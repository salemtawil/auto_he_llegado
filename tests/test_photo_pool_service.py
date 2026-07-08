from __future__ import annotations

from types import SimpleNamespace
from pathlib import Path

from config.settings import Settings
from services.photo_pool_service import PhotoPoolService


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
        supabase_legacy_storage_buckets=("old-pool",),
    )


class FakeRpcClient:
    def __init__(self) -> None:
        self.calls = []

    def rpc(self, name, params):
        self.calls.append((name, params))
        return object()


class FakeClientProvider:
    def __init__(self) -> None:
        self.client = FakeRpcClient()

    def execute_response_factory(self, operation_factory):
        operation_factory()
        return SimpleNamespace(
            data=[
                {
                    "available_count": 12,
                    "new_bucket_count": 7,
                    "old_bucket_count": 5,
                }
            ]
        )


def test_photo_pool_snapshot_uses_rpc_when_available(tmp_path) -> None:
    client_provider = FakeClientProvider()
    service = PhotoPoolService(
        client_provider=client_provider,
        settings=build_settings(tmp_path),
    )

    snapshot = service.get_snapshot()

    assert snapshot.available_count == 12
    assert snapshot.new_bucket_count == 7
    assert snapshot.old_bucket_count == 5
    assert client_provider.client.calls == [
        (
            "photo_pool_counts",
            {"p_active_bucket": "photo-pool", "p_legacy_bucket": "old-pool"},
        )
    ]
