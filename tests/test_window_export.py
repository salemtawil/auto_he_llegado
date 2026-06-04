from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from ui.main_app.window import MainAppWindow, ProcessSlotRuntime


class _FakeFormPanel:
    def get_form_data(self) -> dict[str, str]:
        return {"page_name": "Paripe"}


class _FakePanel:
    def __init__(self) -> None:
        self.form_panel = _FakeFormPanel()


class _NoSummaryPanel:
    def __init__(self) -> None:
        self.form_panel = _FakeFormPanel()
        self.status_panel = SimpleNamespace(set_message=lambda *args, **kwargs: None)
        self.run_button = SimpleNamespace(configure=lambda **kwargs: None)
        self.clear_button = SimpleNamespace(configure=lambda **kwargs: None)


class _SetSummaryPanel(_NoSummaryPanel):
    def __init__(self) -> None:
        super().__init__()
        self.summary_updates: list[str] = []

    def set_summary(self, text: str) -> None:
        self.summary_updates.append(text)


class _FakePage:
    url = "https://paripe.io/app"

    def locator(self, _selector: str):
        first = SimpleNamespace(inner_text=lambda timeout=700: "texto body")
        return SimpleNamespace(first=first)


class _FakeSession:
    def __init__(self) -> None:
        self.page = _FakePage()

    def capture_extension_debug(self, *, page, note: str):
        return {
            "note": note,
            "frame_debug_report": {"total_frames": 1, "frames": [{"frame_url": "cached-frame"}]},
        }

    def get_last_extension_debug(self):
        return {
            "note": "cached",
            "frame_debug_report": {"total_frames": 1, "frames": [{"frame_url": "cached-frame"}]},
        }

    def debug_list_all_frames(self, *, page):
        raise RuntimeError("Cannot switch to a different thread")


class _FakeTileLabel:
    def __init__(self, text: str = "") -> None:
        self.text = text

    def configure(self, *, text: str) -> None:
        self.text = text


class _FakeTile:
    def __init__(self, text: str = "", icon: str = "") -> None:
        self._icon_label = _FakeTileLabel(icon)
        self._text_label = _FakeTileLabel(text)


class _FakeThemeMenu:
    def __init__(self) -> None:
        self.value = None

    def set(self, value: str) -> None:
        self.value = value


class _FakeSettingsDialog:
    def __init__(self) -> None:
        self.theme_menu = _FakeThemeMenu()
        self.sync_calls = 0

    def winfo_exists(self) -> bool:
        return True

    def _sync_save_button_state(self) -> None:
        self.sync_calls += 1


class _FakeThemeConfig:
    def __init__(self, theme_mode: str) -> None:
        self.theme_mode = theme_mode

    def model_copy(self, *, update: dict) -> "_FakeThemeConfig":
        return _FakeThemeConfig(update["theme_mode"])


