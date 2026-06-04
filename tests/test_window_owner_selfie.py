from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from core.models import LocalConfig
from ui.main_app.window import MainAppWindow, ProcessSlotRuntime


class _FakeFormPanel:
    def __init__(self) -> None:
        self.data = {
            "page_name": "Compinche",
            "action_name": "He llegado",
            "phone_number": "8095551234",
            "password": "secret",
        }
        self.owner_selfie_enabled = False
        self.owner_selfie_path = None
        self.owner_selfie_updates: list[tuple[bool, str | None]] = []
        self.label_text = "Sin foto"

    def get_form_data(self) -> dict[str, str]:
        return dict(self.data)

    def get_owner_selfie_data(self) -> dict[str, object]:
        return {
            "owner_selfie_enabled": self.owner_selfie_enabled,
            "owner_selfie_path": self.owner_selfie_path,
        }

    def set_owner_selfie_state(self, *, enabled: bool, path: str | None) -> None:
        self.owner_selfie_enabled = enabled
        self.owner_selfie_path = path
        self.label_text = path.split("\\")[-1].split("/")[-1] if path else "Sin foto"
        self.owner_selfie_updates.append((enabled, path))

    def clear(self) -> None:
        return


class _FakeStatusPanel:
    def __init__(self) -> None:
        self.messages: list[tuple[str, str | None]] = []

    def set_message(self, message: str, color: str | None = None) -> None:
        self.messages.append((message, color))

    def clear_persistent_alert(self) -> None:
        return

    def clear_retry_indicator(self) -> None:
        return


class _FakePanel:
    def __init__(self) -> None:
        self.form_panel = _FakeFormPanel()
        self.status_panel = _FakeStatusPanel()
        self.run_button = SimpleNamespace(configure=lambda **kwargs: None)
        self.clear_button = SimpleNamespace(configure=lambda **kwargs: None)
        self.summary_label = SimpleNamespace(configure=lambda **kwargs: None)


def _build_window(tmp_path: Path) -> MainAppWindow:
    window = MainAppWindow.__new__(MainAppWindow)
    window._is_closing = False  # noqa: SLF001
    window._current_config = LocalConfig()  # noqa: SLF001
    window._settings = SimpleNamespace(local_data_dir=tmp_path / "local_data")  # noqa: SLF001
    window._slots = {  # noqa: SLF001
        "slot_1": ProcessSlotRuntime(slot_id="slot_1", panel=_FakePanel()),
        "slot_2": ProcessSlotRuntime(slot_id="slot_2", panel=_FakePanel()),
    }
    window._active_slot_id = "slot_1"  # noqa: SLF001
    window._layout_mode = "fixed"  # noqa: SLF001
    window._latest_debug_slot_id = "slot_1"  # noqa: SLF001
    window._process_to_slot = {}  # noqa: SLF001
    window._settings_dialog = None  # noqa: SLF001
    window._refresh_header_summary = lambda: None  # type: ignore[method-assign]  # noqa: SLF001
    window._sync_run_button_state = lambda: None  # type: ignore[method-assign]  # noqa: SLF001
    window.refresh_extension_status = lambda: None  # type: ignore[method-assign]  # noqa: SLF001
    window._sync_theme_toggle_button = lambda: None  # type: ignore[method-assign]  # noqa: SLF001
    window._layout_slots = lambda _mode: None  # type: ignore[method-assign]  # noqa: SLF001
    window._safe_after = lambda *_args, **_kwargs: None  # type: ignore[method-assign]  # noqa: SLF001
    return window


def test_select_owner_selfie_copy_creates_slot_specific_local_file(tmp_path: Path) -> None:
    source = tmp_path / "source.jpg"
    source.write_text("demo", encoding="utf-8")
    window = _build_window(tmp_path)

    copied = window._copy_owner_selfie_file("slot_1", source)  # noqa: SLF001

    assert copied == tmp_path / "local_data" / "account_selfies" / "slot_1_owner_selfie.jpg"
    assert copied.read_text(encoding="utf-8") == "demo"


def test_select_owner_selfie_rejects_invalid_extension(tmp_path: Path) -> None:
    source = tmp_path / "source.gif"
    source.write_text("demo", encoding="utf-8")
    window = _build_window(tmp_path)

    with pytest.raises(ValueError, match="Solo se permiten archivos JPG, JPEG o PNG."):
        window._copy_owner_selfie_file("slot_1", source)  # noqa: SLF001


def test_owner_selfie_slots_keep_independent_files(tmp_path: Path) -> None:
    source_1 = tmp_path / "source-1.jpg"
    source_2 = tmp_path / "source-2.png"
    source_1.write_text("slot-1", encoding="utf-8")
    source_2.write_text("slot-2", encoding="utf-8")
    window = _build_window(tmp_path)

    copied_1 = window._copy_owner_selfie_file("slot_1", source_1)  # noqa: SLF001
    copied_2 = window._copy_owner_selfie_file("slot_2", source_2)  # noqa: SLF001

    assert copied_1.name == "slot_1_owner_selfie.jpg"
    assert copied_2.name == "slot_2_owner_selfie.png"
    assert copied_1.read_text(encoding="utf-8") == "slot-1"
    assert copied_2.read_text(encoding="utf-8") == "slot-2"


