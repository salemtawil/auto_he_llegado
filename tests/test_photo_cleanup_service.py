from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from config.settings import Settings
from core.enums import PhotoStatus
from core.models import PhotoRecord
from services.photo_cleanup_service import PhotoCleanupService


def build_settings(tmp_path) -> Settings:
    return Settings(
        app_name="test-app",
        app_env="test",
        log_level="INFO",
        project_root=tmp_path,
        local_data_dir=tmp_path / "local_data",
        supabase_url="https://example.supabase.co",
        supabase_key="test-key",
        supabase_storage_bucket="photo-pool",
        supabase_photos_table="photos",
        supabase_process_logs_table="process_logs",
        supabase_photo_batches_table="photo_ingest_batches",
        supabase_photo_candidates_table="photo_candidates",
        supabase_profiles_table="profiles",
        supabase_timeout_seconds=30,
        admin_access_password="secret",
        weekly_min_approved_photos=20,
        video_frame_interval_seconds=0.0,
        video_max_candidate_frames=300,
        video_jpeg_quality=88,
        use_chrome_profile_extension=False,
        chrome_profile_dir=None,
        chrome_executable_path=None,
    )


def make_photo_record(
    *,
    photo_id: str,
    status: PhotoStatus,
    storage_path: str = "available/sample.jpg",
    cleanup_error: str | None = None,
    reserved_at: datetime | None = None,
    consumed_at: datetime | None = None,
) -> PhotoRecord:
    return PhotoRecord(
        id=photo_id,
        original_filename="sample.jpg",
        storage_path=storage_path,
        status=status,
        cleanup_error=cleanup_error,
        reserved_at=reserved_at,
        consumed_at=consumed_at,
    )


class StubClientProvider:
    def __init__(self, *, remove_error: Exception | None = None) -> None:
        self.remove_error = remove_error
        self.remove_calls: list[tuple[str, str]] = []
        self.remove_files_calls: list[tuple[str, tuple[str, ...]]] = []

    def remove_file(self, *, bucket_name: str, storage_path: str) -> None:
        self.remove_calls.append((bucket_name, storage_path))
        if self.remove_error is not None:
            raise self.remove_error

    def remove_files(self, *, bucket_name: str, storage_paths: list[str]) -> None:
        self.remove_files_calls.append((bucket_name, tuple(storage_paths)))
        if self.remove_error is not None:
            raise self.remove_error


class StubRpcClient:
    def __init__(self) -> None:
        self.calls = []

    def rpc(self, name, params):
        self.calls.append((name, params))
        return object()


class StubRpcClientProvider:
    def __init__(self, row: dict) -> None:
        self.client = StubRpcClient()
        self.row = row

    def execute_response_factory(self, operation_factory):
        operation_factory()
        return SimpleNamespace(data=[self.row])


class StubOrphanClientProvider(StubClientProvider):
    def __init__(self, rows: list[dict], *, remove_error: Exception | None = None) -> None:
        super().__init__(remove_error=remove_error)
        self.client = StubRpcClient()
        self.rows = rows

    def execute_response_factory(self, operation_factory):
        operation_factory()
        return SimpleNamespace(data=self.rows)


class StubSequenceClientProvider(StubClientProvider):
    def __init__(self, responses: list[list[dict]], *, remove_error: Exception | None = None) -> None:
        super().__init__(remove_error=remove_error)
        self.client = StubRpcClient()
        self.responses = list(responses)

    def execute_response_factory(self, operation_factory):
        operation_factory()
        if not self.responses:
            return SimpleNamespace(data=[])
        return SimpleNamespace(data=self.responses.pop(0))


