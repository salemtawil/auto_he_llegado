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


class _TargetsProvider:
    """Responde al RPC de destinos y al de politica activa."""

    def __init__(self, rows) -> None:
        self.client = _RpcClient()
        self._rows = rows

    def execute(self, _query):
        name = self.client.calls[-1][0]
        if name == "photo_pool_upload_targets":
            return self._rows
        if name == "get_photo_pool_policy":
            return [{"bucket": "photo-pool"}]
        raise RuntimeError(f"rpc inesperado: {name}")


class _MissingFunctionProvider:
    """Simula PostgREST cuando la migracion 020 no esta aplicada."""

    def __init__(self) -> None:
        self.client = _RpcClient()

    def execute(self, _query):
        raise RuntimeError(
            "PGRST202: Could not find the function public.photo_pool_upload_targets"
        )


class _NetworkErrorProvider:
    def __init__(self) -> None:
        self.client = _RpcClient()

    def execute(self, _query):
        raise RuntimeError("connection timed out")


TARGET_ROWS = [
    {"bucket": "photo-pool", "is_active": True, "is_eligible": True, "reason": None},
    {"bucket": "photo-pool-v2", "is_active": False, "is_eligible": True, "reason": None},
    {"bucket": "photos", "is_active": False, "is_eligible": False, "reason": "legacy"},
]


def test_upload_targets_come_from_storage_not_from_a_hardcoded_list(tmp_path: Path) -> None:
    provider = _TargetsProvider(TARGET_ROWS)
    service = PhotoPoolPolicyService(client_provider=provider, settings=build_settings(tmp_path))

    result = service.list_upload_targets()

    assert result.migration_applied is True
    assert [t.bucket for t in result.targets] == ["photo-pool", "photo-pool-v2", "photos"]
    # El bucket activo se marca, pero NO limita la lista.
    assert [t.bucket for t in result.targets if t.is_active] == ["photo-pool"]
    assert provider.client.calls[0] == ("photo_pool_upload_targets", {})


def test_allowed_buckets_excludes_only_the_ineligible_ones(tmp_path: Path) -> None:
    service = PhotoPoolPolicyService(
        client_provider=_TargetsProvider(TARGET_ROWS), settings=build_settings(tmp_path)
    )

    assert service.list_allowed_buckets() == ["photo-pool", "photo-pool-v2"]
    assert service.is_allowed_bucket("photos") is False
    assert service.is_allowed_bucket("photo-pool-v2") is True
    assert service.is_allowed_bucket("no-existe") is False


def test_missing_migration_is_reported_not_papered_over(tmp_path: Path) -> None:
    """Sin migracion NO se devuelve el pool activo como si fuese la lista."""

    service = PhotoPoolPolicyService(
        client_provider=_MissingFunctionProvider(), settings=build_settings(tmp_path)
    )

    result = service.list_upload_targets()

    assert result.migration_applied is False
    assert result.targets == ()
    assert service.list_allowed_buckets() == []
    # En particular, el pool activo no se cuela en la lista.
    assert "photo-pool" not in service.list_allowed_buckets()


def test_a_network_error_is_not_reported_as_a_missing_migration(tmp_path: Path) -> None:
    service = PhotoPoolPolicyService(
        client_provider=_NetworkErrorProvider(), settings=build_settings(tmp_path)
    )

    result = service.list_upload_targets()

    assert result.migration_applied is True
    assert result.targets == ()
    assert "timed out" in (result.error or "")
