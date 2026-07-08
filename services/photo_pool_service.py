from __future__ import annotations

from dataclasses import dataclass

from config.settings import Settings, get_settings
from core.enums import PhotoStatus
from storage.photos_repository import PhotosRepository
from storage.supabase_client import SupabaseClientProvider


@dataclass(frozen=True)
class PhotoPoolSnapshot:
    available_count: int
    color: str
    label: str
    new_bucket_name: str = ""
    new_bucket_count: int = 0
    old_bucket_name: str = ""
    old_bucket_count: int = 0


class PhotoPoolService:
    def __init__(
        self,
        photos_repository: PhotosRepository | None = None,
        client_provider: SupabaseClientProvider | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._client_provider = client_provider or SupabaseClientProvider(self._settings)
        self._photos_repository = photos_repository or PhotosRepository(
            client_provider=self._client_provider,
            settings=self._settings,
        )

    def get_snapshot(self) -> PhotoPoolSnapshot:
        old_bucket_name = self._settings.supabase_legacy_storage_buckets[0] if self._settings.supabase_legacy_storage_buckets else ""
        rpc_snapshot = self._get_snapshot_from_rpc(old_bucket_name=old_bucket_name)
        if rpc_snapshot is not None:
            return rpc_snapshot
        new_count, old_count = self._count_available_records_by_bucket(old_bucket_name=old_bucket_name)
        display_count = new_count + old_count
        color, label = self._resolve_state(display_count)
        return PhotoPoolSnapshot(
            available_count=display_count,
            color=color,
            label=label,
            new_bucket_name=self._settings.supabase_storage_bucket,
            new_bucket_count=new_count,
            old_bucket_name=old_bucket_name,
            old_bucket_count=old_count,
        )

    def _get_snapshot_from_rpc(self, *, old_bucket_name: str) -> PhotoPoolSnapshot | None:
        try:
            response = self._client_provider.execute_response_factory(
                lambda: self._client_provider.client.rpc(
                    "photo_pool_counts",
                    {
                        "p_active_bucket": self._settings.supabase_storage_bucket,
                        "p_legacy_bucket": old_bucket_name or None,
                    },
                )
            )
        except Exception:
            return None
        rows = list(getattr(response, "data", []) or [])
        if not rows:
            return None
        row = dict(rows[0])
        new_count = int(row.get("new_bucket_count") or 0)
        old_count = int(row.get("old_bucket_count") or 0)
        display_count = int(row.get("available_count") or (new_count + old_count))
        color, label = self._resolve_state(display_count)
        return PhotoPoolSnapshot(
            available_count=display_count,
            color=color,
            label=label,
            new_bucket_name=self._settings.supabase_storage_bucket,
            new_bucket_count=new_count,
            old_bucket_name=old_bucket_name,
            old_bucket_count=old_count,
        )

    def _count_available_records_by_bucket(self, *, old_bucket_name: str) -> tuple[int, int]:
        total_count = self._count_available_rows()
        try:
            new_count = self._count_available_rows(bucket_name=self._settings.supabase_storage_bucket)
            old_count = self._count_available_rows(bucket_name=old_bucket_name) if old_bucket_name else 0
            unknown_count = self._count_available_rows(bucket_is_null=True)
        except Exception:
            return 0, total_count
        old_count += unknown_count
        if new_count + old_count > total_count:
            old_count = max(total_count - new_count, 0)
        return new_count, old_count

    def _count_available_rows(
        self,
        *,
        bucket_name: str | None = None,
        bucket_is_null: bool = False,
    ) -> int:
        def build_query():
            query = (
                self._client_provider.client.table(self._settings.supabase_photos_table)
                .select("id", count="exact")
                .eq("status", PhotoStatus.AVAILABLE.value)
                .is_("storage_deleted_at", "null")
                .limit(1)
            )
            if bucket_name:
                query = query.eq("storage_bucket", bucket_name)
            elif bucket_is_null:
                query = query.is_("storage_bucket", "null")
            return query

        response = self._client_provider.execute_response_factory(build_query)
        return int(getattr(response, "count", 0) or 0)

    @staticmethod
    def _resolve_state(count: int) -> tuple[str, str]:
        if count <= 20:
            return "#b44545", "Nivel bajo"
        if count <= 60:
            return "#c28a1b", "Nivel medio"
        return "#2f7d4a", "Nivel alto"
