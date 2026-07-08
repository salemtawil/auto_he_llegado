from __future__ import annotations

import contextlib
import base64
import json
import time
from threading import RLock
from typing import Any

from supabase import Client, ClientOptions, create_client

from config.settings import Settings, get_settings
from core.exceptions import RepositoryError, SupabaseClientError
from services.auth_context import get_current_session, update_current_session_tokens


_refresh_lock = RLock()
_PROACTIVE_REFRESH_MARGIN_SECONDS = 300


class SupabaseClientProvider:
    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._client: Client | None = None

    @property
    def client(self) -> Client:
        if self._client is None:
            self._client = self._create_client()
        else:
            self._ensure_session_fresh()
        return self._client

    def _create_client(self) -> Client:
        self._settings.require_supabase()
        try:
            options = self._client_options_for_current_session()
            return create_client(
                self._settings.supabase_url or "",
                self._settings.supabase_key or "",
                options,
            )
        except Exception as exc:
            raise SupabaseClientError(
                "Failed to create the Supabase client: "
                f"{self._describe_exception(exc)}"
            ) from exc

    def reset_client(self) -> None:
        self._client = None

    @staticmethod
    def _client_options_for_current_session() -> ClientOptions | None:
        current_session = get_current_session()
        if current_session is None or not current_session.access_token:
            return None
        return ClientOptions(
            headers={"Authorization": f"Bearer {current_session.access_token}"},
            auto_refresh_token=False,
            persist_session=False,
        )

    def execute(self, operation: Any) -> list[dict[str, Any]]:
        response = self.execute_response(operation)
        return list(getattr(response, "data", []) or [])

    def execute_response(self, operation: Any) -> Any:
        self._ensure_session_fresh()
        try:
            return operation.execute()
        except Exception as exc:
            if self._is_jwt_expired_error(exc) and self._refresh_current_session():
                try:
                    return operation.execute()
                except Exception as retry_exc:
                    exc = retry_exc
            raise RepositoryError(
                f"Supabase operation failed: {self._describe_exception(exc)}"
            ) from exc

    def execute_response_factory(self, operation_factory) -> Any:
        self._ensure_session_fresh()
        operation = operation_factory()
        try:
            return operation.execute()
        except Exception as exc:
            if self._is_jwt_expired_error(exc) and self._refresh_current_session():
                try:
                    return operation_factory().execute()
                except Exception as retry_exc:
                    exc = retry_exc
            raise RepositoryError(
                f"Supabase operation failed: {self._describe_exception(exc)}"
            ) from exc

    def _refresh_current_session(self) -> bool:
        current_session = get_current_session()
        if current_session is None or not current_session.refresh_token:
            return False
        stale_access_token = current_session.access_token
        with _refresh_lock:
            latest_session = get_current_session()
            if latest_session is None or not latest_session.refresh_token:
                return False
            if latest_session.access_token and latest_session.access_token != stale_access_token:
                self._apply_auth_header(latest_session.access_token)
                return True
            try:
                client = self._client
                if client is None:
                    client = self._create_client()
                    self._client = client
                response = client.auth.refresh_session(latest_session.refresh_token)
            except Exception:
                return False
            refreshed_session = getattr(response, "session", None)
            if refreshed_session is None:
                return False
            access_token = str(getattr(refreshed_session, "access_token", "") or "")
            refresh_token = str(getattr(refreshed_session, "refresh_token", "") or latest_session.refresh_token)
            if not access_token:
                return False
            update_current_session_tokens(
                access_token=access_token,
                refresh_token=refresh_token,
            )
            self._apply_auth_header(access_token)
            return True

    def _ensure_session_fresh(self) -> None:
        current_session = get_current_session()
        if current_session is None or not current_session.access_token:
            return
        expires_at = self._jwt_expires_at(current_session.access_token)
        if expires_at is None:
            return
        if expires_at - time.time() <= _PROACTIVE_REFRESH_MARGIN_SECONDS:
            self._refresh_current_session()

    def _apply_auth_header(self, access_token: str) -> None:
        if self._client is None:
            return
        auth_header = f"Bearer {access_token}"
        with contextlib.suppress(Exception):
            self._client.options.headers["Authorization"] = auth_header
        with contextlib.suppress(Exception):
            self._client.auth._headers["Authorization"] = auth_header
        with contextlib.suppress(Exception):
            self._client._postgrest = None
        with contextlib.suppress(Exception):
            self._client._storage = None
        with contextlib.suppress(Exception):
            self._client._functions = None

    def upload_binary(
        self,
        *,
        bucket_name: str,
        storage_path: str,
        content: bytes,
        content_type: str = "image/jpeg",
        upsert: bool = False,
    ) -> None:
        try:
            self._run_storage_operation(
                lambda: self.client.storage.from_(bucket_name).upload(
                    path=storage_path,
                    file=content,
                    file_options={
                        "content-type": content_type,
                        "upsert": upsert,
                    },
                )
            )
        except Exception as exc:
            raise SupabaseClientError(
                "Failed to upload file to Supabase Storage "
                f"({storage_path}): {self._describe_exception(exc)}"
            ) from exc

    def remove_file(self, *, bucket_name: str, storage_path: str) -> None:
        try:
            self._run_storage_operation(
                lambda: self.client.storage.from_(bucket_name).remove([storage_path])
            )
        except Exception as exc:
            raise SupabaseClientError(
                "Failed to remove file from Supabase Storage "
                f"({storage_path}): {self._describe_exception(exc)}"
            ) from exc

    def remove_files(self, *, bucket_name: str, storage_paths: list[str]) -> None:
        normalized_paths = [str(path).strip().replace("\\", "/").lstrip("/") for path in storage_paths if str(path).strip()]
        if not normalized_paths:
            return
        try:
            self._run_storage_operation(
                lambda: self.client.storage.from_(bucket_name).remove(normalized_paths)
            )
        except Exception as exc:
            raise SupabaseClientError(
                "Failed to remove files from Supabase Storage "
                f"({len(normalized_paths)} files): {self._describe_exception(exc)}"
            ) from exc

    def move_file(
        self,
        *,
        bucket_name: str,
        from_path: str,
        to_path: str,
    ) -> None:
        try:
            self._run_storage_operation(
                lambda: self.client.storage.from_(bucket_name).move(from_path, to_path)
            )
        except Exception as exc:
            raise SupabaseClientError(
                "Failed to move file inside Supabase Storage "
                f"({from_path} -> {to_path}): {self._describe_exception(exc)}"
            ) from exc

    def list_files(
        self,
        *,
        bucket_name: str,
        folder_path: str = "",
        limit: int = 1000,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        try:
            return list(
                self._run_storage_operation(
                    lambda: self.client.storage.from_(bucket_name).list(
                        folder_path,
                        {
                            "limit": limit,
                            "offset": offset,
                        },
                    )
                )
                or []
            )
        except Exception as exc:
            raise SupabaseClientError(
                "Failed to list files from Supabase Storage "
                f"({folder_path}): {self._describe_exception(exc)}"
            ) from exc

    def get_bucket_info(self, *, bucket_name: str) -> dict[str, Any]:
        try:
            bucket = self._run_storage_operation(
                lambda: self.client.storage.get_bucket(bucket_name)
            )
        except Exception as exc:
            raise SupabaseClientError(
                "Failed to read Supabase Storage bucket info "
                f"({bucket_name}): {self._describe_exception(exc)}"
            ) from exc
        if isinstance(bucket, dict):
            return dict(bucket)
        data = getattr(bucket, "dict", None)
        if callable(data):
            return dict(data())
        data = getattr(bucket, "model_dump", None)
        if callable(data):
            return dict(data())
        return dict(getattr(bucket, "__dict__", {}) or {})

    def download_binary(
        self,
        *,
        bucket_name: str,
        storage_path: str,
    ) -> bytes:
        try:
            return self._run_storage_operation(
                lambda: self.client.storage.from_(bucket_name).download(storage_path)
            )
        except Exception as exc:
            raise SupabaseClientError(
                "Failed to download file from Supabase Storage "
                f"({storage_path}): {self._describe_exception(exc)}"
            ) from exc

    def _run_storage_operation(self, operation):
        self._ensure_session_fresh()
        try:
            return operation()
        except Exception as exc:
            if self._is_jwt_expired_error(exc) and self._refresh_current_session():
                return operation()
            raise

    @staticmethod
    def _describe_exception(exc: Exception) -> str:
        message = str(exc).strip()
        if message:
            return message
        return exc.__class__.__name__

    @staticmethod
    def _is_jwt_expired_error(exc: Exception) -> bool:
        normalized = str(exc or "").strip().lower()
        return (
            "jwt expired" in normalized
            or "pgrst303" in normalized
            or "exp claim timestamp check failed" in normalized
        )

    @staticmethod
    def _jwt_expires_at(access_token: str) -> float | None:
        parts = str(access_token or "").split(".")
        if len(parts) < 2:
            return None
        payload = parts[1]
        payload += "=" * (-len(payload) % 4)
        try:
            decoded = base64.urlsafe_b64decode(payload.encode("ascii"))
            claims = json.loads(decoded.decode("utf-8"))
            exp = claims.get("exp")
            return float(exp) if exp is not None else None
        except Exception:
            return None