class StubPhotosRepository:
    def __init__(
        self,
        *,
        consumed_records=None,
        stale_reserved_records=None,
        reconcile_records=None,
        mark_storage_cleaned_error: Exception | None = None,
    ) -> None:
        self.consumed_records = list(consumed_records or [])
        self.stale_reserved_records = list(stale_reserved_records or [])
        self.reconcile_records = list(reconcile_records or [])
        self.mark_storage_cleaned_error = mark_storage_cleaned_error
        self.mark_cleanup_error_calls: list[tuple[str, str]] = []
        self.mark_storage_cleaned_calls: list[tuple[str, str, str]] = []
        self.mark_storage_cleaned_many_calls: list[tuple[tuple[str, ...], str, str]] = []
        self.mark_stale_reserved_cleaned_calls: list[tuple[str, str, str]] = []
        self.mark_stale_reserved_cleaned_many_calls: list[tuple[tuple[str, ...], str, str]] = []
        self.list_consumed_pending_cleanup_calls: list[bool] = []
        self.list_stale_reserved_pending_cleanup_calls: list[tuple[int, bool]] = []
        self.list_reconcile_calls: list[int] = []
        self.count_reconcile_errors_calls = 0
        self.count_consumed_cleanable_calls = 0
        self.count_stale_reserved_cleanable_calls = 0

    def count_by_status(self, _status):
        return 0

    def count_consumed_pending_cleanup(self):
        return 0

    def count_consumed_cleanable_pending_cleanup(self):
        self.count_consumed_cleanable_calls += 1
        return 0

    def count_stale_reserved_pending_cleanup(self, *, older_than_hours: int):
        return 0

    def count_stale_reserved_cleanable_pending_cleanup(self, *, older_than_hours: int):
        self.count_stale_reserved_cleanable_calls += 1
        return 0

    def count_storage_cleaned(self, _status=None):
        return 0

    def count_cleanup_errors(self):
        return len(self.reconcile_records)

    def count_db_error_after_storage_delete(self):
        self.count_reconcile_errors_calls += 1
        return len(self.reconcile_records)

    def list_consumed_pending_cleanup(self, limit: int = 100, *, exclude_cleanup_errors: bool = False):
        self.list_consumed_pending_cleanup_calls.append(exclude_cleanup_errors)
        records = self.consumed_records
        if exclude_cleanup_errors:
            records = [record for record in records if record.cleanup_error is None]
        return records[:limit]

    def list_stale_reserved_pending_cleanup(
        self,
        *,
        older_than_hours: int,
        limit: int = 100,
        exclude_cleanup_errors: bool = False,
    ):
        self.list_stale_reserved_pending_cleanup_calls.append((older_than_hours, exclude_cleanup_errors))
        records = self.stale_reserved_records
        if exclude_cleanup_errors:
            records = [record for record in records if record.cleanup_error is None]
        return records[:limit]

    def list_db_error_after_storage_delete(self, *, limit: int = 100):
        self.list_reconcile_calls.append(limit)
        return self.reconcile_records[:limit]

    def mark_storage_cleaned(self, photo_id: str, *, reason: str, cleaned_by: str):
        self.mark_storage_cleaned_calls.append((photo_id, reason, cleaned_by))
        if self.mark_storage_cleaned_error is not None:
            raise self.mark_storage_cleaned_error
        return SimpleNamespace(id=photo_id)

    def mark_storage_cleaned_many(self, photo_ids, *, reason: str, cleaned_by: str):
        self.mark_storage_cleaned_many_calls.append((tuple(photo_ids), reason, cleaned_by))
        if self.mark_storage_cleaned_error is not None:
            raise self.mark_storage_cleaned_error
        return [SimpleNamespace(id=photo_id) for photo_id in photo_ids]

    def mark_stale_reserved_cleaned(self, photo_id: str, *, reason: str, cleaned_by: str):
        self.mark_stale_reserved_cleaned_calls.append((photo_id, reason, cleaned_by))
        if self.mark_storage_cleaned_error is not None:
            raise self.mark_storage_cleaned_error
        return SimpleNamespace(id=photo_id)

    def mark_stale_reserved_cleaned_many(self, photo_ids, *, reason: str, cleaned_by: str):
        self.mark_stale_reserved_cleaned_many_calls.append((tuple(photo_ids), reason, cleaned_by))
        if self.mark_storage_cleaned_error is not None:
            raise self.mark_storage_cleaned_error
        return [SimpleNamespace(id=photo_id) for photo_id in photo_ids]

    def mark_cleanup_error(self, photo_id: str, *, error: str):
        self.mark_cleanup_error_calls.append((photo_id, error))
        return SimpleNamespace(id=photo_id)


