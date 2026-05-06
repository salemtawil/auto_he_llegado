from __future__ import annotations

from config.settings import Settings, get_settings
from core.exceptions import EntityNotFoundError, RepositoryError, ValidationError
from core.models import ProcessLogCreate, ProcessLogRecord, ProcessLogUpdate
from core.validators import validate_limit, validate_positive_int
from storage.supabase_client import SupabaseClientProvider


class ProcessLogsRepository:
    def __init__(
        self,
        client_provider: SupabaseClientProvider | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._client_provider = client_provider or SupabaseClientProvider(self._settings)
        self._table = self._settings.supabase_process_logs_table

    def create(self, log_entry: ProcessLogCreate) -> ProcessLogRecord:
        payload = log_entry.model_dump(mode="json", exclude_none=True)
        rows = self._client_provider.execute(
            self._client_provider.client.table(self._table).insert(payload)
        )
        if not rows:
            raise RepositoryError(
                "Process log insert completed without returning the created row. "
                "The initial log ID could not be confirmed."
            )
        return self._single_row(rows, "Process log was not created.")

    def get_by_id(self, log_id: int) -> ProcessLogRecord:
        validated_id = validate_positive_int(log_id, "log_id")
        rows = self._client_provider.execute(
            self._client_provider.client.table(self._table)
            .select("*")
            .eq("id", validated_id)
            .limit(1)
        )
        return self._single_row(rows, f"Process log '{validated_id}' was not found.")

    def list(
        self,
        *,
        site: str | None = None,
        action: str | None = None,
        final_status: str | None = None,
        phase: str | None = None,
        limit: int = 100,
    ) -> list[ProcessLogRecord]:
        validated_limit = validate_limit(limit)
        query = self._client_provider.client.table(self._table).select("*").limit(
            validated_limit
        )
        if site:
            query = query.eq("site", site)
        if action:
            query = query.eq("action", action)
        if final_status:
            query = query.eq("final_status", final_status)
        if phase:
            query = query.eq("phase", phase)
        rows = self._client_provider.execute(query)
        return [ProcessLogRecord.model_validate(row) for row in rows]

    def update(self, log_id: int, changes: ProcessLogUpdate) -> ProcessLogRecord:
        validated_id = validate_positive_int(log_id, "log_id")
        payload = changes.model_dump(mode="json", exclude_none=True)
        if not payload:
            raise ValidationError("At least one field must be provided to update.")
        rows = self._client_provider.execute(
            self._client_provider.client.table(self._table)
            .update(payload)
            .eq("id", validated_id)
        )
        if rows:
            return self._single_row(rows, f"Process log '{validated_id}' was not found.")
        return self.get_by_id(validated_id)

    def mark_finished(
        self,
        log_id: int,
        *,
        final_status: str,
        page_message: str | None = None,
        error_message: str | None = None,
    ) -> ProcessLogRecord:
        return self.update(
            log_id,
            ProcessLogUpdate(
                final_status=final_status,
                page_message=page_message,
                error_message=error_message,
            ),
        )

    def list_recent(
        self,
        *,
        limit: int = 10,
        final_status: str | None = None,
    ) -> list[ProcessLogRecord]:
        validated_limit = validate_limit(limit, maximum=100)
        query = (
            self._client_provider.client.table(self._table)
            .select("*")
            .order("created_at", desc=True)
            .limit(validated_limit)
        )
        if final_status:
            query = query.eq("final_status", final_status)
        rows = self._client_provider.execute(query)
        return [ProcessLogRecord.model_validate(row) for row in rows]

    @staticmethod
    def _single_row(rows: list[dict], not_found_message: str) -> ProcessLogRecord:
        if not rows:
            raise EntityNotFoundError(not_found_message)
        return ProcessLogRecord.model_validate(rows[0])
