from __future__ import annotations

from typing import Iterable

from config.settings import Settings, get_settings
from core.enums import PhotoStatus
from core.exceptions import EntityNotFoundError, RepositoryError, ValidationError
from core.models import PhotoCreate, PhotoRecord, PhotoUpdate
from core.validators import validate_limit, validate_uuid
from storage.supabase_client import SupabaseClientProvider


class PhotosRepository:
    _CREATE_FIELDS = {"id", "original_name", "file_path", "status"}
    _UPDATE_FIELDS = {"status", "file_path", "reserved_at", "consumed_at", "reserved_by_process_id"}
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
        return self.update(
            photo_id,
            PhotoUpdate(status=status, error_message=error_message),
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
        payload = changes.model_dump(mode="json", by_alias=True, exclude_none=True)
        return {
            field: value
            for field, value in payload.items()
            if field in cls._UPDATE_FIELDS
        }
