from pathlib import Path

from config.settings import Settings
from core.enums import PhotoStatus
from services.process_photo_service import ProcessPhotoService


class StubPhotoRecord:
    def __init__(
        self,
        *,
        photo_id: str,
        original_filename: str = "sample.jpg",
        storage_path: str = "available/sample.jpg",
    ) -> None:
        self.id = photo_id
        self.original_filename = original_filename
        self.storage_path = storage_path
        self.reserved_by_process_id = None


class StubPhotosRepository:
    def __init__(self, records=None) -> None:
        self.records = records or [StubPhotoRecord(photo_id="550e8400-e29b-41d4-a716-446655440000")]
        self.claim_calls = []
        self.update_calls = []
        self.validate_atomic_claim_support_calls = 0

    def validate_atomic_claim_support(self):
        self.validate_atomic_claim_support_calls += 1
        return None

    def claim_available(self, *, process_id=None):
        self.claim_calls.append(process_id)
        if not self.records:
            raise AssertionError("No stub photo records available.")
        return self.records[0]

    def update(self, photo_id, changes):
        self.update_calls.append((photo_id, changes))
        return StubPhotoRecord(photo_id=photo_id)


class StubClientProvider:
    def __init__(self, *, download_error=None) -> None:
        self.download_error = download_error
        self.download_calls = []

    def download_binary(self, *, bucket_name, storage_path):
        self.download_calls.append((bucket_name, storage_path))
        if self.download_error is not None:
            raise self.download_error
        return b"jpg-data"


class StubTempFileService:
    def __init__(self, tmp_path: Path) -> None:
        self.tmp_path = tmp_path
        self.deleted = []

    def create_photo_copy(self, *, content: bytes, original_filename: str) -> Path:
        path = self.tmp_path / original_filename
        path.write_bytes(content)
        return path

    def delete_file(self, path_value) -> None:
        path = Path(path_value)
        self.deleted.append(str(path))
        if path.exists():
            path.unlink()


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


def test_reserve_photo_marks_reserved_downloads_and_creates_local_copy(tmp_path) -> None:
    repository = StubPhotosRepository()
    client_provider = StubClientProvider()
    temp_file_service = StubTempFileService(tmp_path)
    service = ProcessPhotoService(
        photos_repository=repository,
        client_provider=client_provider,
        temp_file_service=temp_file_service,
        settings=build_settings(tmp_path),
    )

    reserved = service.reserve_photo()

    assert reserved.photo_id == "550e8400-e29b-41d4-a716-446655440000"
    assert Path(reserved.local_path).exists() is True
    assert repository.validate_atomic_claim_support_calls == 1
    assert repository.claim_calls == [None]
    assert client_provider.download_calls == [("photo-pool", "available/sample.jpg")]


def test_reserve_photo_consumes_record_if_download_fails(tmp_path) -> None:
    repository = StubPhotosRepository()
    service = ProcessPhotoService(
        photos_repository=repository,
        client_provider=StubClientProvider(download_error=RuntimeError("storage down")),
        temp_file_service=StubTempFileService(tmp_path),
        settings=build_settings(tmp_path),
    )

    try:
        service.reserve_photo()
    except RuntimeError as exc:
        assert str(exc) == "storage down"
    else:
        raise AssertionError("Expected reserve_photo to raise when download fails.")

    assert repository.claim_calls == [None]
    assert repository.validate_atomic_claim_support_calls == 1
    assert repository.update_calls[0][1].status == PhotoStatus.AVAILABLE
