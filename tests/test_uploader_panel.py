"""Uploader panel: the worker thread must never touch Tk.

Tcl is not thread-safe, and that includes ``Misc.after()`` — it is itself an
interpreter call, so handing work to the UI thread with ``after`` *from* the
worker is the same defect as calling ``configure`` from it. The worker fills
buffers; the UI thread polls them.
"""

from __future__ import annotations

import threading
from types import SimpleNamespace

from ui.uploader.panel import UploaderPanel


class _TkTripwire:
    """Any attribute access from a non-UI thread is recorded as a violation."""

    def __init__(self, ui_thread_ident: int, violations: list[str], name: str) -> None:
        self._ui_thread_ident = ui_thread_ident
        self._violations = violations
        self._name = name

    def __getattr__(self, item: str):
        if threading.get_ident() != self._ui_thread_ident:
            self._violations.append(f"{self._name}.{item}")

        def _call(*_args, **_kwargs):
            if threading.get_ident() != self._ui_thread_ident:
                self._violations.append(f"{self._name}.{item}()")
            return None

        return _call


def _panel(violations: list[str], scheduled: list, *, results=None, raises=None):
    ui_ident = threading.get_ident()

    def after(delay, callback):
        if threading.get_ident() != ui_ident:
            violations.append("after()")
        scheduled.append((delay, callback))
        return f"id-{len(scheduled)}"

    def after_cancel(poller_id):
        if threading.get_ident() != ui_ident:
            violations.append("after_cancel()")

    def upload_files(files, *, target_bucket, delete_local_on_success, progress_callback):
        for index, path in enumerate(files):
            progress_callback(
                SimpleNamespace(
                    result=SimpleNamespace(source_path=path, processing_status="ok"),
                    current_index=index,
                    total_files=len(files),
                    processed_count=index + 1,
                    status_text="Subiendo",
                )
            )
        if raises is not None:
            raise raises
        return results or []

    panel = SimpleNamespace(
        _uploader_service=SimpleNamespace(upload_files=upload_files),
        _progress_lock=threading.Lock(),
        _progress_callbacks_received=0,
        _pending_progress=None,
        _pending_result_updates={},
        _pending_file_statuses={},
        _pending_force_immediate=False,
        _progress_update_scheduled=False,
        _terminal_event=None,
        _ui_poller_id=None,
        _panel_closed=False,
        _is_running=True,
        _last_ui_update_at=0.0,
        _ui_update_interval_ms=300,
        _UI_POLL_INTERVAL_MS=10,
        after=after,
        after_cancel=after_cancel,
        winfo_exists=lambda: True,
        # Any of these touched off the UI thread is a bug:
        status_label=_TkTripwire(ui_ident, violations, "status_label"),
        progress_bar=_TkTripwire(ui_ident, violations, "progress_bar"),
        progress_label=_TkTripwire(ui_ident, violations, "progress_label"),
        result_panel=_TkTripwire(ui_ident, violations, "result_panel"),
        file_list_panel=_TkTripwire(ui_ident, violations, "file_list_panel"),
        delete_local_checkbox=_TkTripwire(ui_ident, violations, "delete_local_checkbox"),
    )
    panel._start_ui_poller = lambda: UploaderPanel._start_ui_poller(panel)
    panel._stop_ui_poller = lambda: UploaderPanel._stop_ui_poller(panel)
    panel._drain_pending_progress = lambda: UploaderPanel._drain_pending_progress(panel)
    panel._publish_terminal_event = lambda kind, payload: UploaderPanel._publish_terminal_event(
        panel, kind, payload
    )
    panel._schedule_progress_update = lambda progress: UploaderPanel._schedule_progress_update(
        panel, progress
    )
    panel._poll_upload_events = lambda: UploaderPanel._poll_upload_events(panel)
    panel._apply_progress_update = lambda progress, **kw: applied.append((progress, kw))
    return panel


applied: list = []


def test_worker_thread_never_calls_a_tk_method() -> None:
    applied.clear()
    violations: list[str] = []
    scheduled: list = []
    finished: list = []
    panel = _panel(violations, scheduled, results=["r1", "r2"])
    panel._finish_upload = finished.append
    panel._handle_unexpected_error = lambda exc: finished.append(exc)

    worker = threading.Thread(
        target=UploaderPanel._run_upload, args=(panel, ["a.jpg", "b.jpg"], False, "photo-pool")
    )
    worker.start()
    worker.join(timeout=5)
    assert not worker.is_alive()

    assert violations == [], f"the worker touched Tk: {violations}"
    assert scheduled == [], "the worker must not schedule anything through after()"
    assert panel._progress_callbacks_received == 2
    assert panel._terminal_event == ("done", ["r1", "r2"])