def test_cleanup_marks_recoverable_db_error_after_storage_delete(tmp_path) -> None:
    record = make_photo_record(
        photo_id="550e8400-e29b-41d4-a716-446655440000",
        status=PhotoStatus.CONSUMED,
        consumed_at=datetime.now(timezone.utc),
    )
    repository = StubPhotosRepository(
        consumed_records=[record],
        mark_storage_cleaned_error=RuntimeError("db write failed"),
    )
    service = PhotoCleanupService(
        photos_repository=repository,
        client_provider=StubClientProvider(),
        settings=build_settings(tmp_path),
    )

    result = service.cleanup_consumed_photos(limit=1)

    assert result.error_count == 1
    assert result.items[0]["result"] == "db_error_after_storage_delete"
    assert "Storage borrado, pero fallo update DB" in result.items[0]["message"]
    assert repository.mark_cleanup_error_calls == [
        (
            "550e8400-e29b-41d4-a716-446655440000",
            "Storage borrado, pero fallo update DB: db write failed",
        )
    ]


def test_audit_uses_rpc_when_available(tmp_path) -> None:
    client_provider = StubRpcClientProvider(
        {
            "available_count": 10,
            "reserved_count": 2,
            "consumed_count": 30,
            "discarded_count": 4,
            "consumed_pending_storage_cleanup": 5,
            "consumed_cleanable_pending_storage_cleanup": 3,
            "stale_reserved_pending_storage_cleanup": 2,
            "stale_reserved_cleanable_pending_storage_cleanup": 1,
            "storage_cleaned_count": 20,
            "consumed_storage_cleaned_count": 15,
            "stale_reserved_storage_cleaned_count": 5,
            "cleanup_error_count": 1,
            "db_error_after_storage_delete_count": 1,
        }
    )
    service = PhotoCleanupService(
        photos_repository=StubPhotosRepository(),
        client_provider=client_provider,
        settings=build_settings(tmp_path),
    )

    audit = service.audit(older_than_hours=3)

    assert audit.available_count == 10
    assert audit.consumed_cleanable_pending_storage_cleanup == 3
    assert audit.db_error_after_storage_delete_count == 1
    assert client_provider.client.calls == [
        ("photo_cleanup_audit", {"p_older_than_hours": 3})
    ]


def test_cleanup_consumed_photos_uses_bulk_storage_and_bulk_db(tmp_path) -> None:
    records = [
        make_photo_record(
            photo_id="550e8400-e29b-41d4-a716-446655440000",
            status=PhotoStatus.CONSUMED,
            storage_path="available/one.jpg",
            consumed_at=datetime.now(timezone.utc),
        ),
        make_photo_record(
            photo_id="550e8400-e29b-41d4-a716-446655440001",
            status=PhotoStatus.CONSUMED,
            storage_path="available/two.jpg",
            consumed_at=datetime.now(timezone.utc),
        ),
    ]
    repository = StubPhotosRepository(consumed_records=records)
    client_provider = StubClientProvider()
    service = PhotoCleanupService(
        photos_repository=repository,
        client_provider=client_provider,
        settings=build_settings(tmp_path),
    )

    result = service.cleanup_consumed_photos(limit=2)

    assert result.deleted_count == 2
    assert result.error_count == 0
    assert client_provider.remove_files_calls == [
        ("photo-pool", ("available/one.jpg", "available/two.jpg"))
    ]
    assert client_provider.remove_calls == []
    assert repository.mark_storage_cleaned_many_calls == [
        (
            (
                "550e8400-e29b-41d4-a716-446655440000",
                "550e8400-e29b-41d4-a716-446655440001",
            ),
            "consumed_cleanup",
            "admin_cleanup",
        )
    ]
    assert repository.mark_storage_cleaned_calls == []


