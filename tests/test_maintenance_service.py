from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import os

from config.settings import Settings
from core.enums import PhotoStatus
from services.maintenance_service import MaintenanceService


class StubPhotoRecord:
    def __init__(
        self,
        *,
        photo_id: str,
        status: PhotoStatus,
        storage_path: str,
        reserved_at: datetime | None = None,
        consumed_at: datetime | None = None,
    ) -> None:
        self.id = photo_id
        self.status = status
        self.storage_path = storage_path
        self.original_filename = Path(storage_path).name
        self.reserved_at = reserved_at
        self.consumed_at = consumed_at
        self.created_at = None


class StubPhotosRepository:
    def __init__(self, records: list[StubPhotoRecord]) -> None:
        self.records = records

    def count_by_status(self, status: PhotoStatus) -> int:
        return sum(1 for record in self.records if record.status == status)

    def list(self, *, status: PhotoStatus | None = None, limit: int = 100) -> list[StubPhotoRecord]:
        rows = [record for record in self.records if status is None or record.status == status]
        return rows[:limit]

    def update(self, photo_id: str, changes) -> StubPhotoRecord:
        for record in self.records:
            if record.id != photo_id:
                continue
            if changes.status is not None:
                record.status = changes.status
            if getattr(changes, "storage_path", None):
                record.storage_path = changes.storage_path.replace("\\", "/")
            return record
        raise AssertionError(f"unexpected photo id {photo_id}")


class StubClientProvider:
    def __init__(self) -> None:
        self.moves: list[tuple[str, str, str]] = []

    def move_file(self, *, bucket_name: str, from_path: str, to_path: str) -> None:
        self.moves.append((bucket_name, from_path, to_path))

    def list_files(self, *, bucket_name: str, folder_path: str = "", limit: int = 1000, offset: int = 0) -> list[dict]:
        return []


def build_settings(tmp_path: Path) -> Settings:
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
        supabase_timeout_seconds=30,
        admin_access_password="secret",
        use_chrome_profile_extension=False,
        chrome_profile_dir=None,
        chrome_executable_path=None,
    )


def test_cleanup_local_data_removes_only_old_safe_files(tmp_path) -> None:
    settings = build_settings(tmp_path)
    local_data_dir = settings.local_data_dir
    old_file = local_data_dir / "temp_photos" / "old.jpg"
    new_file = local_data_dir / "temp_photos" / "new.jpg"
    old_file.parent.mkdir(parents=True, exist_ok=True)
    old_file.write_bytes(b"old")
    new_file.write_bytes(b"new")

    old_ts = (datetime.now(timezone.utc) - timedelta(hours=12)).timestamp()
    os.utime(old_file, (old_ts, old_ts))

    service = MaintenanceService(
        settings=settings,
        photos_repository=StubPhotosRepository([]),
        client_provider=StubClientProvider(),
    )

    report = service.cleanup_local_data(dry_run=False, temp_photos_hours=8)

    assert report["temp_photos"]["removed"] == 1
    assert old_file.exists() is False
    assert new_file.exists() is True


def test_archive_consumed_photos_moves_storage_and_updates_status(tmp_path) -> None:
    consumed_at = datetime.now(timezone.utc) - timedelta(days=10)
    records = [
        StubPhotoRecord(
            photo_id="photo-1",
            status=PhotoStatus.CONSUMED,
            storage_path="available/photo-1.jpg",
            consumed_at=consumed_at,
        )
    ]
    repository = StubPhotosRepository(records)
    client_provider = StubClientProvider()
    service = MaintenanceService(
        settings=build_settings(tmp_path),
        photos_repository=repository,
        client_provider=client_provider,
    )

    report = service.archive_consumed_photos(dry_run=False, older_than_days=7, limit=10)

    assert report["archived_count"] == 1
    assert client_provider.moves == [("photo-pool", "available/photo-1.jpg", "archived/photo-1.jpg")]
    assert records[0].status == PhotoStatus.ARCHIVED
    assert records[0].storage_path == "archived/photo-1.jpg"
