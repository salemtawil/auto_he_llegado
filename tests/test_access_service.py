from __future__ import annotations

from datetime import date

from services.access_service import AccessService
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
    service._latest_weekly_batch = lambda _user_id, _week_start: latest_batch  # type: ignore[method-assign]  # noqa: SLF001
    service.current_week_start = lambda: date(2026, 6, 15)  # type: ignore[method-assign]
    return service


def test_approved_member_can_use_app_without_weekly_video() -> None:
    snapshot = _service_with_batch(None).get_access_snapshot(_session())

    assert snapshot.can_use_app is True
    assert snapshot.needs_weekly_video is False
    assert "Puedes subir tu video cuando quieras" in snapshot.reason


def test_approved_member_can_use_app_after_rejected_video() -> None:
    snapshot = _service_with_batch({"status": "rejected"}).get_access_snapshot(_session())

    assert snapshot.can_use_app is True
    assert snapshot.needs_weekly_video is False
    assert "subir un video nuevo" in snapshot.reason
