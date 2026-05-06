from __future__ import annotations

from datetime import datetime, timezone

from config.settings import Settings, get_settings
from core.enums import PhotoStatus
from core.exceptions import RepositoryError
from core.models import PhotoUpdate, ReservedPhoto
from services.temp_file_service import TempFileService
from storage.photos_repository import PhotosRepository
from storage.supabase_client import SupabaseClientProvider


class ProcessPhotoService:
    def __init__(
        self,
        photos_repository: PhotosRepository | None = None,
        client_provider: SupabaseClientProvider | None = None,
        temp_file_service: TempFileService | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._client_provider = client_provider or SupabaseClientProvider(self._settings)
        self._photos_repository = photos_repository or PhotosRepository(
            client_provider=self._client_provider,
            settings=self._settings,
        )
        self._temp_file_service = temp_file_service or TempFileService(self._settings)
        self._atomic_claim_support_validated = False

    def validate_atomic_reservation_support(self) -> None:
        if self._atomic_claim_support_validated:
            return
        try:
            self._photos_repository.validate_atomic_claim_support()
        except RepositoryError as exc:
            raise RuntimeError("Falta aplicar la migración sql/004_functions.sql en Supabase.") from exc
        self._atomic_claim_support_validated = True

    def reserve_photo(self, *, process_id: str | None = None) -> ReservedPhoto:
        self.validate_atomic_reservation_support()
        reserved_photo = self._photos_repository.claim_available(process_id=process_id)
        if not reserved_photo.id or not reserved_photo.storage_path or not reserved_photo.original_filename:
            raise RuntimeError("La reserva atómica devolvió una foto inválida.")

        try:
            content = self._client_provider.download_binary(
                bucket_name=self._settings.supabase_storage_bucket,
                storage_path=self._normalize_storage_path(reserved_photo.storage_path),
            )
            local_path = self._temp_file_service.create_photo_copy(
                content=content,
                original_filename=reserved_photo.original_filename,
            )
        except Exception:
            self.release_photo(reserved_photo.id)
            raise

        return ReservedPhoto(
            photo_id=reserved_photo.id,
            storage_path=reserved_photo.storage_path,
            local_path=str(local_path),
            original_filename=reserved_photo.original_filename,
            reserved_by_process_id=reserved_photo.reserved_by_process_id,
        )

    def consume_photo(self, photo_id: str) -> None:
        self._photos_repository.update(
            photo_id,
            PhotoUpdate(
                status=PhotoStatus.CONSUMED,
                consumed_at=self._utcnow(),
            ),
        )

    def release_photo(self, photo_id: str) -> None:
        self._photos_repository.update(
            photo_id,
            PhotoUpdate(
                status=PhotoStatus.AVAILABLE,
                reserved_at=None,
                reserved_by_process_id=None,
            ),
        )

    def delete_local_copy(self, local_path: str) -> None:
        self._temp_file_service.delete_file(local_path)

    @staticmethod
    def _normalize_storage_path(storage_path: str) -> str:
        return storage_path.replace("\\", "/")

    @staticmethod
    def _utcnow() -> datetime:
        return datetime.now(timezone.utc)