def test_select_owner_selfie_replaces_previous_slot_copy(tmp_path: Path) -> None:
    first = tmp_path / "first.jpg"
    second = tmp_path / "second.png"
    first.write_text("first", encoding="utf-8")
    second.write_text("second", encoding="utf-8")
    window = _build_window(tmp_path)

    original_copy = window._copy_owner_selfie_file("slot_1", first)  # noqa: SLF001
    replacement_copy = window._copy_owner_selfie_file("slot_1", second)  # noqa: SLF001

    assert original_copy.exists() is False
    assert replacement_copy.name == "slot_1_owner_selfie.png"
    assert replacement_copy.read_text(encoding="utf-8") == "second"


def test_owner_selfie_does_not_restore_after_new_session(tmp_path: Path) -> None:
    copied = tmp_path / "local_data" / "account_selfies" / "slot_2_owner_selfie.jpg"
    copied.parent.mkdir(parents=True)
    copied.write_text("demo", encoding="utf-8")
    window = _build_window(tmp_path)
    slot_form = window._slots["slot_2"].panel.form_panel  # noqa: SLF001
    slot_form.set_owner_selfie_state(enabled=True, path=str(copied))

    new_window = _build_window(tmp_path)

    new_panel = new_window._slots["slot_2"].panel.form_panel  # noqa: SLF001
    assert new_panel.owner_selfie_enabled is False
    assert new_panel.owner_selfie_path is None
    assert new_panel.label_text == "Sin foto"


def test_remove_owner_selfie_deletes_local_copy_and_disables_state(tmp_path: Path) -> None:
    copied = tmp_path / "local_data" / "account_selfies" / "slot_1_owner_selfie.jpg"
    copied.parent.mkdir(parents=True)
    copied.write_text("demo", encoding="utf-8")
    window = _build_window(tmp_path)
    slot_form = window._slots["slot_1"].panel.form_panel  # noqa: SLF001
    slot_form.set_owner_selfie_state(enabled=True, path=str(copied))

    window._handle_owner_selfie_remove("slot_1")  # noqa: SLF001

    assert copied.exists() is False
    assert slot_form.owner_selfie_enabled is False
    assert slot_form.owner_selfie_path is None
    assert slot_form.label_text == "Sin foto"


def test_clear_form_also_clears_owner_selfie_for_slot(tmp_path: Path) -> None:
    copied = tmp_path / "local_data" / "account_selfies" / "slot_1_owner_selfie.jpg"
    copied.parent.mkdir(parents=True)
    copied.write_text("demo", encoding="utf-8")
    window = _build_window(tmp_path)
    slot_form = window._slots["slot_1"].panel.form_panel  # noqa: SLF001
    slot_form.set_owner_selfie_state(enabled=True, path=str(copied))

    window.clear_form("slot_1")

    assert copied.exists() is False
    assert slot_form.owner_selfie_enabled is False
    assert slot_form.owner_selfie_path is None
    assert slot_form.label_text == "Sin foto"


def test_remove_owner_selfie_only_affects_target_slot(tmp_path: Path) -> None:
    slot_1 = tmp_path / "local_data" / "account_selfies" / "slot_1_owner_selfie.jpg"
    slot_2 = tmp_path / "local_data" / "account_selfies" / "slot_2_owner_selfie.jpg"
    slot_1.parent.mkdir(parents=True)
    slot_1.write_text("one", encoding="utf-8")
    slot_2.write_text("two", encoding="utf-8")
    window = _build_window(tmp_path)
    window._slots["slot_1"].panel.form_panel.set_owner_selfie_state(enabled=True, path=str(slot_1))  # noqa: SLF001
    window._slots["slot_2"].panel.form_panel.set_owner_selfie_state(enabled=True, path=str(slot_2))  # noqa: SLF001

    window._handle_owner_selfie_remove("slot_1")  # noqa: SLF001

    assert slot_1.exists() is False
    assert slot_2.exists() is True
    assert window._slots["slot_2"].panel.form_panel.owner_selfie_enabled is True  # noqa: SLF001


def test_build_process_request_includes_owner_selfie_fields(tmp_path: Path) -> None:
    selfie = tmp_path / "local_data" / "account_selfies" / "slot_1_owner_selfie.jpg"
    selfie.parent.mkdir(parents=True)
    selfie.write_text("demo", encoding="utf-8")
    window = _build_window(tmp_path)
    slot_form = window._slots["slot_1"].panel.form_panel  # noqa: SLF001
    slot_form.owner_selfie_enabled = True
    slot_form.owner_selfie_path = str(selfie)

    request = window._build_process_request("slot_1", process_id="proc-1")

    assert request.slot_id == "slot_1"
    assert request.owner_selfie_enabled is True
    assert request.owner_selfie_path == str(selfie)


def test_build_process_request_rejects_enabled_owner_selfie_without_valid_file(tmp_path: Path) -> None:
    window = _build_window(tmp_path)
    slot_form = window._slots["slot_1"].panel.form_panel  # noqa: SLF001
    slot_form.owner_selfie_enabled = True
    slot_form.owner_selfie_path = str(tmp_path / "missing.jpg")

    with pytest.raises(ValueError, match="Selecciona una foto valida del titular o desactiva la opcion."):
        window._build_process_request("slot_1", process_id="proc-1")


def test_build_process_request_without_session_selfie_omits_owner_selfie_fields(tmp_path: Path) -> None:
    window = _build_window(tmp_path)

    request = window._build_process_request("slot_1", process_id="proc-1")

    assert request.owner_selfie_enabled is False
    assert request.owner_selfie_path is None