def test_cleanup_available_orphan_storage_removes_paths_by_bucket(tmp_path) -> None:
    client_provider = StubOrphanClientProvider(
        [
            {
                "bucket_name": "photo-pool",
                "storage_path": "available/orphan-1.jpg",
                "total_bytes": 100,
            },
            {
                "bucket_name": "photo-pool",
                "storage_path": "available/orphan-2.jpg",
                "total_bytes": 200,
            },
            {
                "bucket_name": "photos",
                "storage_path": "available/old-orphan.jpg",
                "total_bytes": 300,
            },
        ]
    )
    service = PhotoCleanupService(
        photos_repository=StubPhotosRepository(),
        client_provider=client_provider,
        settings=build_settings(tmp_path),
    )

    result = service.cleanup_available_orphan_storage(limit=1000)

    assert client_provider.client.calls == [
        ("available_storage_orphan_paths", {"p_limit": 1000})
    ]
    assert result.action == "cleanup_available_orphan_storage"
    assert result.matched_count == 3
    assert result.deleted_count == 3
    assert result.error_count == 0
    assert client_provider.remove_files_calls == [
        ("photo-pool", ("available/orphan-1.jpg", "available/orphan-2.jpg")),
        ("photos", ("available/old-orphan.jpg",)),
    ]
    assert [item["result"] for item in result.items] == ["cleaned", "cleaned", "cleaned"]


def test_cleanup_all_available_orphan_storage_runs_batches_with_progress(tmp_path) -> None:
    client_provider = StubSequenceClientProvider(
        [
            [{"bucket_name": "photo-pool", "object_count": 3, "total_bytes": 300}],
            [
                {
                    "bucket_name": "photo-pool",
                    "storage_path": "available/orphan-1.jpg",
                    "total_bytes": 100,
                },
                {
                    "bucket_name": "photo-pool",
                    "storage_path": "available/orphan-2.jpg",
                    "total_bytes": 100,
                },
            ],
            [
                {
                    "bucket_name": "photo-pool",
                    "storage_path": "available/orphan-3.jpg",
                    "total_bytes": 100,
                },
            ],
        ]
    )
    progress_events = []
    service = PhotoCleanupService(
        photos_repository=StubPhotosRepository(),
        client_provider=client_provider,
        settings=build_settings(tmp_path),
    )

    result = service.cleanup_all_available_orphan_storage(
        batch_size=2,
        progress_callback=progress_events.append,
    )

    assert result.action == "cleanup_all_available_orphan_storage"
    assert result.matched_count == 3
    assert result.deleted_count == 3
    assert result.error_count == 0
    assert client_provider.client.calls == [
        ("available_storage_orphan_audit", {}),
        ("available_storage_orphan_paths", {"p_limit": 2}),
        ("available_storage_orphan_paths", {"p_limit": 2}),
    ]
    assert client_provider.remove_files_calls == [
        ("photo-pool", ("available/orphan-1.jpg", "available/orphan-2.jpg")),
        ("photo-pool", ("available/orphan-3.jpg",)),
    ]
    assert progress_events[-1].kind == "available_orphans"
    assert progress_events[-1].is_complete is True
    assert progress_events[-1].pending_current == 0


def test_discard_missing_available_photos_marks_db_rows_without_storage(tmp_path) -> None:
    client_provider = StubSequenceClientProvider(
        [
            [
                {
                    "photo_id": "550e8400-e29b-41d4-a716-446655440000",
                    "storage_bucket": "photo-pool",
                    "file_path": "available/missing.jpg",
                }
            ]
        ]
    )
    service = PhotoCleanupService(
        photos_repository=StubPhotosRepository(),
        client_provider=client_provider,
        settings=build_settings(tmp_path),
    )

    result = service.discard_missing_available_photos(limit=1000)

    assert result.action == "discard_missing_available_photos"
    assert result.matched_count == 1
    assert result.deleted_count == 1
    assert result.items[0]["result"] == "discarded"
    assert client_provider.client.calls == [
        (
            "discard_missing_available_photos",
            {
                "p_active_bucket": "photo-pool",
                "p_limit": 1000,
                "p_reason": "missing_storage_integrity_cleanup",
                "p_cleaned_by": "admin_cleanup",
            },
        )
    ]
    assert client_provider.remove_files_calls == []