def test_window_export_keeps_process_debug_when_frame_debug_fails(monkeypatch, tmp_path) -> None:
    written: dict[str, object] = {}
    slot = ProcessSlotRuntime(slot_id="slot_1", panel=_FakePanel(), process_id=None, last_process_id="proc-1")
    slot.last_process_debug = {
        "process_id": "proc-1",
        "page_name": "Paripe",
        "slot_id": "slot_1",
        "flow_state_detector": {"last_state": "FINAL_RESULT"},
        "timeline": [{"event": "flow_detector_state"}],
        "run_stats_timeline": [{"event": "process_finished"}],
        "run_stats_summary_text": "Resumen tiempos: demo",
        "timing_summary_text": "Resumen tiempos: local",
        "last_final_button_candidate": {"text": "He llegado"},
    }

    window = MainAppWindow.__new__(MainAppWindow)
    window._is_closing = False  # noqa: SLF001
    window._latest_debug_slot_id = "slot_1"  # noqa: SLF001
    window._current_config = SimpleNamespace(flow_engine="extension")  # noqa: SLF001
    window._slots = {"slot_1": slot}  # noqa: SLF001
    window._get_slot = lambda slot_id: slot  # type: ignore[method-assign]  # noqa: SLF001
    window._set_slot_status = lambda *args, **kwargs: None  # type: ignore[method-assign]  # noqa: SLF001
    window._process_service = SimpleNamespace(  # noqa: SLF001
        get_process_debug_export=lambda process_id, slot_id=None: dict(slot.last_process_debug or {})
    )

    target = tmp_path / "export.json"
    monkeypatch.setattr("ui.main_app.window.filedialog.asksaveasfilename", lambda **kwargs: str(target))
    monkeypatch.setattr("ui.main_app.window.BrowserManager.get_latest_session", classmethod(lambda cls: _FakeSession()))
    monkeypatch.setattr("ui.main_app.window.BrowserManager.get_latest_extension_debug", classmethod(lambda cls: {}))

    window.export_extension_state("slot_1")

    payload = json.loads(Path(target).read_text(encoding="utf-8"))

    assert payload["process_debug"]["flow_state_detector"]["last_state"] == "FINAL_RESULT"
    assert payload["process_debug"]["run_stats_timeline"] == [{"event": "process_finished"}]
    assert payload["process_debug"]["run_stats_summary_text"] == "Resumen tiempos: demo"
    assert payload["timeline"] == [{"event": "flow_detector_state"}]
    assert payload["last_final_button_candidate"] == {"text": "He llegado"}
    assert payload["frames"]["frames"][0]["frame_url"] == "cached-frame"
    assert payload["browser_export_warning"] == "Cannot switch to a different thread"


def test_set_slot_summary_uses_panel_method_when_summary_label_missing() -> None:
    panel = _SetSummaryPanel()
    slot = ProcessSlotRuntime(slot_id="slot_1", panel=panel)
    window = MainAppWindow.__new__(MainAppWindow)
    window._slots = {"slot_1": slot}  # noqa: SLF001
    window._active_slot_id = "slot_1"  # noqa: SLF001
    refreshed: list[str] = []
    window._refresh_header_summary = lambda: refreshed.append("ok")  # type: ignore[method-assign]  # noqa: SLF001

    window._set_slot_summary("slot_1", "resumen corto")

    assert panel.summary_updates == ["resumen corto"]
    assert refreshed == ["ok"]


def test_broadcast_status_message_does_not_fail_without_summary_label() -> None:
    panel = _NoSummaryPanel()
    slot = ProcessSlotRuntime(slot_id="slot_1", panel=panel)
    window = MainAppWindow.__new__(MainAppWindow)
    window._slots = {"slot_1": slot}  # noqa: SLF001
    window._active_slot_id = "slot_1"  # noqa: SLF001
    window._refresh_header_summary = lambda: None  # type: ignore[method-assign]  # noqa: SLF001

    window._broadcast_status_message("mensaje")


def test_save_local_config_does_not_break_when_panel_lacks_summary_label() -> None:
    panel = _NoSummaryPanel()
    slot = ProcessSlotRuntime(slot_id="slot_1", panel=panel)
    window = MainAppWindow.__new__(MainAppWindow)
    window._slots = {"slot_1": slot}  # noqa: SLF001
    window._active_slot_id = "slot_1"  # noqa: SLF001
    window._refresh_header_summary = lambda: None  # type: ignore[method-assign]  # noqa: SLF001
    window._settings_dialog = None  # noqa: SLF001
    window._persist_local_config = lambda config: None  # type: ignore[method-assign]  # noqa: SLF001
    window._extract_local_config = lambda data=None: {"demo": "ok"}  # type: ignore[method-assign]  # noqa: SLF001

    window.save_local_config({})


