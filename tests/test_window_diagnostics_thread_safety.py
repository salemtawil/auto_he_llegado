"""Diagnostics must never drive Playwright from the Tk thread.

Playwright's sync API is bound to the thread that started the driver. Sessions
are created on the run worker, so a live capture from the UI was both a freeze
and a cross-thread call. When the session is not ours, diagnostics fall back to
the snapshot the run captured and say so.
"""

from __future__ import annotations

import threading
from types import SimpleNamespace

from automation.browser_manager import BrowserSession
from ui.main_app.window import MainAppWindow


class _ForeignSession:
    """A session owned by another thread: touching .page must be a test failure."""

    def __init__(self, last_debug: dict | None = None) -> None:
        self._last_debug = last_debug or {}
        self.live_calls: list[str] = []

    def is_owned_by_current_thread(self) -> bool:
        return False

    @property
    def page(self):  # pragma: no cover - only reached if the guard regresses
        self.live_calls.append("page")
        raise AssertionError("Playwright touched from a thread that does not own it")

    def capture_extension_debug(self, **_kwargs):  # pragma: no cover
        self.live_calls.append("capture_extension_debug")
        raise AssertionError("live capture attempted from the wrong thread")

    def debug_list_all_frames(self, **_kwargs):  # pragma: no cover
        self.live_calls.append("debug_list_all_frames")
        raise AssertionError("live frame listing attempted from the wrong thread")

    def get_last_extension_debug(self):
        return dict(self._last_debug)


class _OwnedSession(_ForeignSession):
    def is_owned_by_current_thread(self) -> bool:
        return True

    @property
    def page(self):
        return SimpleNamespace(url="https://paripe.io/x")

    def capture_extension_debug(self, **_kwargs):
        self.live_calls.append("capture_extension_debug")
        return {"phase": "final_result", "live": True}

    def debug_list_all_frames(self, **_kwargs):
        self.live_calls.append("debug_list_all_frames")
        return {"total_frames": 3, "frames": []}


def test_session_records_its_owning_thread() -> None:
    session = BrowserSession(playwright=None, browser=None, context=None, page=None)
    assert session.is_owned_by_current_thread() is True

    result: list[bool] = []
    worker = threading.Thread(target=lambda: result.append(session.is_owned_by_current_thread()))
    worker.start()
    worker.join(timeout=5)
    assert result == [False]


def test_foreign_session_is_not_usable_and_never_touched() -> None:
    session = _ForeignSession()
    assert MainAppWindow._session_is_usable_here(session) is False
    assert session.live_calls == []


def test_owned_session_is_usable() -> None:
    assert MainAppWindow._session_is_usable_here(_OwnedSession()) is True


def test_a_session_without_the_guard_is_treated_as_foreign() -> None:
    assert MainAppWindow._session_is_usable_here(SimpleNamespace()) is False


def test_debug_payload_from_the_ui_thread_uses_the_last_snapshot(monkeypatch) -> None:
    import ui.main_app.window as window_module

    monkeypatch.setattr(
        window_module.BrowserManager, "get_latest_extension_debug", staticmethod(lambda: {})
    )
    session = _ForeignSession({"phase": "block_read", "frame_debug_report": {"total_frames": 2}})
    window = SimpleNamespace()
    window._session_is_usable_here = MainAppWindow._session_is_usable_here
    window._collect_session_debug_payload = (
        lambda current: MainAppWindow._collect_session_debug_payload(window, current)
    )

    payload, warning = window._collect_session_debug_payload(session)

    assert session.live_calls == [], "no live Playwright call may happen on the UI thread"
    assert warning is None
    assert payload["phase"] == "block_read"
    assert payload["live_capture"] is False
    assert "un solo hilo" in payload["live_capture_note"]


def test_debug_payload_from_the_owning_thread_captures_live() -> None:
    session = _OwnedSession()
    window = SimpleNamespace()
    window._session_is_usable_here = MainAppWindow._session_is_usable_here
    payload, warning = MainAppWindow._collect_session_debug_payload(window, session)

    assert session.live_calls == ["capture_extension_debug"]
    assert warning is None
    assert payload == {"phase": "final_result", "live": True}


def test_frame_report_falls_back_to_the_captured_one() -> None:
    payload = {"frame_debug_report": {"total_frames": 4, "frames": []}}
    assert MainAppWindow._last_known_frame_report(payload) == {"total_frames": 4, "frames": []}


def test_frame_report_says_why_it_is_not_live_when_nothing_was_captured() -> None:
    report = MainAppWindow._last_known_frame_report({})
    assert report["total_frames"] == 0
    assert "hilo del proceso" in report["note"]

    with_error = MainAppWindow._last_known_frame_report({}, error="boom")
    assert with_error["error"] == "boom"
