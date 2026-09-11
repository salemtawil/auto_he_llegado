from __future__ import annotations

from types import SimpleNamespace

from services.user_access_admin_service import UserAccessAdminService


class _FakeTable:
    def __init__(self, sink: dict) -> None:
        self._sink = sink

    def upsert(self, payload: dict):
        self._sink["upsert"] = payload
        return self


class _FakeClient:
    def __init__(self, sink: dict) -> None:
        self._sink = sink

    def table(self, table_name: str):
        self._sink["table"] = table_name
        return _FakeTable(self._sink)


class _FakeProvider:
    def __init__(self, sink: dict) -> None:
        self.client = _FakeClient(sink)
        self.sink = sink

    def execute(self, query):
        self.sink["executed"] = query
        return [self.sink["upsert"]]


def test_update_video_requirement_policy_upserts_app_setting() -> None:
    sink: dict = {}
    service = UserAccessAdminService.__new__(UserAccessAdminService)
    service._client_provider = _FakeProvider(sink)  # noqa: SLF001
    service._settings = SimpleNamespace()  # noqa: SLF001

    policy = service.update_video_requirement_policy(
        enabled=True,
        days=7,
        duration_based=True,
        long_video_days=14,
        long_video_min_duration_seconds=25,
    )

    assert policy.enabled is True
    assert policy.days == 7
    assert policy.duration_based is True
    assert policy.long_video_days == 14
    assert policy.long_video_min_duration_seconds == 25
    assert policy.source == "supabase"
    assert sink["table"] == "app_settings"
    assert sink["upsert"]["key"] == "video_requirement"
    assert sink["upsert"]["value"] == {
        "enabled": True,
        "days": 7,
        "duration_based": True,
        "long_video_days": 14,
        "long_video_min_duration_seconds": 25,
    }


def test_update_video_requirement_policy_clamps_days() -> None:
    sink: dict = {}
    service = UserAccessAdminService.__new__(UserAccessAdminService)
    service._client_provider = _FakeProvider(sink)  # noqa: SLF001
    service._settings = SimpleNamespace()  # noqa: SLF001

    policy = service.update_video_requirement_policy(enabled=False, days=0)

    assert policy.enabled is False
    assert policy.days == 1
    assert policy.long_video_days == 1
    assert sink["upsert"]["value"] == {
        "enabled": False,
        "days": 1,
        "duration_based": False,
        "long_video_days": 1,
        "long_video_min_duration_seconds": 25,
    }
