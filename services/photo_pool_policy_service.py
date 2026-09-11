from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from config.settings import Settings, get_settings
from storage.supabase_client import SupabaseClientProvider


@dataclass(frozen=True)
class PhotoPoolPolicy:
    bucket: str
    available_prefix: str = "available"
    candidates_prefix: str = "candidates"
    source: str = "local"


class PhotoPoolPolicyService:
    _DEFAULT_AVAILABLE_PREFIX = "available"
    _DEFAULT_CANDIDATES_PREFIX = "candidates"

    def __init__(
        self,
        client_provider: SupabaseClientProvider | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._client_provider = client_provider or SupabaseClientProvider(self._settings)

    def get_policy(self) -> PhotoPoolPolicy:
        try:
            rows = self._client_provider.execute(
                self._client_provider.client.rpc("get_photo_pool_policy", {})
            )
        except Exception:
            return self._fallback_policy()
        row = dict(rows[0]) if rows else {}
        bucket = self._normalize_bucket(row.get("bucket"))
        if not bucket:
            return self._fallback_policy()
        return PhotoPoolPolicy(
            bucket=bucket,
            available_prefix=self._normalize_prefix(row.get("available_prefix"), self._DEFAULT_AVAILABLE_PREFIX),
            candidates_prefix=self._normalize_prefix(row.get("candidates_prefix"), self._DEFAULT_CANDIDATES_PREFIX),
            source="supabase",
        )

    def update_policy(
        self,
        *,
        bucket: str,
        available_prefix: str = _DEFAULT_AVAILABLE_PREFIX,
        candidates_prefix: str = _DEFAULT_CANDIDATES_PREFIX,
    ) -> PhotoPoolPolicy:
        normalized_bucket = self._normalize_bucket(bucket)
        if not normalized_bucket:
            raise ValueError("Ingresa un bucket valido para el pool.")
        normalized_available = self._normalize_prefix(available_prefix, self._DEFAULT_AVAILABLE_PREFIX)
        normalized_candidates = self._normalize_prefix(candidates_prefix, self._DEFAULT_CANDIDATES_PREFIX)
        payload = {
            "key": "photo_pool",
            "value": {
                "bucket": normalized_bucket,
                "available_prefix": normalized_available,
                "candidates_prefix": normalized_candidates,
            },
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        rows = self._client_provider.execute(
            self._client_provider.client.table("app_settings").upsert(payload)
        )
        if not rows:
            raise RuntimeError("No se actualizo la politica del pool de fotos.")
        return PhotoPoolPolicy(
            bucket=normalized_bucket,
            available_prefix=normalized_available,
            candidates_prefix=normalized_candidates,
            source="supabase",
        )

    def list_buckets(self) -> list[str]:
        buckets = self._list_buckets_from_rpc()
        if buckets:
            return buckets
        buckets = self._list_buckets_from_storage_api()
        fallback = [
            self._settings.supabase_storage_bucket,
            *self._settings.supabase_legacy_storage_buckets,
        ]
        return self._unique_bucket_names([*buckets, *fallback])

    def _fallback_policy(self) -> PhotoPoolPolicy:
        return PhotoPoolPolicy(
            bucket=self._normalize_bucket(self._settings.supabase_storage_bucket) or "photo-pool",
            available_prefix=self._DEFAULT_AVAILABLE_PREFIX,
            candidates_prefix=self._DEFAULT_CANDIDATES_PREFIX,
            source="local",
        )

    def _list_buckets_from_rpc(self) -> list[str]:
        try:
            rows = self._client_provider.execute(
                self._client_provider.client.rpc("list_photo_pool_buckets", {})
            )
        except Exception:
            return []
        return self._unique_bucket_names(row.get("bucket") or row.get("id") for row in rows)

    def _list_buckets_from_storage_api(self) -> list[str]:
        try:
            buckets = self._client_provider.list_buckets()
        except Exception:
            return []
        return self._unique_bucket_names(self._bucket_name_from_payload(bucket) for bucket in buckets)

    @staticmethod
    def _normalize_bucket(value) -> str:
        return str(value or "").strip().strip("/")

    @staticmethod
    def _normalize_prefix(value, default: str) -> str:
        normalized = str(value or "").strip().strip("/")
        return normalized or default

    @staticmethod
    def _bucket_name_from_payload(payload: dict[str, Any]) -> str:
        return str(payload.get("id") or payload.get("name") or "").strip()

    @classmethod
    def _unique_bucket_names(cls, bucket_names) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []
        for bucket_name in bucket_names:
            normalized = cls._normalize_bucket(bucket_name)
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            result.append(normalized)
        return result
