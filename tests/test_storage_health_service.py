from __future__ import annotations

from config.settings import Settings
from services.storage_health_service import StorageHealthService


def build_settings(tmp_path, *, storage_limit_mb: int = 0) -> Settings:
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
        supabase_legacy_storage_buckets=(),
        supabase_storage_limit_mb=storage_limit_mb,
    )


class StubPhotosRepository:
    def __init__(self, active_count: int) -> None:
        self.active_count = active_count

    def count_active_storage_records(self) -> int:
        return self.active_count


class StubClientProvider:
    def __init__(self, files: list[dict]) -> None:
        self.files = files
        self.list_calls: list[tuple[str, str, int, int]] = []

    def list_files(self, *, bucket_name: str, folder_path: str = "", limit: int = 1000, offset: int = 0):
        self.list_calls.append((bucket_name, folder_path, limit, offset))
        return self.files


class StubRpcClientProvider(StubClientProvider):
    def __init__(self, files: list[dict], rpc_rows: list[dict]) -> None:
        super().__init__(files)
        self.rpc_rows = rpc_rows
        self.rpc_calls: list[str] = []
        self.client = self

    def rpc(self, name: str):
        self.rpc_calls.append(name)
        return name

    def execute(self, operation):
        assert operation == "storage_usage_by_prefix"
        return self.rpc_rows


def test_storage_health_estimates_usage_and_capacity_from_storage_sample(tmp_path) -> None:
    service = StorageHealthService(
        photos_repository=StubPhotosRepository(active_count=100),
        client_provider=StubClientProvider(
            [
                {"name": "one.jpg", "metadata": {"size": 100_000}},
                {"name": "two.jpg", "metadata": {"size": 300_000}},
            ]
        ),
        settings=build_settings(tmp_path, storage_limit_mb=20),
    )

    snapshot = service.get_snapshot()

    assert snapshot.bucket_names == ["photo-pool"]
    assert snapshot.active_photo_count == 100
    assert snapshot.sampled_file_count == 2
    assert snapshot.average_file_size_bytes == 200_000
    assert snapshot.estimated_used_bytes == 20_000_000
    assert snapshot.configured_limit_bytes == 20 * 1024 * 1024
    assert snapshot.estimated_capacity_photos == 104
    assert snapshot.estimated_remaining_photos == 4
    assert snapshot.status == "Critico"


def test_storage_health_uses_exact_storage_usage_rpc_when_available(tmp_path) -> None:
    client_provider = StubRpcClientProvider(
        [{"name": "one.jpg", "metadata": {"size": 100_000}}],
        [
            {
                "bucket_name": "photo-pool",
                "top_folder": "candidates",
                "object_count": 400,
                "total_bytes": 1_200_000_000,
            },
            {
                "bucket_name": "photo-pool",
                "top_folder": "available",
                "object_count": 100,
                "total_bytes": 400_000_000,
            },
        ],
    )
    service = StorageHealthService(
        photos_repository=StubPhotosRepository(active_count=100),
        client_provider=client_provider,
        settings=build_settings(tmp_path, storage_limit_mb=1024),
    )

    snapshot = service.get_snapshot()

    assert client_provider.rpc_calls == ["storage_usage_by_prefix"]
    assert snapshot.sampled_file_count == 500
    assert snapshot.estimated_used_bytes == 1_600_000_000
    assert snapshot.estimated_available_bytes == 0
    assert snapshot.status == "Critico"
    assert [item.top_folder for item in snapshot.folder_usage] == ["candidates", "available"]


def test_storage_health_does_not_invent_capacity_without_limit_or_file_sizes(tmp_path) -> None:
    service = StorageHealthService(
        photos_repository=StubPhotosRepository(active_count=50),
        client_provider=StubClientProvider([{"name": "one.jpg", "metadata": {}}]),
        settings=build_settings(tmp_path),
    )

    snapshot = service.get_snapshot()

    assert snapshot.sampled_file_count == 0
    assert snapshot.average_file_size_bytes == 0
    assert snapshot.estimated_used_bytes == 0
    assert snapshot.configured_limit_bytes is None
    assert snapshot.estimated_available_bytes is None
    assert snapshot.estimated_capacity_photos is None
    assert snapshot.estimated_remaining_photos is None
    assert snapshot.status == "Sin limite configurado"