def test_worker_error_is_delivered_through_the_buffer_not_through_after() -> None:
    applied.clear()
    violations: list[str] = []
    scheduled: list = []
    boom = RuntimeError("fallo offline")
    panel = _panel(violations, scheduled, raises=boom)
    handled: list = []
    panel._finish_upload = handled.append
    panel._handle_unexpected_error = lambda exc: handled.append(("error", exc))

    worker = threading.Thread(
        target=UploaderPanel._run_upload, args=(panel, ["a.jpg"], False, "photo-pool")
    )
    worker.start()
    worker.join(timeout=5)

    assert violations == []
    assert scheduled == []
    assert panel._terminal_event == ("error", boom)

    # The UI thread picks it up on its next tick.
    UploaderPanel._poll_upload_events(panel)
    assert handled == [("error", boom)]


def test_ui_poller_applies_progress_and_then_the_terminal_event() -> None:
    applied.clear()
    violations: list[str] = []
    scheduled: list = []
    panel = _panel(violations, scheduled, results=["r1"])
    finished: list = []
    panel._finish_upload = finished.append
    panel._handle_unexpected_error = lambda exc: finished.append(exc)

    worker = threading.Thread(target=UploaderPanel._run_upload, args=(panel, ["a.jpg"], False, "photo-pool"))
    worker.start()
    worker.join(timeout=5)

    UploaderPanel._poll_upload_events(panel)

    assert len(applied) == 1, "the buffered progress must reach the UI"
    progress, kwargs = applied[0]
    assert kwargs["result_updates"][0].source_path == "a.jpg"
    assert finished == [["r1"]]
    assert violations == []


def test_progress_updates_keep_their_order() -> None:
    applied.clear()
    violations: list[str] = []
    scheduled: list = []
    panel = _panel(violations, scheduled, results=[])
    panel._finish_upload = lambda _r: None
    panel._handle_unexpected_error = lambda _e: None

    files = [f"f{index}.jpg" for index in range(10)]
    worker = threading.Thread(target=UploaderPanel._run_upload, args=(panel, files, False, "photo-pool"))
    worker.start()
    worker.join(timeout=5)

    UploaderPanel._poll_upload_events(panel)

    _progress, kwargs = applied[0]
    assert [item.source_path for item in kwargs["result_updates"]] == files


def test_poller_stops_when_the_panel_is_closed_mid_upload() -> None:
    applied.clear()
    violations: list[str] = []
    scheduled: list = []
    panel = _panel(violations, scheduled)
    panel._finish_upload = lambda _r: None
    panel._handle_unexpected_error = lambda _e: None
    panel.winfo_exists = lambda: False

    UploaderPanel._poll_upload_events(panel)

    assert panel._panel_closed is True
    assert applied == [], "no widget work after the panel is gone"
    assert scheduled == [], "the poller must not reschedule itself"


def test_poller_reschedules_itself_while_the_upload_runs() -> None:
    applied.clear()
    violations: list[str] = []
    scheduled: list = []
    panel = _panel(violations, scheduled)
    panel._finish_upload = lambda _r: None
    panel._handle_unexpected_error = lambda _e: None

    UploaderPanel._poll_upload_events(panel)

    assert len(scheduled) == 1
    assert scheduled[0][0] == panel._UI_POLL_INTERVAL_MS


def test_progress_is_coalesced_within_the_update_window() -> None:
    applied.clear()
    violations: list[str] = []
    scheduled: list = []
    panel = _panel(violations, scheduled)
    import time as _time

    panel._last_ui_update_at = _time.monotonic()  # inside the throttle window

    for index in range(5):
        UploaderPanel._schedule_progress_update(
            panel,
            SimpleNamespace(
                result=SimpleNamespace(source_path=f"f{index}.jpg", processing_status="ok"),
                current_index=index + 1,
                total_files=100,
                processed_count=index + 1,
                status_text="Subiendo",
            ),
        )
    UploaderPanel._drain_pending_progress(panel)

    assert applied == [], "five callbacks inside the window must not repaint five times"
    assert panel._progress_callbacks_received == 5
