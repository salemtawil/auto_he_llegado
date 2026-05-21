from pathlib import Path

from config.settings import Settings
from services.uploader_service import UploaderService


class StubClientProvider:
    def __init__(
        self,
        *,
        upload_error: Exception | None = None,
        remove_error: Exception | None = None,
    ) -> None:
        self.upload_error = upload_error
        self.remove_error = remove_error
        self.upload_calls: list[tuple[str, str, bytes]] = []
        self.remove_calls: list[tuple[str, str]] = []

    def upload_binary(
        self,
        *,
        bucket_name: str,
        storage_path: str,
        content: bytes,
        content_type: str = "image/jpeg",
        upsert: bool = False,
    ) -> None:
        self.upload_calls.append((bucket_name, storage_path, content))
        if self.upload_error is not None:
            raise self.upload_error

    def remove_file(self, *, bucket_name: str, storage_path: str) -> None:
        self.remove_calls.append((bucket_name, storage_path))
        if self.remove_error is not None:
            raise self.remove_error


class StubPhotoRecord:
    def __init__(self, *, photo_id: str, storage_path: str) -> None:
        self.id = photo_id
        self.storage_path = storage_path


class StubPhotosRepository:
    def __init__(self, *, create_error: Exception | None = None) -> None:
        self.create_error = create_error
        self.created_photos = []
        self.bulk_created_photos = []

    def create(self, photo) -> StubPhotoRecord:
        self.created_photos.append(photo)
        if self.create_error is not None:
            raise self.create_error
        return StubPhotoRecord(photo_id=photo.id, storage_path=photo.storage_path)

    def bulk_create(self, photos) -> list[StubPhotoRecord]:
        self.bulk_created_photos.append(list(photos))
        if self.create_error is not None:
            raise self.create_error
        return [StubPhotoRecord(photo_id=photo.id, storage_path=photo.storage_path) for photo in photos]


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


def test_upload_failure_reports_storage_phase_and_moves_file(tmp_path) -> None:
    source = tmp_path / "example.jpg"
    source.write_bytes(b"jpg-data")
    settings = build_settings(tmp_path)
    client_provider = StubClientProvider(upload_error=RuntimeError("bucket denied"))
    service = UploaderService(
        photos_repository=StubPhotosRepository(),
        client_provider=client_provider,
        settings=settings,
    )

    result = service.upload_file(source)

    assert result.success is False
    assert result.storage_uploaded is False
    assert result.storage_error == "bucket denied"
    assert result.database_inserted is False
    assert result.database_error is None
    assert "Fallo en storage upload" in result.message
    assert result.failed_file_path is not None
    assert Path(result.failed_file_path).exists()
    assert source.exists() is False
    assert client_provider.remove_calls == []


def test_database_failure_reports_insert_phase_and_not_storage_phase(tmp_path) -> None:
    source = tmp_path / "example.jpg"
    source.write_bytes(b"jpg-data")
    settings = build_settings(tmp_path)
    client_provider = StubClientProvider()
    service = UploaderService(
        photos_repository=StubPhotosRepository(
            create_error=RuntimeError("new row violates row-level security policy")
        ),
        client_provider=client_provider,
        settings=settings,
    )

    result = service.upload_file(source)

    assert result.success is False
    assert result.storage_uploaded is True
    assert result.storage_error is None
    assert result.database_inserted is False
    assert result.database_error == "new row violates row-level security policy"
    assert "Storage upload completado" in result.message
    assert "registro en base de datos" in result.message
    assert result.failed_file_path is not None
    assert client_provider.remove_calls == [("photo-pool", result.storage_path)]


def test_local_cleanup_failure_is_reported_as_warning_after_success(
    tmp_path,
    monkeypatch,
) -> None:
    source = tmp_path / "example.jpg"
    source.write_bytes(b"jpg-data")
    settings = build_settings(tmp_path)
    service = UploaderService(
        photos_repository=StubPhotosRepository(),
        client_provider=StubClientProvider(),
        settings=settings,
    )

    def fail_unlink(self) -> None:
        raise OSError("file is locked")

    monkeypatch.setattr(Path, "unlink", fail_unlink)

    result = service.upload_file(source, delete_local_on_success=True)

    assert result.success is True
    assert result.storage_uploaded is True
    assert result.database_inserted is True
    assert (
        result.local_cleanup_error
        == "No se pudo borrar el archivo local: file is locked"
    )
    assert "local cleanup" in result.message
    assert source.exists() is True


def test_upload_files_emits_live_progress_updates(tmp_path) -> None:
    source = tmp_path / "example.jpg"
    source.write_bytes(b"jpg-data")
    settings = build_settings(tmp_path)
    service = UploaderService(
        photos_repository=StubPhotosRepository(),
        client_provider=StubClientProvider(),
        settings=settings,
    )
    events = []

    results = service.upload_files([source], progress_callback=events.append)

    assert len(results) == 1
    assert events[0].status_text == "Preparando archivos..."
    assert [event.current_file_status for event in events if event.current_file_status] == [
        "Subiendo",
        "Storage OK",
        "Pendiente DB",
        "Database OK",
        "Completado",
        "Completado",
    ]
    assert events[-1].status_text == "Finalizado"
    assert events[-1].processed_count == 1
    assert events[-1].success_count == 1
    assert events[-1].failed_count == 0


def test_upload_file_does_not_depend_on_unconfirmed_photo_columns(tmp_path) -> None:
    source = tmp_path / "example.jpg"
    source.write_bytes(b"jpg-data")
    settings = build_settings(tmp_path)
    repository = StubPhotosRepository()
    service = UploaderService(
        photos_repository=repository,
        client_provider=StubClientProvider(),
        settings=settings,
    )

    result = service.upload_file(source)

    assert result.success is True
    assert len(repository.created_photos) == 1
    created_photo = repository.created_photos[0]
    assert created_photo.original_filename == "example.jpg"
    assert created_photo.storage_path.endswith(".jpg")
    assert created_photo.source == "uploader_app"
