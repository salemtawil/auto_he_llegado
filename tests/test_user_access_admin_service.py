from __future__ import annotations

from types import SimpleNamespace

from services.user_access_admin_service import UserAccessAdminService


class _FakeTable:
    def __init__(self, sink: dict) -> None:
        self._sink = sink

    def upsert(self, payload: dict):
        self._sink["upsert"] = payload
        return self

    def insert(self, payload: dict):
        self._sink.setdefault("insert", []).append(payload)
        return self

    def update(self, payload: dict):
        self._sink.setdefault("updates", []).append(payload)
        self._sink["update"] = payload
        return self

    def eq(self, column: str, value: str):
        self._sink.setdefault("filters", []).append(("eq", column, value))
        self._sink["eq"] = (column, value)
        return self

    def in_(self, column: str, values: list[str]):
        self._sink.setdefault("filters", []).append(("in", column, values))
        self._sink["in"] = (column, values)
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
        if "insert" in self.sink and "update" not in self.sink:
            return [self.sink["insert"][-1]]
        if "update" in self.sink:
            return [
                {
                    "id": self.sink["eq"][1],
                    "email": "agente@example.com",
                    "login_id": "agente",
                    "display_name": "Agente",
                    "role": "member",
                    "approved": True,
                    "disabled": False,
                    **self.sink["update"],
                }
            ]
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


def test_set_video_exempt_updates_profile_without_admin_role() -> None:
    sink: dict = {}
    service = UserAccessAdminService.__new__(UserAccessAdminService)
    service._client_provider = _FakeProvider(sink)  # noqa: SLF001
    service._settings = SimpleNamespace()  # noqa: SLF001
    service._table = "profiles"  # noqa: SLF001
    service._batches_table = "photo_ingest_batches"  # noqa: SLF001
    service.get_video_requirement_policy = lambda: SimpleNamespace(days=7)  # type: ignore[method-assign]
    service._latest_weekly_video = lambda _user_id: None  # type: ignore[method-assign]  # noqa: SLF001

    user = service.set_video_exempt("user-1", True)

    assert sink["table"] == "profiles"
    assert sink["eq"] == ("id", "user-1")
    assert sink["update"]["video_exempt"] is True
    assert "role" not in sink["update"]
    assert user.video_exempt is True
    assert user.role == "member"
    assert sink["insert"][0]["user_id"] == "user-1"
    assert sink["insert"][0]["status"] == "accepted"
    assert sink["insert"][0]["original_video_name"] == "exencion_admin_sin_video"


def test_require_video_revokes_admin_exemption_batches() -> None:
    sink: dict = {}
    service = UserAccessAdminService.__new__(UserAccessAdminService)
    service._client_provider = _FakeProvider(sink)  # noqa: SLF001
    service._settings = SimpleNamespace()  # noqa: SLF001
    service._table = "profiles"  # noqa: SLF001
    service._batches_table = "photo_ingest_batches"  # noqa: SLF001
    service._latest_weekly_video = lambda _user_id: None  # type: ignore[method-assign]  # noqa: SLF001

    user = service.set_video_exempt("user-1", False)

    assert sink["updates"][0]["status"] == "rejected"
    assert sink["updates"][0]["error_message"] == "Exencion de video revocada por admin."
    assert ("eq", "user_id", "user-1") in sink["filters"]
    assert ("eq", "original_video_name", "exencion_admin_sin_video") in sink["filters"]
    assert sink["in"] == ("status", ["processing", "pending_review", "accepted", "reviewed"])
    assert sink["updates"][1]["video_exempt"] is False
    assert user.video_exempt is False
