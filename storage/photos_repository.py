from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Iterable

from config.settings import Settings, get_settings
from core.enums import PhotoStatus
from core.exceptions import EntityNotFoundError, RepositoryError, ValidationError
from core.models import PhotoCreate, PhotoRecord, PhotoUpdate
from core.validators import validate_limit, validate_uuid
from storage.supabase_client import SupabaseClientProvider


class PhotosRepository:
    _DB_ERROR_AFTER_STORAGE_DELETE_PREFIX = "Storage borrado, pero fallo update DB:"
    _CREATE_FIELDS = {"id", "original_name", "file_path", "status", "storage_bucket"}
    _UPDATE_FIELDS = {
        "status",
        "file_path",
        "storage_bucket",
        "reserved_at",
        "consumed_at",
        "reserved_by_process_id",
        "storage_deleted_at",
        "cleanup_reason",
        "cleanup_error",
        "cleaned_by",
    }
    _MIGRATION_REQUIRED_MESSAGE = "Falta aplicar la migración sql/004_functions.sql en Supabase."

    def __init__(
        self,
        client_provider: SupabaseClientProvider | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._client_provider = client_provider or SupabaseClientProvider(self._settings)
        self._table = self._settings.supabase_photos_table

    def create(self, photo: PhotoCreate) -> PhotoRecord:
        payload = self._serialize_create(photo)
        try:
            rows = self._client_provider.execute(
                self._client_provider.client.table(self._table).insert(payload)
            )
        except RepositoryError as exc:
            raise RepositoryError(
                f"Failed to insert photo record into '{self._table}': {exc}"
            ) from exc
        return self._single_row(rows, "Photo was not created.")

    def bulk_create(self, photos: Iterable[PhotoCreate]) -> list[PhotoRecord]:
        payload = [self._serialize_create(photo) for photo in photos]
        if not payload:
            return []
        rows = self._client_provider.execute(
            self._client_provider.client.table(self._table).insert(payload)
        )
        return [PhotoRecord.model_validate(row) for row in rows]

    def get_by_id(self, photo_id: str) -> PhotoRecord:
        validated_id = validate_uuid(photo_id, "photo_id")
        rows = self._client_provider.execute(
            self._client_provider.client.table(self._table)
            .select("*")
            .eq("id", validated_id)
            .limit(1)
        )
        return self._single_row(rows, f"Photo '{validated_id}' was not found.")

    def list(
        self,
        *,
        status: PhotoStatus | None = None,
        limit: int = 100,
    ) -> list[PhotoRecord]:
        validated_limit = validate_limit(limit)
        query = self._client_provider.client.table(self._table).select("*").limit(
            validated_limit
        )
        if status is not None:
            query = query.eq("status", status.value)
        rows = self._client_provider.execute(query)
        return [PhotoRecord.model_validate(row) for row in rows]

    def update(self, photo_id: str, changes: PhotoUpdate) -> PhotoRecord:
        validated_id = validate_uuid(photo_id, "photo_id")
        payload = self._serialize_update(changes)
        if not payload:
            raise ValidationError("At least one field must be provided to update.")
        rows = self._client_provider.execute(
            self._client_provider.client.table(self._table)
            .update(payload)
            .eq("id", validated_id)
        )
        return self._single_row(rows, f"Photo '{validated_id}' was not found.")

    def claim_available(self, *, process_id: str | None = None) -> PhotoRecord:
        try:
            rows = self._client_provider.execute(
                self._client_provider.client.rpc(
                    "claim_available_photo",
                    {"p_process_id": process_id},
                )
            )
        except RepositoryError as exc:
            raise RepositoryError(
                f"{self._MIGRATION_REQUIRED_MESSAGE} "
                "Atomic photo claim failed. "
                f"Details: {exc}"
            ) from exc
        return self._single_row(rows, "No hay fotos disponibles en el pool.")

    def validate_atomic_claim_support(self) -> None:
        try:
            self._client_provider.execute_response(
                self._client_provider.client.table(self._table)
                .select("id,reserved_by_process_id")
                .limit(1)
            )
            self._client_provider.execute_response(
                self._client_provider.client.rpc(
                    "claim_available_photo",
                    {
                        "p_process_id": "__migration_validation__",
                        "p_validate_only": True,
                    },
                )
            )
        except RepositoryError as exc:
            raise RepositoryError(
                f"{self._MIGRATION_REQUIRED_MESSAGE} Details: {exc}"
            ) from exc

    def update_status(
        self,
        photo_id: str,
        status: PhotoStatus,
        *,
        error_message: str | None = None,
    ) -> PhotoRecord:
        if error_message is not None:
            raise ValidationError(
                "error_message no esta soportado por el schema local confirmado de photos."
            )
        return self.update(
            photo_id,
            PhotoUpdate(status=status),
        )

    def count_available(self) -> int:
        return self.count_by_status(PhotoStatus.AVAILABLE)

    def count_by_status(self, status: PhotoStatus) -> int:
        response = self._client_provider.execute_response(
            self._client_provider.client.table(self._table)
            .select("id", count="exact")
            .eq("status", status.value)
        )
        return int(getattr(response, "count", 0) or 0)

    def count_storage_cleaned(self, status: PhotoStatus | None = None) -> int:
        query = self._client_provider.client.table(self._table).select("id", count="exact").not_.is_(
            "storage_deleted_at",
            "null",
        )
        if status is not None:
            query = query.eq("status", status.value)
        response = self._client_provider.execute_response(query)
        return int(getattr(response, "count", 0) or 0)

    def count_cleanup_errors(self) -> int:
        response = self._client_provider.execute_response(
            self._client_provider.client.table(self._table)
            .select("id", count="exact")
            .not_.is_("cleanup_error", "null")
        )
        return int(getattr(response, "count", 0) or 0)

    def count_db_error_after_storage_delete(self) -> int:
        response = self._client_provider.execute_response(
            self._client_provider.client.table(self._table)
            .select("id", count="exact")
            .not_.is_("file_path", "null")
            .is_("storage_deleted_at", "null")
            .like(
                "cleanup_error",
                f"{self._DB_ERROR_AFTER_STORAGE_DELETE_PREFIX}%",
            )
        )
        return int(getattr(response, "count", 0) or 0)

    def count_consumed_pending_cleanup(self) -> int:
        return self._count_pending_storage_cleanup(PhotoStatus.CONSUMED)

    def count_consumed_cleanable_pending_cleanup(self) -> int:
        return self._count_pending_storage_cleanup(PhotoStatus.CONSUMED, exclude_cleanup_errors=True)

    def count_stale_reserved_pending_cleanup(self, *, older_than_hours: int) -> int:
        cutoff = self._stale_reserved_cutoff(older_than_hours)
        response = self._client_provider.execute_response(
            self._client_provider.client.table(self._table)
            .select("id", count="exact")
            .eq("status", PhotoStatus.RESERVED.value)
            .not_.is_("file_path", "null")
            .is_("storage_deleted_at", "null")
            .not_.is_("reserved_at", "null")
            .lt("reserved_at", cutoff)
        )
        return int(getattr(response, "count", 0) or 0)

    def count_stale_reserved_cleanable_pending_cleanup(self, *, older_than_hours: int) -> int:
        cutoff = self._stale_reserved_cutoff(older_than_hours)
        response = self._client_provider.execute_response(
            self._client_provider.client.table(self._table)
            .select("id", count="exact")
            .eq("status", PhotoStatus.RESERVED.value)
            .not_.is_("file_path", "null")
            .is_("storage_deleted_at", "null")
            .is_("cleanup_error", "null")
            .not_.is_("reserved_at", "null")
            .lt("reserved_at", cutoff)
        )
        return int(getattr(response, "count", 0) or 0)

    def list_consumed_pending_cleanup(self, limit: int = 100, *, exclude_cleanup_errors: bool = False) -> list[PhotoRecord]:
        validated_limit = validate_limit(limit)
        query = (
            self._client_provider.client.table(self._table)
            .select("*")
            .eq("status", PhotoStatus.CONSUMED.value)
            .not_.is_("file_path", "null")
            .is_("storage_deleted_at", "null")
            .order("consumed_at", desc=False, nullsfirst=True)
            .limit(validated_limit)
        )
        if exclude_cleanup_errors:
            query = query.is_("cleanup_error", "null")
        rows = self._client_provider.execute(query)
        return [PhotoRecord.model_validate(row) for row in rows]

    def list_stale_reserved_pending_cleanup(
        self,
        *,
        older_than_hours: int,
        limit: int = 100,
        exclude_cleanup_errors: bool = False,
    ) -> list[PhotoRecord]:
        validated_limit = validate_limit(limit)
        cutoff = self._stale_reserved_cutoff(older_than_hours)
        query = (
            self._client_provider.client.table(self._table)
            .select("*")
            .eq("status", PhotoStatus.RESERVED.value)
            .not_.is_("file_path", "null")
            .is_("storage_deleted_at", "null")
            .not_.is_("reserved_at", "null")
            .lt("reserved_at", cutoff)
            .order("reserved_at", desc=False, nullsfirst=True)
            .limit(validated_limit)
        )
        if exclude_cleanup_errors:
            query = query.is_("cleanup_error", "null")
        rows = self._client_provider.execute(query)
        return [PhotoRecord.model_validate(row) for row in rows]

    def list_db_error_after_storage_delete(self, *, limit: int = 100) -> list[PhotoRecord]:
        validated_limit = validate_limit(limit)
        rows = self._client_provider.execute(
            self._client_provider.client.table(self._table)
            .select("*")
            .not_.is_("file_path", "null")
            .is_("storage_deleted_at", "null")
            .like(
                "cleanup_error",
                f"{self._DB_ERROR_AFTER_STORAGE_DELETE_PREFIX}%",
            )
            .limit(validated_limit)
        )
        return [PhotoRecord.model_validate(row) for row in rows]

    def mark_storage_cleaned(self, photo_id: str, *, reason: str, cleaned_by: str) -> PhotoRecord:
        return self.update(
            photo_id,
            PhotoUpdate(
                storage_deleted_at=self._utcnow(),
                cleanup_reason=reason,
                cleanup_error=None,
                cleaned_by=cleaned_by,
            ),
        )

    def mark_cleanup_error(self, photo_id: str, *, error: str) -> PhotoRecord:
        return self.update(
            photo_id,
            PhotoUpdate(
                cleanup_error=error,
            ),
        )

    def mark_stale_reserved_cleaned(
        self,
        photo_id: str,
        *,
        reason: str,
        cleaned_by: str,
    ) -> PhotoRecord:
        return self.update(
            photo_id,
            PhotoUpdate(
                status=PhotoStatus.DISCARDED,
                reserved_by_process_id=None,
                storage_deleted_at=self._utcnow(),
                cleanup_reason=reason,
                cleanup_error=None,
                cleaned_by=cleaned_by,
            ),
        )

    @staticmethod
    def _single_row(rows: list[dict], not_found_message: str) -> PhotoRecord:
        if not rows:
            raise EntityNotFoundError(not_found_message)
        return PhotoRecord.model_validate(rows[0])

    @classmethod
    def _serialize_create(cls, photo: PhotoCreate) -> dict:
        payload = photo.model_dump(mode="json", by_alias=True, exclude_none=True)
        return {
            field: value
            for field, value in payload.items()
            if field in cls._CREATE_FIELDS
        }

    @classmethod
    def _serialize_update(cls, changes: PhotoUpdate) -> dict:
        payload = changes.model_dump(mode="json", by_alias=True, exclude_unset=True)
        return {
            field: value
            for field, value in payload.items()
            if field in cls._UPDATE_FIELDS
        }

    def _count_pending_storage_cleanup(self, status: PhotoStatus, exclude_cleanup_errors: bool = False) -> int:
        query = (
            self._client_provider.client.table(self._table)
            .select("id", count="exact")
            .eq("status", status.value)
            .not_.is_("file_path", "null")
            .is_("storage_deleted_at", "null")
        )
        if exclude_cleanup_errors:
            query = query.is_("cleanup_error", "null")
        response = self._client_provider.execute_response(query)
        return int(getattr(response, "count", 0) or 0)

    @staticmethod
    def _stale_reserved_cutoff(older_than_hours: int) -> str:
        normalized_hours = max(int(older_than_hours), 1)
        return (datetime.now(timezone.utc) - timedelta(hours=normalized_hours)).isoformat()

    @staticmethod
    def _utcnow() -> datetime:
        return datetime.now(timezone.utc)
