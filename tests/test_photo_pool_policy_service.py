from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from config.settings import Settings
from services.photo_pool_policy_service import PhotoPoolPolicyService


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


class _RpcClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def rpc(self, name: str, params: dict):
        self.calls.append((name, params))
        return object()


class _RpcBucketProvider:
    def __init__(self) -> None:
        self.client = _RpcClient()

    def execute(self, _query):
        return [{"bucket": "photo-pool-v2"}, {"bucket": "photo-pool"}]


class _StorageBucketProvider:
    def __init__(self) -> None:
        self.client = SimpleNamespace(rpc=lambda *_args: object())

    def execute(self, _query):
        raise RuntimeError("rpc missing")

    def list_buckets(self):
        return [{"id": "photo-pool-v3"}, {"name": "photo-pool"}]


def test_list_buckets_uses_supabase_rpc(tmp_path: Path) -> None:
    provider = _RpcBucketProvider()
    service = PhotoPoolPolicyService(client_provider=provider, settings=build_settings(tmp_path))

    buckets = service.list_buckets()

    assert buckets == ["photo-pool-v2", "photo-pool"]
    assert provider.client.calls == [("list_photo_pool_buckets", {})]


def test_list_buckets_falls_back_to_storage_api_and_local_settings(tmp_path: Path) -> None:
    service = PhotoPoolPolicyService(
        client_provider=_StorageBucketProvider(),
        settings=build_settings(tmp_path),
    )

    assert service.list_buckets() == ["photo-pool-v3", "photo-pool", "old-pool"]
