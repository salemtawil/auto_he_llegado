from __future__ import annotations

import contextlib
from datetime import datetime, timezone

from config.settings import Settings, get_settings
from core.enums import PhotoStatus
from core.exceptions import RepositoryError
from core.models import PhotoUpdate, ReservedPhoto
from services.photo_source_tracker import record_photo_source
from services.temp_file_service import TempFileService
from storage.photos_repository import PhotosRepository
from storage.supabase_client import SupabaseClientProvider


class ProcessPhotoService:
    _MAX_RESERVATION_DOWNLOAD_ATTEMPTS = 500
    _MISSING_STORAGE_REASON = "missing_storage_on_reservation"
    _MISSING_STORAGE_CLEANED_BY = "process_photo_service"
    _CONSUMED_STORAGE_REASON = "consumed_after_use"

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
        self._reserved_storage_buckets: dict[str, tuple[str, str]] = {}

    def validate_atomic_reservation_support(self) -> None:
        if self._atomic_claim_support_validated:
            return
        try:
            self._photos_repository.validate_atomic_claim_support()
        except RepositoryError as exc:
            if self._is_missing_atomic_claim_function_error(exc):
                raise RuntimeError("Falta aplicar la migracion sql/004_functions.sql en Supabase.") from exc
            retry_error = self._retry_atomic_reservation_validation_with_fresh_client()
            if retry_error is None:
                self._atomic_claim_support_validated = True
                return
            raise RuntimeError(
                "No se pudo validar la reserva atomica del pool de fotos. "
                "Esto suele pasar por sesion vencida, cache temporal de Supabase o conexion inestable. "
                f"Detalle: {retry_error}"
            ) from retry_error
        self._atomic_claim_support_validated = True

    def _retry_atomic_reservation_validation_with_fresh_client(self) -> RepositoryError | None:
        reset_client = getattr(self._client_provider, "reset_client", None)
        if callable(reset_client):
            with contextlib.suppress(Exception):
                reset_client()
        try:
            self._photos_repository.validate_atomic_claim_support()
        except RepositoryError as exc:
            return exc
        return None

    @staticmethod
    def _is_missing_atomic_claim_function_error(exc: Exception) -> bool:
        detail = str(exc).lower()
        return (
            "falta aplicar la migracion sql/004_functions.sql" in detail
            or (
                "claim_available_photo" in detail
                and (
                    "pgrst202" in detail
                    or "could not find the function" in detail
                    or "schema cache" in detail
                    or "function public.claim_available_photo" in detail
                )
            )
        )

    def reserve_photo(self, *, process_id: str | None = None) -> ReservedPhoto:
        self.validate_atomic_reservation_support()
        last_missing_error: Exception | None = None
        missing_count = 0
        for _attempt in range(self._MAX_RESERVATION_DOWNLOAD_ATTEMPTS):
            try:
                reserved_photo = self._photos_repository.claim_available(process_id=process_id)
            except Exception as exc:
                if missing_count > 0:
                    raise RuntimeError(
                        f"Se limpiaron {missing_count} entradas rotas del pool, "
                        "pero no quedo ninguna foto disponible valida."
                    ) from exc
                raise
            if not reserved_photo.id or not reserved_photo.storage_path or not reserved_photo.original_filename:
                raise RuntimeError("La reserva atomica devolvio una foto invalida.")

            try:
                content, storage_bucket = self._download_reserved_photo(
                    reserved_photo.storage_path,
                    preferred_bucket=getattr(reserved_photo, "storage_bucket", None),
                )
                local_path = self._temp_file_service.create_photo_copy(
                    content=content,
                    original_filename=reserved_photo.original_filename,
                )
                self._remember_reserved_storage(
                    reserved_photo.id,
                    reserved_photo.storage_path,
                    storage_bucket,
                )
                record_photo_source(process_id, storage_bucket, self._settings)
            except Exception as exc:
                if self._is_storage_missing_error(exc):
                    last_missing_error = exc
                    missing_count += 1
                    self._discard_missing_storage_photo(reserved_photo.id, exc)
                    continue
                self.release_photo(reserved_photo.id)
                raise

            return ReservedPhoto(
                photo_id=reserved_photo.id,
                storage_path=reserved_photo.storage_path,
                local_path=str(local_path),
                original_filename=reserved_photo.original_filename,
                storage_bucket=storage_bucket,
                reserved_by_process_id=reserved_photo.reserved_by_process_id,
            )

        raise RuntimeError(
            f"Se limpiaron {missing_count} entradas rotas del pool, pero todavia "
            "hay demasiadas fotos disponibles sin archivo en Storage. "
            f"Ultimo error: {last_missing_error}"
        )

    def consume_photo(self, photo_id: str) -> None:
        storage_removed = self._remove_consumed_storage_file(photo_id)
        changes = PhotoUpdate(
            status=PhotoStatus.CONSUMED,
            consumed_at=self._utcnow(),
        )
        if storage_removed:
            changes.storage_deleted_at = self._utcnow()
            changes.cleanup_reason = self._CONSUMED_STORAGE_REASON
            changes.cleanup_error = None
            changes.cleaned_by = self._MISSING_STORAGE_CLEANED_BY
        self._photos_repository.update(
            photo_id,
            changes,
        )

    def release_photo(self, photo_id: str) -> None:
        self._reserved_storage_buckets.pop(photo_id, None)
        self._photos_repository.update(
            photo_id,
            PhotoUpdate(
                status=PhotoStatus.AVAILABLE,
                reserved_at=None,
                reserved_by_process_id=None,
            ),
        )

    def _discard_missing_storage_photo(self, photo_id: str, exc: Exception) -> None:
        self._photos_repository.update(
            photo_id,
            PhotoUpdate(
                status=PhotoStatus.DISCARDED,
                reserved_at=None,
                reserved_by_process_id=None,
                storage_deleted_at=self._utcnow(),
                cleanup_reason=self._MISSING_STORAGE_REASON,
                cleanup_error=f"Storage object missing during reservation: {exc}",
                cleaned_by=self._MISSING_STORAGE_CLEANED_BY,
            ),
        )

    def _download_reserved_photo(self, storage_path: str, *, preferred_bucket: str | None = None) -> tuple[bytes, str]:
        normalized_path = self._normalize_storage_path(storage_path)
        last_missing_error: Exception | None = None
        for bucket_name in self._download_bucket_names(preferred_bucket=preferred_bucket):
            try:
                content = self._client_provider.download_binary(
                    bucket_name=bucket_name,
                    storage_path=normalized_path,
                )
                return content, bucket_name
            except Exception as exc:
                if self._is_storage_missing_error(exc):
                    last_missing_error = exc
                    continue
                raise
        if last_missing_error is not None:
            raise last_missing_error
        raise RuntimeError(f"No hay bucket configurado para descargar {normalized_path}.")

    def _download_bucket_names(self, *, preferred_bucket: str | None = None) -> tuple[str, ...]:
        bucket_names = [preferred_bucket, self._settings.supabase_storage_bucket]
        bucket_names.extend(self._settings.supabase_legacy_storage_buckets)
        deduped = []
        for bucket_name in bucket_names:
            normalized = str(bucket_name or "").strip()
            if normalized and normalized not in deduped:
                deduped.append(normalized)
        return tuple(deduped)

    def _remember_reserved_storage(self, photo_id: str, storage_path: str, storage_bucket: str) -> None:
        self._reserved_storage_buckets[photo_id] = (storage_bucket, self._normalize_storage_path(storage_path))

    def _remove_consumed_storage_file(self, photo_id: str) -> bool:
        remembered = self._reserved_storage_buckets.pop(photo_id, None)
        if remembered is None:
            return False
        bucket_name, storage_path = remembered
        try:
            self._client_provider.remove_file(
                bucket_name=bucket_name,
                storage_path=storage_path,
            )
        except Exception:
            return False
        return True

    def delete_local_copy(self, local_path: str) -> None:
        self._temp_file_service.delete_file(local_path)

    @staticmethod
    def _normalize_storage_path(storage_path: str) -> str:
        return storage_path.strip().replace("\\", "/").lstrip("/")

    @staticmethod
    def _is_storage_missing_error(exc: Exception) -> bool:
        normalized = str(exc or "").strip().lower()
        if "failed to download file from supabase storage" in normalized and (
            "404" in normalized or "not_found" in normalized or "not found" in normalized
        ):
            return True
        return any(
            token in normalized
            for token in (
                "not_found",
                "not found",
                "object not found",
                "no such object",
                "missing object",
                "does not exist",
                "statuscode': 404",
                'statuscode": 404',
            )
        )

    @staticmethod
    def _utcnow() -> datetime:
        return datetime.now(timezone.utc)
