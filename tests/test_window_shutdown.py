"""Cooperative, bounded application close.

Closing must not silently kill a run mid-flight: the run owns its Playwright
session and its own cleanup (release the reserved photo, delete the temp copy,
persist the result). The close asks it to stop, waits a bounded time on the
owning thread, and says so plainly if the run never answers.
"""

from __future__ import annotations

import threading
import time
from types import SimpleNamespace

import pytest

from services.process_service import ProcessService
from ui.main_app.window import MainAppWindow


class _Slot:
    def __init__(self, thread=None) -> None:
        self.thread = thread
        self.panel = SimpleNamespace(
            run_button=SimpleNamespace(configure=lambda **_kw: None),
            clear_button=SimpleNamespace(configure=lambda **_kw: None),
        )


def _window(*, slots, active, service, answers=None, messages=None):
    asked: list[str] = []

    def askyesno(_title, message, **_kwargs):
        asked.append(message)
        return answers.pop(0) if answers else True

    window = SimpleNamespace(
        _is_closing=False,
        _close_prompt_open=False,
        _slots=slots,
        _process_service=service,
        _active_process_count=lambda: active,
        _cleanup_owner_selfie_temp_files=lambda: None,
        _stop_process_timer=lambda _slot_id, prefix=None: None,
        _broadcast_status_message=lambda message, color=None: (
            messages.append(message) if messages is not None else None
        ),
        _safe_after=lambda _delay, callback, allow_during_close=False: callback(),
        _destroy_after_shutdown=lambda: (messages or []).append("__destroyed__"),
        SHUTDOWN_GRACE_SECONDS=1.0,
        _asked=asked,
        _askyesno=askyesno,
    )
    # bind the real, unbound shutdown routine to this stub
    window._shutdown_and_destroy = lambda: MainAppWindow._shutdown_and_destroy(window)
    return window


def _close(window, monkeypatch, *, confirm=True):
    import ui.main_app.window as window_module

    monkeypatch.setattr(window_module.messagebox, "askyesno", window._askyesno)
    started: list[threading.Thread] = []
    real_thread = threading.Thread

    def capture(*args, **kwargs):
        thread = real_thread(*args, **kwargs)
        started.append(thread)
        return thread

    monkeypatch.setattr(window_module.threading, "Thread", capture)
    MainAppWindow._handle_app_close(window, confirm=confirm)
    for thread in started:
        thread.join(timeout=10)
    return started


class _StubService:
    def __init__(self) -> None:
        self.begin_shutdown_calls = 0
        self.shutdown_calls = 0
        self.shutdown_order: list[str] = []

    def begin_shutdown(self) -> int:
        self.begin_shutdown_calls += 1
        self.shutdown_order.append("begin_shutdown")
        return 1

    def shutdown(self) -> None:
        self.shutdown_calls += 1
        self.shutdown_order.append("shutdown")


def test_close_without_runs_needs_no_confirmation(monkeypatch) -> None:
    service = _StubService()
    messages: list[str] = []
    window = _window(slots={}, active=0, service=service, messages=messages)

    _close(window, monkeypatch)

    assert window._asked == [], "no prompt when nothing is running"
    assert window._is_closing is True
    assert service.shutdown_calls == 1
    assert "__destroyed__" in messages


def test_close_can_be_refused_and_changes_nothing(monkeypatch) -> None:
    service = _StubService()
    messages: list[str] = []
    window = _window(slots={}, active=2, service=service, answers=[False], messages=messages)

    _close(window, monkeypatch)

    assert len(window._asked) == 1
    assert "2 proceso(s) en ejecución" in window._asked[0]
    assert window._is_closing is False
    assert service.begin_shutdown_calls == 0
    assert service.shutdown_calls == 0
    assert messages == []


def test_confirmed_close_cancels_runs_then_waits_then_tears_down(monkeypatch) -> None:
    """The run thread must finish its own cleanup before BrowserManager is torn down."""

    service = _StubService()
    messages: list[str] = []
    cleanup_done = threading.Event()

    def worker() -> None:
        time.sleep(0.2)
        cleanup_done.set()  # stands in for the run's finally block
        service.shutdown_order.append("run_cleanup")

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    window = _window(
        slots={"a": _Slot(thread)}, active=1, service=service, answers=[True], messages=messages
    )

    _close(window, monkeypatch)
    thread.join(timeout=5)

    assert cleanup_done.is_set()
    assert service.begin_shutdown_calls == 1
    assert service.shutdown_order == ["begin_shutdown", "run_cleanup", "shutdown"], (
        "the browsers must be torn down only after the run finished its own cleanup"
    )
    assert "__destroyed__" in messages


def test_unresponsive_run_is_reported_not_papered_over(monkeypatch) -> None:
    service = _StubService()
    messages: list[str] = []
    keep_running = threading.Event()

    thread = threading.Thread(target=lambda: keep_running.wait(20), daemon=True)
    thread.start()
    window = _window(
        slots={"a": _Slot(thread)}, active=1, service=service, answers=[True], messages=messages
    )

    try:
        _close(window, monkeypatch)
    finally:
        keep_running.set()

    assert any("no respondieron a tiempo" in message for message in messages), messages
    assert "__destroyed__" in messages  # the app still closes


# --------------------------------------------------------------------------
# ProcessService side of the cooperative stop
# --------------------------------------------------------------------------


def test_begin_shutdown_cancels_active_runs_and_refuses_new_ones() -> None:
    service = ProcessService.__new__(ProcessService)
    service._active_runs = {}
    service._active_runs_lock = threading.Lock()
    service._closing = threading.Event()

    context = SimpleNamespace(cancel_event=threading.Event())
    service._active_runs[threading.get_ident()] = context

    assert service.active_run_count() == 1
    assert service.begin_shutdown() == 1
    assert context.cancel_event.is_set() is True
    assert service.is_closing() is True

    with pytest.raises(RuntimeError, match="cerrando"):
        ProcessService.execute(service, SimpleNamespace())


def test_a_second_close_while_the_dialog_is_open_does_not_stack_another(monkeypatch) -> None:
    """askyesno pumps the Tk event loop, so WM_DELETE can re-enter the handler."""

    import ui.main_app.window as window_module

    service = _StubService()
    messages: list[str] = []
    window = _window(slots={}, active=1, service=service, messages=messages)
    reentered: list[int] = []

    def askyesno(_title, _message, **_kwargs):
        # simulate the event loop delivering a second close while we are open
        MainAppWindow._handle_app_close(window)
        reentered.append(1)
        return False

    monkeypatch.setattr(window_module.messagebox, "askyesno", askyesno)
    MainAppWindow._handle_app_close(window)

    assert len(reentered) == 1, "the re-entrant close must be ignored, not prompt again"
    assert window._is_closing is False
    assert service.begin_shutdown_calls == 0