def test_discard_all_missing_available_photos_runs_batches_with_progress(tmp_path) -> None:
    client_provider = StubSequenceClientProvider(
        [
            [{"missing_count": 2}],
            [
                {
                    "photo_id": "550e8400-e29b-41d4-a716-446655440000",
                    "storage_bucket": "photo-pool",
                    "file_path": "available/missing-1.jpg",
                }
            ],
            [
                {
                    "photo_id": "550e8400-e29b-41d4-a716-446655440001",
                    "storage_bucket": "photo-pool",
                    "file_path": "available/missing-2.jpg",
                }
            ],
        ]
    )
    progress_events = []
    service = PhotoCleanupService(
        photos_repository=StubPhotosRepository(),
        client_provider=client_provider,
        settings=build_settings(tmp_path),
    )

    result = service.discard_all_missing_available_photos(
        batch_size=1,
        progress_callback=progress_events.append,
    )

    assert result.action == "discard_all_missing_available_photos"
    assert result.matched_count == 2
    assert result.deleted_count == 2
    assert client_provider.client.calls == [
        ("missing_available_photo_audit", {"p_active_bucket": "photo-pool"}),
        (
            "discard_missing_available_photos",
            {
                "p_active_bucket": "photo-pool",
                "p_limit": 1,
                "p_reason": "missing_storage_integrity_cleanup",
                "p_cleaned_by": "admin_cleanup",
            },
        ),
        (
            "discard_missing_available_photos",
            {
                "p_active_bucket": "photo-pool",
                "p_limit": 1,
                "p_reason": "missing_storage_integrity_cleanup",
                "p_cleaned_by": "admin_cleanup",
            },
        ),
    ]
    assert progress_events[-1].kind == "missing_available"
    assert progress_events[-1].is_complete is True


def test_reconcile_db_error_after_storage_delete_marks_consumed_photo_as_cleaned(tmp_path) -> None:
    record = make_photo_record(
        photo_id="550e8400-e29b-41d4-a716-446655440000",
        status=PhotoStatus.CONSUMED,
        cleanup_error="Storage borrado, pero fallo update DB: db write failed",
        consumed_at=datetime.now(timezone.utc),
    )
    repository = StubPhotosRepository(reconcile_records=[record])
    client_provider = StubClientProvider(remove_error=RuntimeError("Object not found"))
    service = PhotoCleanupService(
        photos_repository=repository,
        client_provider=client_provider,
        settings=build_settings(tmp_path),
    )

    result = service.reconcile_db_error_after_storage_delete(limit=1)

    assert result.matched_count == 1
    assert result.processed_count == 1
    assert result.reconciled_count == 1
    assert result.failed_count == 0
    assert result.skipped_count == 0
    assert result.deleted_count == 1
    assert result.error_count == 0
    assert result.remaining_count == 0
    assert result.stop_reason == "completed"
    assert result.recent_errors == []
    assert result.last_error is None
    assert result.items[0]["result"] == "reconciled"
    assert repository.mark_storage_cleaned_calls == [
        (
            "550e8400-e29b-41d4-a716-446655440000",
            "consumed_cleanup",
            "admin_cleanup",
        )
    ]
    assert client_provider.remove_calls == [("photo-pool", "available/sample.jpg")]


def test_reconcile_db_error_after_storage_delete_marks_stale_reserved_photo_as_discarded(tmp_path) -> None:
    record = make_photo_record(
        photo_id="550e8400-e29b-41d4-a716-446655440001",
        status=PhotoStatus.RESERVED,
        cleanup_error="Storage borrado, pero fallo update DB: db write failed",
        reserved_at=datetime.now(timezone.utc) - timedelta(hours=5),
    )
    repository = StubPhotosRepository(reconcile_records=[record])
    service = PhotoCleanupService(
        photos_repository=repository,
        client_provider=StubClientProvider(remove_error=RuntimeError("404 missing object")),
        settings=build_settings(tmp_path),
    )

    result = service.reconcile_db_error_after_storage_delete(limit=1)

    assert result.deleted_count == 1
    assert result.reconciled_count == 1
    assert repository.mark_stale_reserved_cleaned_calls == [
        (
            "550e8400-e29b-41d4-a716-446655440001",
            "stale_reserved_cleanup",
            "admin_cleanup",
        )
    ]


