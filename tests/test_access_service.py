from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

from services.access_service import AccessService, VideoRequirementPolicy
from services.auth_context import AuthSession


def _session() -> AuthSession:
    return AuthSession(
        user_id="user-1",
        email="usuario",
        access_token="token",
        refresh_token="refresh",
        role="member",
        approved=True,
        disabled=False,
    )


def _service_with_batch(latest_batch: dict | None) -> AccessService:
    service = AccessService.__new__(AccessService)
    service.get_profile = lambda *, user_id: {  # type: ignore[method-assign]
        "id": user_id,
        "approved": True,
        "disabled": False,
        "role": "member",
    }
    service.get_video_requirement_policy = lambda: VideoRequirementPolicy(  # type: ignore[method-assign]
        enabled=True,
        days=7,
        duration_based=True,
        long_video_days=14,
        long_video_min_duration_seconds=25,
        source="supabase",
    )
    service._latest_required_video_batch = lambda _user_id, _period_start: latest_batch  # type: ignore[method-assign]  # noqa: SLF001
    service.current_requirement_start = lambda _days: date(2026, 6, 3)  # type: ignore[method-assign]
    return service


class _FakeAuth:
    def __init__(self) -> None:
        self.sign_up_payloads = []

    def sign_up(self, payload: dict):
        self.sign_up_payloads.append(payload)
        return SimpleNamespace(user=SimpleNamespace(id="new-user-1"), session=None)


class _FakeClient:
    def __init__(self) -> None:
        self.auth = _FakeAuth()
        self.rpc_calls = []

    def rpc(self, name: str, payload: dict):
        self.rpc_calls.append((name, payload))
        return SimpleNamespace(name=name, payload=payload)


class _FakeClientProvider:
    def __init__(self, existing_identifiers: set[str] | None = None) -> None:
        self.client = _FakeClient()
        self.existing_identifiers = existing_identifiers or set()

    def execute(self, query):
        identifier = str(query.payload["p_identifier"]).lower()
        if identifier in self.existing_identifiers:
            return [{"email": "existing@example.com"}]
        return []


class _FakePolicyClient:
    def __init__(self) -> None:
        self.rpc_calls = []

    def rpc(self, name: str, payload: dict):
        self.rpc_calls.append((name, payload))
        return SimpleNamespace(name=name, payload=payload)


class _FakePolicyProvider:
    def __init__(self, rows=None, error: Exception | None = None) -> None:
        self.client = _FakePolicyClient()
        self.rows = rows or []
        self.error = error

    def execute(self, _query):
        if self.error is not None:
            raise self.error
        return self.rows


def _service_for_registration(existing_identifiers: set[str] | None = None) -> AccessService:
    service = AccessService.__new__(AccessService)
    service._client_provider = _FakeClientProvider(existing_identifiers)  # noqa: SLF001
    return service


def _service_for_policy(provider: _FakePolicyProvider) -> AccessService:
    service = AccessService.__new__(AccessService)
    service._client_provider = provider  # noqa: SLF001
    service._settings = SimpleNamespace(video_requirement_days=7)  # noqa: SLF001
    return service


def test_approved_member_must_upload_weekly_video_before_using_app() -> None:
    snapshot = _service_with_batch(None).get_access_snapshot(_session())

    assert snapshot.can_use_app is False
    assert snapshot.needs_weekly_video is True
    assert "cada 7 dias" in snapshot.reason


def test_approved_member_must_upload_again_after_rejected_video() -> None:
    snapshot = _service_with_batch({"status": "rejected"}).get_access_snapshot(_session())

    assert snapshot.can_use_app is False
    assert snapshot.needs_weekly_video is True
    assert "fue rechazado" in snapshot.reason


def test_approved_member_can_use_app_with_current_week_video_received() -> None:
    snapshot = _service_with_batch({"status": "pending_review", "video_duration_seconds": 12}).get_access_snapshot(_session())

    assert snapshot.can_use_app is True
    assert snapshot.needs_weekly_video is False
    assert "ultimos 7 dias" in snapshot.reason


def test_long_video_extends_requirement_window() -> None:
    old_enough_for_short_video = datetime.now(timezone.utc) - timedelta(days=10)
    snapshot = _service_with_batch(
        {
            "status": "pending_review",
            "video_duration_seconds": 26,
            "created_at": old_enough_for_short_video.isoformat(),
        }
    ).get_access_snapshot(_session())

    assert snapshot.can_use_app is True
    assert snapshot.needs_weekly_video is False
    assert "ultimos 14 dias" in snapshot.reason


def test_short_video_expires_on_short_window_even_when_inside_long_window() -> None:
    old_enough_for_short_video = datetime.now(timezone.utc) - timedelta(days=10)
    snapshot = _service_with_batch(
        {
            "status": "pending_review",
            "video_duration_seconds": 12,
            "created_at": old_enough_for_short_video.isoformat(),
        }
    ).get_access_snapshot(_session())

    assert snapshot.can_use_app is False
    assert snapshot.needs_weekly_video is True


