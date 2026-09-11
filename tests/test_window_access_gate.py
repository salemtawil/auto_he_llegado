from __future__ import annotations

from datetime import date
from types import SimpleNamespace

from services.access_service import AccessSnapshot
from services.auth_context import AuthSession, set_current_session
from services.video_contribution_service import VideoContributionProgress
from ui.main_app.window import MainAppWindow, ProcessSlotRuntime


class _FakeButton:
    def __init__(self) -> None:
        self.state = "normal"

    def configure(self, **kwargs) -> None:
        if "state" in kwargs:
            self.state = kwargs["state"]


class _FakeStatusPanel:
    def __init__(self) -> None:
        self.messages: list[tuple[str, str | None]] = []

    def set_message(self, message: str, *, color: str | None = None) -> None:
        self.messages.append((message, color))


class _FakePanel:
    def __init__(self) -> None:
        self.run_button = _FakeButton()
        self.status_panel = _FakeStatusPanel()
        self.form_panel = SimpleNamespace(page_menu=SimpleNamespace(get=lambda: "Compinche"))
        self.summary: list[str] = []

    def set_summary(self, text: str) -> None:
        self.summary.append(text)


class _FakeAccessService:
    def __init__(self, snapshot: AccessSnapshot) -> None:
        self.snapshot = snapshot
        self.calls = 0

    def get_access_snapshot(self, _session):
        self.calls += 1
        return self.snapshot


class _FakeProcessService:
    def __init__(self) -> None:
        self.register_calls = []

    def register_process_slot(self, process_id: str, slot_id: str) -> None:
        self.register_calls.append((process_id, slot_id))


def _session(*, role: str = "member") -> AuthSession:
    return AuthSession(
        user_id="user-1",
        email="usuario",
        access_token="token",
        refresh_token="refresh",
        role=role,
        approved=True,
        disabled=False,
    )


def _snapshot(*, can_use_app: bool, reason: str) -> AccessSnapshot:
    return AccessSnapshot(
        can_use_app=can_use_app,
        needs_weekly_video=not can_use_app,
        reason=reason,
        week_start=date(2026, 8, 31),
        profile={"id": "user-1", "role": "member", "approved": True},
    )


def _window_for_gate(*, session: AuthSession, snapshot: AccessSnapshot) -> MainAppWindow:
    set_current_session(None)
    window = MainAppWindow.__new__(MainAppWindow)
    window._is_closing = False  # noqa: SLF001
    window._auth_session = session  # noqa: SLF001
    window._access_snapshot = snapshot  # noqa: SLF001
    window._process_access_block_reason = "" if snapshot.can_use_app else snapshot.reason  # noqa: SLF001
    window._current_config = SimpleNamespace(flow_engine="traditional")  # noqa: SLF001
    window._active_slot_id = "slot_1"  # noqa: SLF001
    window._layout_mode = "wide"  # noqa: SLF001
    window._process_to_slot = {}  # noqa: SLF001
    window._latest_debug_slot_id = "slot_1"  # noqa: SLF001
    window._access_service = _FakeAccessService(snapshot)  # noqa: SLF001
    window._process_service = _FakeProcessService()  # noqa: SLF001
    window._safe_after = lambda _delay, callback: callback()  # type: ignore[method-assign]  # noqa: SLF001
    window._broadcast_status_message = lambda _message, **_kwargs: None  # type: ignore[method-assign]  # noqa: SLF001
    window._slots = {  # noqa: SLF001
        "slot_1": ProcessSlotRuntime(slot_id="slot_1", panel=_FakePanel(), thread=None),
        "slot_2": ProcessSlotRuntime(slot_id="slot_2", panel=_FakePanel(), thread=None),
    }
    window._refresh_header_summary = lambda: None  # type: ignore[method-assign]  # noqa: SLF001
    window._layout_slots = lambda _mode: None  # type: ignore[method-assign]  # noqa: SLF001
    return window


def test_member_process_buttons_stay_locked_without_weekly_video() -> None:
    window = _window_for_gate(
        session=_session(),
        snapshot=_snapshot(can_use_app=False, reason="Debes subir video."),
    )

    window._sync_run_button_state()  # noqa: SLF001

    assert window._slots["slot_1"].panel.run_button.state == "disabled"  # noqa: SLF001
    assert window._slots["slot_2"].panel.run_button.state == "disabled"  # noqa: SLF001


def test_member_process_buttons_unlock_after_weekly_video_received() -> None:
    window = _window_for_gate(
        session=_session(),
        snapshot=_snapshot(can_use_app=True, reason="Video semanal recibido."),
    )

    window._sync_run_button_state()  # noqa: SLF001

    assert window._slots["slot_1"].panel.run_button.state == "normal"  # noqa: SLF001
    assert window._slots["slot_2"].panel.run_button.state == "normal"  # noqa: SLF001


def test_optional_video_received_progress_unlocks_member_temporarily() -> None:
    window = _window_for_gate(
        session=_session(),
        snapshot=_snapshot(can_use_app=False, reason="Debes subir video."),
    )
    window._sync_run_button_state()  # noqa: SLF001

    window._apply_optional_video_progress(  # noqa: SLF001
        VideoContributionProgress(
            phase="received",
            message="Video registrado. Acceso temporal activo mientras se revisa.",
            current=0,
            total=1,
        )
    )

    assert window._access_snapshot is not None  # noqa: SLF001
    assert window._access_snapshot.can_use_app is True  # noqa: SLF001
    assert window._slots["slot_1"].panel.run_button.state == "normal"  # noqa: SLF001
    assert window._slots["slot_2"].panel.run_button.state == "normal"  # noqa: SLF001


def test_start_process_revalidates_and_blocks_when_video_is_missing() -> None:
    window = _window_for_gate(
        session=_session(),
        snapshot=_snapshot(can_use_app=False, reason="Para usar la app debes subir video."),
    )

    window.start_process("slot_1")

    panel = window._slots["slot_1"].panel  # noqa: SLF001
    assert "subir video" in panel.status_panel.messages[-1][0]
    assert window._process_service.register_calls == []  # noqa: SLF001


def test_admin_process_buttons_do_not_require_weekly_video() -> None:
    window = _window_for_gate(
        session=_session(role="admin"),
        snapshot=_snapshot(can_use_app=False, reason="Debes subir video."),
    )

    window._sync_run_button_state()  # noqa: SLF001

    assert window._slots["slot_1"].panel.run_button.state == "normal"  # noqa: SLF001
    assert window._slots["slot_2"].panel.run_button.state == "normal"  # noqa: SLF001
