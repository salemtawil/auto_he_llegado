from __future__ import annotations

from typing import Any

from supabase import Client, create_client

from config.settings import Settings, get_settings
from core.exceptions import RepositoryError, SupabaseClientError
from services.auth_context import get_current_session


class SupabaseClientProvider:
    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._client: Client | None = None

    @property
    def client(self) -> Client:
        if self._client is None:
            self._settings.require_supabase()
            try:
                self._client = create_client(
                    self._settings.supabase_url or "",
                    self._settings.supabase_key or "",
                )
                current_session = get_current_session()
                if current_session is not None:
                    self._client.auth.set_session(
                        current_session.access_token,
                        current_session.refresh_token,
                    )
            except Exception as exc:
                raise SupabaseClientError(
                    "Failed to create the Supabase client: "
                    f"{self._describe_exception(exc)}"
                ) from exc
        return self._client

    def execute(self, operation: Any) -> list[dict[str, Any]]:
        response = self.execute_response(operation)
        return list(getattr(response, "data", []) or [])

    def execute_response(self, operation: Any) -> Any:
        try:
            return operation.execute()
        except Exception as exc:
            raise RepositoryError(
                f"Supabase operation failed: {self._describe_exception(exc)}"
            ) from exc

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
            self.client.storage.from_(bucket_name).upload(
                path=storage_path,
                file=content,
                file_options={
                    "content-type": content_type,
                    "upsert": upsert,
                },
            )
        except Exception as exc:
            raise SupabaseClientError(
                "Failed to upload file to Supabase Storage "
                f"({storage_path}): {self._describe_exception(exc)}"
            ) from exc

    def remove_file(self, *, bucket_name: str, storage_path: str) -> None:
        try:
            self.client.storage.from_(bucket_name).remove([storage_path])
        except Exception as exc:
            raise SupabaseClientError(
                "Failed to remove file from Supabase Storage "
                f"({storage_path}): {self._describe_exception(exc)}"
            ) from exc

    def move_file(
        self,
        *,
        bucket_name: str,
        from_path: str,
        to_path: str,
    ) -> None:
        try:
            self.client.storage.from_(bucket_name).move(from_path, to_path)
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
                self.client.storage.from_(bucket_name).list(
                    folder_path,
                    {
                        "limit": limit,
                        "offset": offset,
                    },
                )
                or []
            )
        except Exception as exc:
            raise SupabaseClientError(
                "Failed to list files from Supabase Storage "
                f"({folder_path}): {self._describe_exception(exc)}"
            ) from exc

    def download_binary(
        self,
        *,
        bucket_name: str,
        storage_path: str,
    ) -> bytes:
        try:
            return self.client.storage.from_(bucket_name).download(storage_path)
        except Exception as exc:
            raise SupabaseClientError(
                "Failed to download file from Supabase Storage "
                f"({storage_path}): {self._describe_exception(exc)}"
            ) from exc

    @staticmethod
    def _describe_exception(exc: Exception) -> str:
        message = str(exc).strip()
        if message:
            return message
        return exc.__class__.__name__