def test_explicit_reconciliation_is_not_blocked_by_exclude_cleanup_errors(tmp_path) -> None:
    record = make_photo_record(
        photo_id="550e8400-e29b-41d4-a716-446655440002",
        status=PhotoStatus.CONSUMED,
        cleanup_error="Storage borrado, pero fallo update DB: db write failed",
        consumed_at=datetime.now(timezone.utc),
    )
    repository = StubPhotosRepository(
        consumed_records=[record],
        reconcile_records=[record],
    )
    service = PhotoCleanupService(
        photos_repository=repository,
        client_provider=StubClientProvider(remove_error=RuntimeError("Object not found")),
        settings=build_settings(tmp_path),
    )

    batch_result = service.cleanup_consumed_photos(limit=1, exclude_cleanup_errors=True)
    reconcile_result = service.reconcile_db_error_after_storage_delete(limit=1)

    assert batch_result.matched_count == 0
    assert repository.list_consumed_pending_cleanup_calls == [True]
    assert reconcile_result.deleted_count == 1
    assert repository.list_reconcile_calls == [1]


def test_count_db_error_after_storage_delete_returns_repository_count(tmp_path) -> None:
    record = make_photo_record(
        photo_id="550e8400-e29b-41d4-a716-446655440010",
        status=PhotoStatus.CONSUMED,
        cleanup_error="Storage borrado, pero fallo update DB: db write failed",
        consumed_at=datetime.now(timezone.utc),
    )
    repository = StubPhotosRepository(reconcile_records=[record])
    service = PhotoCleanupService(
        photos_repository=repository,
        client_provider=StubClientProvider(),
        settings=build_settings(tmp_path),
    )

    count = service.count_db_error_after_storage_delete()

    assert count == 1
    assert repository.count_reconcile_errors_calls == 1


def test_reconcile_db_error_after_storage_delete_returns_complete_counters(tmp_path) -> None:
    consumed = make_photo_record(
        photo_id="550e8400-e29b-41d4-a716-446655440011",
        status=PhotoStatus.CONSUMED,
        cleanup_error="Storage borrado, pero fallo update DB: db write failed",
        consumed_at=datetime.now(timezone.utc),
    )
    missing_path = make_photo_record(
        photo_id="550e8400-e29b-41d4-a716-446655440012",
        status=PhotoStatus.CONSUMED,
        storage_path="available/missing.jpg",
        cleanup_error="Storage borrado, pero fallo update DB: db write failed",
        consumed_at=datetime.now(timezone.utc),
    ).model_copy(update={"storage_path": ""})
    unsupported_status = make_photo_record(
        photo_id="550e8400-e29b-41d4-a716-446655440013",
        status=PhotoStatus.AVAILABLE,
        cleanup_error="Storage borrado, pero fallo update DB: db write failed",
    )
    repository = StubPhotosRepository(reconcile_records=[consumed, missing_path, unsupported_status])
    service = PhotoCleanupService(
        photos_repository=repository,
        client_provider=StubClientProvider(remove_error=RuntimeError("Object not found")),
        settings=build_settings(tmp_path),
    )

    result = service.reconcile_db_error_after_storage_delete(limit=3)

    assert result.matched_count == 3
    assert result.processed_count == 3
    assert result.reconciled_count == 1
    assert result.failed_count == 0
    assert result.skipped_count == 2
    assert result.remaining_count == 2
    assert result.stop_reason == "limit_reached"
    assert result.last_error is None
    assert result.recent_errors == []


def test_reconcile_db_error_after_storage_delete_reports_remaining_and_recent_errors(tmp_path) -> None:
    consumed = make_photo_record(
        photo_id="550e8400-e29b-41d4-a716-446655440014",
        status=PhotoStatus.CONSUMED,
        cleanup_error="Storage borrado, pero fallo update DB: db write failed",
        consumed_at=datetime.now(timezone.utc),
    )
    repository = StubPhotosRepository(
        reconcile_records=[consumed],
        mark_storage_cleaned_error=RuntimeError("db write failed again"),
    )
    service = PhotoCleanupService(
        photos_repository=repository,
        client_provider=StubClientProvider(remove_error=RuntimeError("Object not found")),
        settings=build_settings(tmp_path),
    )

    result = service.reconcile_db_error_after_storage_delete(limit=1)

    assert result.processed_count == 1
    assert result.reconciled_count == 0
    assert result.failed_count == 1
    assert result.skipped_count == 0
    assert result.remaining_count == 1
    assert result.stop_reason == "has_failures"
    assert result.last_error == "Storage borrado, pero fallo update DB: db write failed again"
    assert result.recent_errors == ["Storage borrado, pero fallo update DB: db write failed again"]