def test_handle_app_close_continues_when_status_broadcast_fails(monkeypatch) -> None:
    panel = _NoSummaryPanel()
    slot = ProcessSlotRuntime(slot_id="slot_1", panel=panel)
    window = MainAppWindow.__new__(MainAppWindow)
    window._is_closing = False  # noqa: SLF001
    window._slots = {"slot_1": slot}  # noqa: SLF001
    window._stop_process_timer = lambda *args, **kwargs: None  # type: ignore[method-assign]  # noqa: SLF001
    window._broadcast_status_message = lambda *args, **kwargs: (_ for _ in ()).throw(AttributeError("missing summary"))  # type: ignore[method-assign]  # noqa: SLF001

    started: list[bool] = []

    class _FakeThread:
        def __init__(self, target=None, daemon=None):
            self.target = target
            self.daemon = daemon

        def start(self):
            started.append(True)

    monkeypatch.setattr("ui.main_app.window.threading.Thread", _FakeThread)

    window._handle_app_close()

    assert window._is_closing is True  # noqa: SLF001
    assert started == [True]


def test_sync_theme_toggle_button_updates_header_label_for_light_and_dark() -> None:
    window = MainAppWindow.__new__(MainAppWindow)
    window.theme_toggle_button = _FakeTile("Inicial")  # noqa: SLF001
    window._settings_dialog = None  # noqa: SLF001
    window._current_config = SimpleNamespace(theme_mode="light")  # noqa: SLF001

    window._sync_theme_toggle_button()

    assert window.theme_toggle_button._text_label.text == "Claro"  # noqa: SLF001
    assert window.theme_toggle_button._icon_label.text == "☼"  # noqa: SLF001

    window._current_config = SimpleNamespace(theme_mode="dark")  # noqa: SLF001
    window._sync_theme_toggle_button()

    assert window.theme_toggle_button._text_label.text == "Oscuro"  # noqa: SLF001
    assert window.theme_toggle_button._icon_label.text == "◐"  # noqa: SLF001


def test_toggle_theme_mode_persists_next_theme_without_refresh_or_messages(monkeypatch) -> None:
    window = MainAppWindow.__new__(MainAppWindow)
    window._current_config = _FakeThemeConfig("light")  # noqa: SLF001
    window._settings_dialog = None  # noqa: SLF001
    persisted = []
    refresh_calls = []
    messages = []
    theme_syncs = []
    repaint_calls = []
    window._config_service = SimpleNamespace(save=lambda config: persisted.append(config) or config)  # noqa: SLF001
    window.refresh_extension_status = lambda: refresh_calls.append("refresh")  # type: ignore[method-assign]  # noqa: SLF001
    window._broadcast_status_message = lambda message, color=None: messages.append((message, color))  # type: ignore[method-assign]  # noqa: SLF001
    window._sync_theme_toggle_button = lambda: theme_syncs.append(window._current_config.theme_mode)  # type: ignore[method-assign]  # noqa: SLF001
    window._refresh_theme_widgets = lambda: repaint_calls.append(window._current_config.theme_mode)  # type: ignore[method-assign]  # noqa: SLF001
    monkeypatch.setattr("ui.main_app.window.apply_theme_mode", lambda mode: mode)

    window.toggle_theme_mode()

    assert persisted[0].theme_mode == "dark"
    assert window._current_config.theme_mode == "dark"  # noqa: SLF001
    assert refresh_calls == []
    assert messages == []
    assert theme_syncs == ["dark", "dark"]
    assert repaint_calls == ["dark"]


def test_sync_theme_toggle_button_updates_open_settings_dialog_theme_menu() -> None:
    window = MainAppWindow.__new__(MainAppWindow)
    window.theme_toggle_button = _FakeTile("Inicial")  # noqa: SLF001
    window._current_config = SimpleNamespace(theme_mode="dark")  # noqa: SLF001
    window._settings_dialog = _FakeSettingsDialog()  # noqa: SLF001

    window._sync_theme_toggle_button()

    assert window.theme_toggle_button._text_label.text == "Oscuro"  # noqa: SLF001
    assert window.theme_toggle_button._icon_label.text == "◐"  # noqa: SLF001
    assert window._settings_dialog.theme_menu.value == "dark"  # noqa: SLF001
    assert window._settings_dialog.sync_calls == 1  # noqa: SLF001