def test_duration_policy_can_be_disabled_for_fixed_days() -> None:
    old_enough_for_short_video = datetime.now(timezone.utc) - timedelta(days=10)
    service = _service_with_batch(
        {
            "status": "pending_review",
            "video_duration_seconds": 30,
            "created_at": old_enough_for_short_video.isoformat(),
        }
    )
    service.get_video_requirement_policy = lambda: VideoRequirementPolicy(  # type: ignore[method-assign]
        enabled=True,
        days=7,
        duration_based=False,
        long_video_days=14,
        long_video_min_duration_seconds=25,
        source="supabase",
    )

    snapshot = service.get_access_snapshot(_session())

    assert snapshot.can_use_app is False
    assert snapshot.needs_weekly_video is True


def test_approved_member_can_use_app_when_remote_video_requirement_is_disabled() -> None:
    service = _service_with_batch(None)
    service.get_video_requirement_policy = lambda: VideoRequirementPolicy(  # type: ignore[method-assign]
        enabled=False,
        days=14,
        source="supabase",
    )

    snapshot = service.get_access_snapshot(_session())

    assert snapshot.can_use_app is True
    assert snapshot.needs_weekly_video is False
    assert "no requerido" in snapshot.reason


def test_admin_can_use_app_without_weekly_video() -> None:
    service = _service_with_batch(None)
    service.get_profile = lambda *, user_id: {  # type: ignore[method-assign]
        "id": user_id,
        "approved": True,
        "disabled": False,
        "role": "admin",
    }

    snapshot = service.get_access_snapshot(_session())

    assert snapshot.can_use_app is True
    assert snapshot.needs_weekly_video is False
    assert "admin" in snapshot.reason.lower()


def test_video_exempt_member_can_use_app_without_weekly_video() -> None:
    service = _service_with_batch(None)
    service.get_profile = lambda *, user_id: {  # type: ignore[method-assign]
        "id": user_id,
        "approved": True,
        "disabled": False,
        "role": "member",
        "video_exempt": True,
    }

    snapshot = service.get_access_snapshot(_session())

    assert snapshot.can_use_app is True
    assert snapshot.needs_weekly_video is False
    assert "exento" in snapshot.reason.lower()


def test_video_requirement_policy_reads_days_from_supabase() -> None:
    service = _service_for_policy(
        _FakePolicyProvider(
            [
                {
                    "enabled": True,
                    "days": 7,
                    "duration_based": True,
                    "long_video_days": 14,
                    "long_video_min_duration_seconds": 25,
                }
            ]
        )
    )

    policy = service.get_video_requirement_policy()

    assert policy.enabled is True
    assert policy.days == 7
    assert policy.duration_based is True
    assert policy.long_video_days == 14
    assert policy.long_video_min_duration_seconds == 25
    assert policy.source == "supabase"


def test_video_requirement_policy_falls_back_to_local_days_when_supabase_is_missing() -> None:
    provider = _FakePolicyProvider(error=RuntimeError("function missing"))
    service = _service_for_policy(provider)

    policy = service.get_video_requirement_policy()

    assert policy.enabled is True
    assert policy.days == 7
    assert policy.source == "local"


def test_register_member_creates_pending_auth_user_with_login_id() -> None:
    service = _service_for_registration()

    result = service.register_member(
        login_id="Agente.Uno",
        email="AGENTE@example.com",
        password="secret123",
        display_name="Agente Uno",
    )

    payload = service._client_provider.client.auth.sign_up_payloads[0]  # noqa: SLF001
    assert result.user_id == "new-user-1"
    assert result.login_id == "agente.uno"
    assert result.email == "agente@example.com"
    assert result.needs_email_confirmation is True
    assert payload["email"] == "agente@example.com"
    assert payload["options"]["data"] == {
        "login_id": "agente.uno",
        "display_name": "Agente Uno",
    }


def test_register_member_rejects_existing_login_id_before_signup() -> None:
    service = _service_for_registration({"agente"})

    try:
        service.register_member(
            login_id="agente",
            email="nuevo@example.com",
            password="secret123",
        )
    except RuntimeError as exc:
        assert "usuario ya existe" in str(exc)
    else:
        raise AssertionError("Expected existing login id to be rejected.")

    assert service._client_provider.client.auth.sign_up_payloads == []  # noqa: SLF001


def test_register_member_rejects_invalid_login_id_before_network_calls() -> None:
    service = _service_for_registration()

    try:
        service.register_member(
            login_id="alvaro>",
            email="nuevo@example.com",
            password="secret123",
        )
    except ValueError as exc:
        assert "3 a 32 caracteres" in str(exc)
    else:
        raise AssertionError("Expected invalid login id to be rejected.")

    provider = service._client_provider  # noqa: SLF001
    assert provider.client.rpc_calls == []
    assert provider.client.auth.sign_up_payloads == []
