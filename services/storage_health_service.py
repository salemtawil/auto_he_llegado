from __future__ import annotations

from config.settings import Settings, get_settings
from core.models import StorageHealthSnapshot
from storage.photos_repository import PhotosRepository
from storage.supabase_client import SupabaseClientProvider


class StorageHealthService:
    _SAMPLE_LIMIT_PER_BUCKET = 250

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

    def get_snapshot(self) -> StorageHealthSnapshot:
        bucket_names = self._bucket_names()
        active_photo_count = self._photos_repository.count_active_storage_records()
        sample_sizes = self._sample_storage_file_sizes(bucket_names)
        average_file_size = int(sum(sample_sizes) / len(sample_sizes)) if sample_sizes else 0
        estimated_used = active_photo_count * average_file_size if average_file_size else 0
        configured_limit = self._configured_limit_bytes()
        estimated_available = None
        estimated_capacity = None
        estimated_remaining = None
        if configured_limit is not None and average_file_size > 0:
            estimated_available = max(configured_limit - estimated_used, 0)
            estimated_capacity = max(configured_limit // average_file_size, 0)
            estimated_remaining = max(estimated_capacity - active_photo_count, 0)
        return StorageHealthSnapshot(
            bucket_names=bucket_names,
            active_photo_count=active_photo_count,
            sampled_file_count=len(sample_sizes),
            average_file_size_bytes=average_file_size,
            estimated_used_bytes=estimated_used,
            configured_limit_bytes=configured_limit,
            estimated_available_bytes=estimated_available,
            estimated_capacity_photos=estimated_capacity,
            estimated_remaining_photos=estimated_remaining,
            status=self._resolve_status(configured_limit, estimated_used),
            note=self._build_note(sample_sizes, configured_limit),
        )

    def _bucket_names(self) -> list[str]:
        bucket_names = [self._settings.supabase_storage_bucket]
        bucket_names.extend(self._settings.supabase_legacy_storage_buckets)
        normalized: list[str] = []
        seen: set[str] = set()
        for bucket_name in bucket_names:
            value = str(bucket_name or "").strip()
            if value and value not in seen:
                normalized.append(value)
                seen.add(value)
        return normalized

    def _sample_storage_file_sizes(self, bucket_names: list[str]) -> list[int]:
        sizes: list[int] = []
        for bucket_name in bucket_names:
            try:
                files = self._client_provider.list_files(
                    bucket_name=bucket_name,
                    folder_path="available",
                    limit=self._SAMPLE_LIMIT_PER_BUCKET,
                    offset=0,
                )
            except Exception:
                continue
            for item in files:
                size = self._extract_file_size(item)
                if size > 0:
                    sizes.append(size)
        return sizes

    def _configured_limit_bytes(self) -> int | None:
        limit_mb = int(self._settings.supabase_storage_limit_mb or 0)
        if limit_mb <= 0:
            return None
        return limit_mb * 1024 * 1024

    @staticmethod
    def _extract_file_size(item: dict) -> int:
        metadata = item.get("metadata") if isinstance(item, dict) else None
        candidates = []
        if isinstance(metadata, dict):
            candidates.extend(
                [
                    metadata.get("size"),
                    metadata.get("contentLength"),
                    metadata.get("content_length"),
                    metadata.get("Content-Length"),
                ]
            )
        if isinstance(item, dict):
            candidates.append(item.get("size"))
        for value in candidates:
            try:
                size = int(value)
            except (TypeError, ValueError):
                continue
            if size > 0:
                return size
        return 0

    @staticmethod
    def _resolve_status(configured_limit: int | None, estimated_used: int) -> str:
        if configured_limit is None or configured_limit <= 0:
            return "Sin limite configurado"
        if estimated_used <= 0:
            return "Sin muestra"
        usage_ratio = estimated_used / configured_limit
        if usage_ratio >= 0.9:
            return "Critico"
        if usage_ratio >= 0.75:
            return "Alto"
        return "Saludable"

    @staticmethod
    def _build_note(sample_sizes: list[int], configured_limit: int | None) -> str:
        if not sample_sizes:
            return "No se encontraron tamanos de archivo en la muestra de Storage."
        if configured_limit is None:
            return "Uso estimado con muestra real; configura SUPABASE_STORAGE_LIMIT_MB para calcular espacio libre."
        return "Uso y capacidad estimados con muestra real de archivos JPG."
