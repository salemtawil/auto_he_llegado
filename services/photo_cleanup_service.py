from __future__ import annotations

from time import monotonic

from config.settings import Settings, get_settings
from core.enums import PhotoStatus
from core.models import PhotoCleanupAudit, PhotoCleanupBatchProgress, PhotoCleanupResult, PhotoRecord
from storage.photos_repository import PhotosRepository
from storage.supabase_client import SupabaseClientProvider


class PhotoCleanupService:
    _CLEANED_BY = "admin_cleanup"
    _CONSUMED_REASON = "consumed_cleanup"
    _STALE_RESERVED_REASON = "stale_reserved_cleanup"
    _DB_ERROR_AFTER_STORAGE_DELETE_PREFIX = "Storage borrado, pero fallo update DB:"
    _RECENT_ERROR_LIMIT = 5

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

    def audit(self, older_than_hours: int = 2) -> PhotoCleanupAudit:
        normalized_hours = max(int(older_than_hours), 1)
        rpc_audit = self._audit_from_rpc(normalized_hours)
        if rpc_audit is not None:
            return rpc_audit
        return PhotoCleanupAudit(
            available_count=self._photos_repository.count_by_status(PhotoStatus.AVAILABLE),
            reserved_count=self._photos_repository.count_by_status(PhotoStatus.RESERVED),
            consumed_count=self._photos_repository.count_by_status(PhotoStatus.CONSUMED),
            discarded_count=self._photos_repository.count_by_status(PhotoStatus.DISCARDED),
            consumed_pending_storage_cleanup=self._photos_repository.count_consumed_pending_cleanup(),
            consumed_cleanable_pending_storage_cleanup=self._photos_repository.count_consumed_cleanable_pending_cleanup(),
            stale_reserved_pending_storage_cleanup=self._photos_repository.count_stale_reserved_pending_cleanup(
                older_than_hours=normalized_hours
            ),
            stale_reserved_cleanable_pending_storage_cleanup=self._photos_repository.count_stale_reserved_cleanable_pending_cleanup(
                older_than_hours=normalized_hours
            ),
            storage_cleaned_count=self._photos_repository.count_storage_cleaned(),
            consumed_storage_cleaned_count=self._photos_repository.count_storage_cleaned(PhotoStatus.CONSUMED),
            stale_reserved_storage_cleaned_count=self._photos_repository.count_storage_cleaned(PhotoStatus.DISCARDED),
            cleanup_error_count=self._photos_repository.count_cleanup_errors(),
            db_error_after_storage_delete_count=self._photos_repository.count_db_error_after_storage_delete(),
            older_than_hours=normalized_hours,
        )

    def _audit_from_rpc(self, older_than_hours: int) -> PhotoCleanupAudit | None:
        try:
            response = self._client_provider.execute_response_factory(
                lambda: self._client_provider.client.rpc(
                    "photo_cleanup_audit",
                    {"p_older_than_hours": older_than_hours},
                )
            )
        except Exception:
            return None
        rows = list(getattr(response, "data", []) or [])
        if not rows:
            return None
        row = dict(rows[0])
        return PhotoCleanupAudit(
            available_count=int(row.get("available_count") or 0),
            reserved_count=int(row.get("reserved_count") or 0),
            consumed_count=int(row.get("consumed_count") or 0),
            discarded_count=int(row.get("discarded_count") or 0),
            consumed_pending_storage_cleanup=int(row.get("consumed_pending_storage_cleanup") or 0),
            consumed_cleanable_pending_storage_cleanup=int(row.get("consumed_cleanable_pending_storage_cleanup") or 0),
            stale_reserved_pending_storage_cleanup=int(row.get("stale_reserved_pending_storage_cleanup") or 0),
            stale_reserved_cleanable_pending_storage_cleanup=int(row.get("stale_reserved_cleanable_pending_storage_cleanup") or 0),
            storage_cleaned_count=int(row.get("storage_cleaned_count") or 0),
            consumed_storage_cleaned_count=int(row.get("consumed_storage_cleaned_count") or 0),
            stale_reserved_storage_cleaned_count=int(row.get("stale_reserved_storage_cleaned_count") or 0),
            cleanup_error_count=int(row.get("cleanup_error_count") or 0),
            db_error_after_storage_delete_count=int(row.get("db_error_after_storage_delete_count") or 0),
            older_than_hours=older_than_hours,
        )

    def count_db_error_after_storage_delete(self) -> int:
        return self._photos_repository.count_db_error_after_storage_delete()

    def cleanup_consumed_photos(
        self,
        limit: int = 100,
        dry_run: bool = False,
        exclude_cleanup_errors: bool = False,
    ) -> PhotoCleanupResult:
        records = self._photos_repository.list_consumed_pending_cleanup(
            limit=limit,
            exclude_cleanup_errors=exclude_cleanup_errors,
        )
        return self._cleanup_records(
            action="cleanup_consumed_photos",
            records=records,
            dry_run=dry_run,
            limit=limit,
            reason=self._CONSUMED_REASON,
            bulk_success=lambda cleanable_records: self._photos_repository.mark_storage_cleaned_many(
                [record.id for record in cleanable_records],
                reason=self._CONSUMED_REASON,
                cleaned_by=self._CLEANED_BY,
            ),
            on_success=lambda record: self._photos_repository.mark_storage_cleaned(
                record.id,
                reason=self._CONSUMED_REASON,
                cleaned_by=self._CLEANED_BY,
            ),
            on_db_error=lambda record, error: self._mark_db_error(record, error),
        )

    def cleanup_stale_reserved_photos(
        self,
        older_than_hours: int = 2,
        limit: int = 100,
        dry_run: bool = False,
        exclude_cleanup_errors: bool = False,
    ) -> PhotoCleanupResult:
        normalized_hours = max(int(older_than_hours), 1)
        records = self._photos_repository.list_stale_reserved_pending_cleanup(
            older_than_hours=normalized_hours,
            limit=limit,
            exclude_cleanup_errors=exclude_cleanup_errors,
        )
        return self._cleanup_records(
            action="cleanup_stale_reserved_photos",
            records=records,
            dry_run=dry_run,
            limit=limit,
            older_than_hours=normalized_hours,
            reason=self._STALE_RESERVED_REASON,
            bulk_success=lambda cleanable_records: self._photos_repository.mark_stale_reserved_cleaned_many(
                [record.id for record in cleanable_records],
                reason=self._STALE_RESERVED_REASON,
                cleaned_by=self._CLEANED_BY,
            ),
            on_success=lambda record: self._photos_repository.mark_stale_reserved_cleaned(
                record.id,
                reason=self._STALE_RESERVED_REASON,
                cleaned_by=self._CLEANED_BY,
            ),
            on_db_error=lambda record, error: self._mark_db_error(record, error),
        )

    def cleanup_all_consumed_photos(
        self,
        *,
        batch_size: int = 100,
        progress_callback=None,
        cancel_callback=None,
        max_consecutive_stalled_batches: int = 3,
    ) -> PhotoCleanupResult:
        return self._cleanup_in_batches(
            kind="consumed",
            batch_size=batch_size,
            progress_callback=progress_callback,
            cancel_callback=cancel_callback,
            max_consecutive_stalled_batches=max_consecutive_stalled_batches,
        )

    def cleanup_all_stale_reserved_photos(
        self,
        *,
        older_than_hours: int = 2,
        batch_size: int = 100,
        progress_callback=None,
        cancel_callback=None,
        max_consecutive_stalled_batches: int = 3,
    ) -> PhotoCleanupResult:
        return self._cleanup_in_batches(
            kind="stale_reserved",
            older_than_hours=max(int(older_than_hours), 1),
            batch_size=batch_size,
            progress_callback=progress_callback,
            cancel_callback=cancel_callback,
            max_consecutive_stalled_batches=max_consecutive_stalled_batches,
        )

    def reconcile_db_error_after_storage_delete(
        self,
        *,
        limit: int = 100,
    ) -> PhotoCleanupResult:
        normalized_limit = max(int(limit), 1)
        records = self._photos_repository.list_db_error_after_storage_delete(limit=normalized_limit)
        total_pending = self._photos_repository.count_db_error_after_storage_delete()
        result = PhotoCleanupResult(
            action="reconcile_db_error_after_storage_delete",
            limit=normalized_limit,
            dry_run=False,
            matched_count=len(records),
            remaining_count=max(total_pending - len(records), 0),
        )
        for record in records:
            result.processed_count += 1
            normalized_path = self._normalize_storage_path(record.storage_path)
            item = {
                "photo_id": record.id,
                "status": record.status,
                "file_path": normalized_path,
                "cleanup_error": record.cleanup_error,
            }
            if not normalized_path:
                result.skipped_count += 1
                item["result"] = "skipped"
                item["message"] = "La foto no tiene file_path utilizable."
                result.items.append(item)
                continue
            if record.status not in {PhotoStatus.CONSUMED, PhotoStatus.RESERVED}:
                result.skipped_count += 1
                item["result"] = "skipped"
                item["message"] = "Estado no soportado para reconciliacion."
                result.items.append(item)
                continue
            try:
                self._client_provider.remove_file(
                    bucket_name=self._settings.supabase_storage_bucket,
                    storage_path=normalized_path,
                )
            except Exception as exc:
                if not self._is_storage_missing_error(str(exc)):
                    message = f"Reconciliacion pendiente: fallo storage: {exc}"
                    self._append_reconcile_error(result, message)
                    item["result"] = "storage_error"
                    item["message"] = message
                    result.items.append(item)
                    self._mark_cleanup_error_safe(record.id, message)
                    continue
            try:
                self._mark_reconciled_record(record)
            except Exception as exc:
                message = f"{self._DB_ERROR_AFTER_STORAGE_DELETE_PREFIX} {exc}"
                self._append_reconcile_error(result, message)
                item["result"] = "db_error_after_storage_delete"
                item["message"] = message
                result.items.append(item)
                self._mark_cleanup_error_safe(record.id, message)
                continue
            result.deleted_count += 1
            result.reconciled_count += 1
            item["result"] = "reconciled"
            item["message"] = "Storage ya estaba eliminado o se confirmo su borrado; DB reconciliada."
            result.items.append(item)
        result.remaining_count = max(
            self._photos_repository.count_db_error_after_storage_delete() - result.reconciled_count,
            0,
        )
        if result.failed_count > 0:
            result.stop_reason = "has_failures"
        elif result.remaining_count > 0 and result.processed_count >= result.limit:
            result.stop_reason = "limit_reached"
        else:
            result.stop_reason = "completed"
        return result

    def _cleanup_records(
        self,
        *,
        action: str,
        records: list[PhotoRecord],
        dry_run: bool,
        limit: int,
        reason: str,
        bulk_success,
        on_success,
        on_db_error,
        older_than_hours: int | None = None,
    ) -> PhotoCleanupResult:
        result = PhotoCleanupResult(
            action=action,
            older_than_hours=older_than_hours,
            limit=max(int(limit), 1),
            dry_run=dry_run,
            matched_count=len(records),
        )
        prepared_items: list[tuple[PhotoRecord, dict, str]] = []
        for record in records:
            normalized_path = self._normalize_storage_path(record.storage_path)
            item = {
                "photo_id": record.id,
                "status": record.status,
                "file_path": normalized_path,
                "reserved_at": record.reserved_at.isoformat() if record.reserved_at else None,
                "consumed_at": record.consumed_at.isoformat() if record.consumed_at else None,
                "cleanup_reason": reason,
            }
            if not normalized_path:
                result.skipped_count += 1
                item["result"] = "skipped"
                item["message"] = "La foto no tiene file_path utilizable."
                result.items.append(item)
                continue
            if dry_run:
                result.skipped_count += 1
                item["result"] = "dry_run"
                item["message"] = "Dry-run: no se borro Storage ni se actualizo DB."
                result.items.append(item)
                continue
            prepared_items.append((record, item, normalized_path))
        if not prepared_items:
            return result

        if self._cleanup_records_bulk(result, prepared_items, reason=reason, bulk_success=bulk_success):
            return result

        for record, item, normalized_path in prepared_items:
            try:
                self._client_provider.remove_file(
                    bucket_name=self._settings.supabase_storage_bucket,
                    storage_path=normalized_path,
                )
            except Exception as exc:
                message = str(exc)
                result.error_count += 1
                item["result"] = "storage_error"
                item["message"] = message
                result.items.append(item)
                self._mark_cleanup_error_safe(record.id, message)
                continue
            try:
                on_success(record)
            except Exception as exc:
                message = f"Storage borrado, pero fallo update DB: {exc}"
                result.error_count += 1
                item["result"] = "db_error_after_storage_delete"
                item["message"] = message
                result.items.append(item)
                on_db_error(record, message)
                continue
            result.deleted_count += 1
            item["result"] = "cleaned"
            item["message"] = "Archivo eliminado de Storage y DB actualizada."
            result.items.append(item)
        return result

    def _cleanup_records_bulk(
        self,
        result: PhotoCleanupResult,
        prepared_items: list[tuple[PhotoRecord, dict, str]],
        *,
        reason: str,
        bulk_success,
    ) -> bool:
        remove_files = getattr(self._client_provider, "remove_files", None)
        if not callable(remove_files):
            return False
        try:
            remove_files(
                bucket_name=self._settings.supabase_storage_bucket,
                storage_paths=[storage_path for _record, _item, storage_path in prepared_items],
            )
        except Exception:
            return False
        try:
            bulk_success([record for record, _item, _path in prepared_items])
        except Exception as exc:
            message = f"{self._DB_ERROR_AFTER_STORAGE_DELETE_PREFIX} bulk update: {exc}"
            for record, item, _path in prepared_items:
                result.error_count += 1
                item["result"] = "db_error_after_storage_delete"
                item["message"] = message
                result.items.append(item)
                self._mark_cleanup_error_safe(record.id, f"{self._DB_ERROR_AFTER_STORAGE_DELETE_PREFIX} {exc}")
            return True
        for record, item, _path in prepared_items:
            result.deleted_count += 1
            item["result"] = "cleaned"
            item["message"] = f"Archivo eliminado de Storage en lote y DB actualizada. Motivo: {reason}."
            result.items.append(item)
        return True

    def _cleanup_in_batches(
        self,
        *,
        kind: str,
        batch_size: int,
        progress_callback=None,
        cancel_callback=None,
        older_than_hours: int = 2,
        max_consecutive_stalled_batches: int = 3,
    ) -> PhotoCleanupResult:
        normalized_batch_size = max(int(batch_size), 1)
        total_initial = self._pending_cleanable_count_for_kind(kind, older_than_hours=older_than_hours)
        result = PhotoCleanupResult(
            action=f"cleanup_all_{kind}_photos",
            older_than_hours=older_than_hours if kind == "stale_reserved" else None,
            limit=normalized_batch_size,
            dry_run=False,
            matched_count=total_initial,
        )
        if total_initial <= 0:
            self._emit_batch_progress(
                progress_callback,
                kind=kind,
                batch_size=normalized_batch_size,
                total_initial=0,
                pending_current=0,
                result=result,
                batch_index=0,
                stop_reason="nothing_pending",
                is_complete=True,
            )
            return result

        started_at = monotonic()
        batch_index = 0
        consecutive_stalled_batches = 0

        while True:
            if callable(cancel_callback) and cancel_callback():
                self._emit_batch_progress(
                    progress_callback,
                    kind=kind,
                    batch_size=normalized_batch_size,
                    total_initial=total_initial,
                    pending_current=max(
                        total_initial - result.deleted_count - result.error_count - result.skipped_count,
                        0,
                    ),
                    result=result,
                    batch_index=batch_index,
                    stop_reason="cancelled_by_user",
                    is_cancelled=True,
                )
                return result

            batch_index += 1
            batch_result = self._run_single_batch(kind=kind, batch_size=normalized_batch_size, older_than_hours=older_than_hours)
            result.deleted_count += batch_result.deleted_count
            result.error_count += batch_result.error_count
            result.skipped_count += batch_result.skipped_count
            result.items.extend(batch_result.items)

            pending_current = max(
                total_initial - result.deleted_count - result.error_count - result.skipped_count,
                0,
            )

            stalled = batch_result.deleted_count <= 0
            consecutive_stalled_batches = consecutive_stalled_batches + 1 if stalled else 0

            stop_reason: str | None = None
            is_complete = False
            if pending_current <= 0 or batch_result.matched_count <= 0:
                stop_reason = "pending_zero"
                is_complete = True
            elif callable(cancel_callback) and cancel_callback():
                stop_reason = "cancelled_by_user"
            elif consecutive_stalled_batches >= max(max_consecutive_stalled_batches, 1):
                stop_reason = "stalled_batches"
            if stop_reason is not None:
                self._emit_batch_progress(
                    progress_callback,
                    kind=kind,
                    batch_size=normalized_batch_size,
                    total_initial=total_initial,
                    pending_current=max(pending_current, 0),
                    result=result,
                    batch_index=batch_index,
                    last_batch=batch_result,
                    stop_reason=stop_reason,
                    is_complete=is_complete,
                    is_cancelled=(stop_reason == "cancelled_by_user"),
                    started_at=started_at,
                )
                return result

            self._emit_batch_progress(
                progress_callback,
                kind=kind,
                batch_size=normalized_batch_size,
                total_initial=total_initial,
                pending_current=max(pending_current, 0),
                result=result,
                batch_index=batch_index,
                last_batch=batch_result,
                started_at=started_at,
            )

    def _run_single_batch(self, *, kind: str, batch_size: int, older_than_hours: int) -> PhotoCleanupResult:
        if kind == "consumed":
            return self.cleanup_consumed_photos(
                limit=batch_size,
                dry_run=False,
                exclude_cleanup_errors=True,
            )
        return self.cleanup_stale_reserved_photos(
            older_than_hours=older_than_hours,
            limit=batch_size,
            dry_run=False,
            exclude_cleanup_errors=True,
        )

    def _pending_cleanable_count(self, audit: PhotoCleanupAudit, kind: str) -> int:
        if kind == "consumed":
            return int(audit.consumed_cleanable_pending_storage_cleanup)
        return int(audit.stale_reserved_cleanable_pending_storage_cleanup)

    def _pending_cleanable_count_for_kind(self, kind: str, *, older_than_hours: int) -> int:
        if kind == "consumed":
            return self._photos_repository.count_consumed_cleanable_pending_cleanup()
        return self._photos_repository.count_stale_reserved_cleanable_pending_cleanup(
            older_than_hours=older_than_hours
        )

    def _emit_batch_progress(
        self,
        progress_callback,
        *,
        kind: str,
        batch_size: int,
        total_initial: int,
        pending_current: int,
        result: PhotoCleanupResult,
        batch_index: int,
        last_batch: PhotoCleanupResult | None = None,
        stop_reason: str | None = None,
        is_complete: bool = False,
        is_cancelled: bool = False,
        started_at: float | None = None,
    ) -> None:
        if progress_callback is None:
            return
        processed_count = max(total_initial - max(pending_current, 0), result.deleted_count + result.error_count + result.skipped_count)
        elapsed_seconds = 0.0 if started_at is None else max(monotonic() - started_at, 0.0)
        photos_per_minute = 0.0 if elapsed_seconds <= 0 else round((processed_count / elapsed_seconds) * 60.0, 1)
        progress_callback(
            PhotoCleanupBatchProgress(
                kind=kind,
                batch_size=batch_size,
                total_initial=total_initial,
                pending_current=max(pending_current, 0),
                processed_count=processed_count,
                deleted_count=result.deleted_count,
                error_count=result.error_count,
                skipped_count=result.skipped_count,
                batch_index=batch_index,
                last_batch_matched=0 if last_batch is None else last_batch.matched_count,
                last_batch_deleted=0 if last_batch is None else last_batch.deleted_count,
                last_batch_errors=0 if last_batch is None else last_batch.error_count,
                last_batch_skipped=0 if last_batch is None else last_batch.skipped_count,
                is_complete=is_complete,
                is_cancelled=is_cancelled,
                stop_reason=stop_reason,
                elapsed_seconds=round(elapsed_seconds, 1),
                photos_per_minute=photos_per_minute,
            )
        )

    def _mark_db_error(self, record: PhotoRecord, error: str) -> None:
        self._photos_repository.mark_cleanup_error(record.id, error=error)

    def _mark_reconciled_record(self, record: PhotoRecord) -> None:
        if record.status == PhotoStatus.CONSUMED:
            self._photos_repository.mark_storage_cleaned(
                record.id,
                reason=self._CONSUMED_REASON,
                cleaned_by=self._CLEANED_BY,
            )
            return
        self._photos_repository.mark_stale_reserved_cleaned(
            record.id,
            reason=self._STALE_RESERVED_REASON,
            cleaned_by=self._CLEANED_BY,
        )

    def _mark_cleanup_error_safe(self, photo_id: str, error: str) -> None:
        try:
            self._photos_repository.mark_cleanup_error(photo_id, error=error)
        except Exception:
            return

    def _append_reconcile_error(self, result: PhotoCleanupResult, message: str) -> None:
        result.error_count += 1
        result.failed_count += 1
        result.last_error = message
        result.recent_errors.append(message)
        if len(result.recent_errors) > self._RECENT_ERROR_LIMIT:
            result.recent_errors = result.recent_errors[-self._RECENT_ERROR_LIMIT :]

    @staticmethod
    def _is_storage_missing_error(message: str) -> bool:
        normalized = str(message or "").strip().lower()
        return any(
            token in normalized
            for token in (
                "not found",
                "404",
                "no such object",
                "missing object",
                "does not exist",
            )
        )

    @staticmethod
    def _normalize_storage_path(storage_path: str | None) -> str:
        return str(storage_path or "").strip().replace("\\", "/").lstrip("/")
