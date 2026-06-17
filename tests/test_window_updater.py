from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import ui.main_app.window as window_module
from ui.main_app.window import MainAppWindow, ProcessSlotRuntime


class _FakePanel:
    def __init__(self) -> None:
        self.run_button = SimpleNamespace(configure=lambda **kwargs: None)
        self.clear_button = SimpleNamespace(configure=lambda **kwargs: None)


def _build_window(*, thread=None) -> MainAppWindow:
    window = MainAppWindow.__new__(MainAppWindow)
    window._is_closing = False  # noqa: SLF001
    window._slots = {  # noqa: SLF001
        "slot_1": ProcessSlotRuntime(slot_id="slot_1", panel=_FakePanel(), thread=thread),
        "slot_2": ProcessSlotRuntime(slot_id="slot_2", panel=_FakePanel(), thread=None),
    }
    return window


def _write_updater_config(
    root: Path,
    *,
    owner: str | None = "salemtawil",
    repo: str | None = "auto_he_llegado",
    branch: str | None = "main",
    relative_dir: str = "updater",
    encoding: str = "utf-8",
) -> None:
    updater_dir = root / relative_dir
    updater_dir.mkdir(parents=True, exist_ok=True)
    config = {
        "owner": owner,
        "repo": repo,
        "branch": branch,
    }
    (updater_dir / "updater_config.json").write_text(
        json.dumps(config, ensure_ascii=True),
        encoding=encoding,
    )


def _write_helper_layout(root: Path, *, use_exe: bool = False, relative_dir: str = "updater") -> None:
    helper_dir = root / relative_dir
    helper_dir.mkdir(parents=True, exist_ok=True)
    if use_exe:
        (root / "AutoHeLlegadoUpdateHelper.exe").write_text("helper exe", encoding="utf-8")
        return
    (helper_dir / "apply_update_helper.py").write_text("# helper", encoding="utf-8")


def _write_staged_package(root: Path) -> Path:
    package_dir = root / "updates" / "staging" / "latest_build"
    package_dir.mkdir(parents=True)
    (package_dir / "AutoHeLlegado.exe").write_text("new exe", encoding="utf-8")
    return package_dir


def test_validate_updater_ready_rejects_active_processes(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(window_module, "PROJECT_ROOT", tmp_path)
    _write_updater_config(tmp_path)
    _write_helper_layout(tmp_path)
    _write_staged_package(tmp_path)
    window = _build_window(thread=object())

    error = window._validate_updater_ready()

    assert error == "Hay procesos activos. Espera a que terminen o cancelalos antes de actualizar."


def test_validate_updater_ready_rejects_missing_helper(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(window_module, "PROJECT_ROOT", tmp_path)
    _write_updater_config(tmp_path)
    _write_staged_package(tmp_path)
    window = _build_window()

    error = window._validate_updater_ready()

    assert error == "No se encontro el helper de actualizacion."


def test_validate_updater_ready_rejects_missing_config(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(window_module, "PROJECT_ROOT", tmp_path)
    _write_helper_layout(tmp_path)
    _write_staged_package(tmp_path)
    window = _build_window()

    error = window._validate_updater_ready()

    assert error == "No se encontro updater/updater_config.json. Configura el updater antes de actualizar."


def test_validate_updater_ready_rejects_missing_staged_package(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(window_module, "PROJECT_ROOT", tmp_path)
    _write_helper_layout(tmp_path)
    _write_updater_config(tmp_path)
    window = _build_window()

    error = window._validate_updater_ready()

    assert error == "No se encontro updates/staging/latest_build. Prepara primero el paquete de actualizacion."


def test_validate_updater_ready_accepts_internal_helper_fallback(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(window_module, "PROJECT_ROOT", tmp_path)
    _write_helper_layout(tmp_path, relative_dir="_internal/updater")
    _write_updater_config(tmp_path, relative_dir="_internal/updater")
    _write_staged_package(tmp_path)
    window = _build_window()

    error = window._validate_updater_ready()

    assert error is None


def test_is_updater_config_valid_accepts_utf8_sig_bom(tmp_path: Path) -> None:
    config_path = tmp_path / "updater_config.json"
    config_path.write_text(
        json.dumps({"owner": "demo", "repo": "repo", "branch": "main"}, ensure_ascii=True),
        encoding="utf-8-sig",
    )

    assert MainAppWindow._is_updater_config_valid(config_path) is True


def test_resolve_update_helper_source_prefers_root_exe(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(window_module, "PROJECT_ROOT", tmp_path)
    _write_helper_layout(tmp_path, use_exe=True)
    _write_helper_layout(tmp_path, relative_dir="_internal/updater")
    window = _build_window()

    helper_path = window._resolve_update_helper_source()

    assert helper_path == tmp_path / "AutoHeLlegadoUpdateHelper.exe"


def test_resolve_update_helper_source_uses_internal_script_fallback(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(window_module, "PROJECT_ROOT", tmp_path)
    _write_helper_layout(tmp_path, relative_dir="_internal/updater")
    window = _build_window()

    helper_path = window._resolve_update_helper_source()

    assert helper_path == tmp_path / "_internal" / "updater" / "apply_update_helper.py"


def test_resolve_staged_package_dir_points_to_latest_build(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(window_module, "PROJECT_ROOT", tmp_path)
    package_dir = _write_staged_package(tmp_path)
    window = _build_window()

    assert window._resolve_update_package_dir() == package_dir


def test_launch_integrated_updater_uses_helper_and_current_pid(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(window_module, "PROJECT_ROOT", tmp_path)
    _write_helper_layout(tmp_path)
    _write_updater_config(tmp_path)
    package_dir = _write_staged_package(tmp_path)
    (tmp_path / "AutoHeLlegado.exe").write_text("current exe", encoding="utf-8")
    monkeypatch.setattr(window_module.os, "getpid", lambda: 4242)
    monkeypatch.setattr(window_module.subprocess, "CREATE_NO_WINDOW", 134217728, raising=False)
    monkeypatch.setattr(window_module.subprocess, "CREATE_NEW_PROCESS_GROUP", 512, raising=False)
    window = _build_window()
    seen: dict[str, object] = {}

    monkeypatch.setattr(window, "_prepare_helper_runtime_copy", lambda path: path)  # type: ignore[method-assign]  # noqa: SLF001

    class _FakePopen:
        def __init__(self, command, **kwargs) -> None:
            seen["command"] = command
            seen["kwargs"] = kwargs

    monkeypatch.setattr(window_module.subprocess, "Popen", _FakePopen)

    ok = window._launch_integrated_updater()

    assert ok is True
    assert seen["command"] == [
        sys.executable,
        str(tmp_path / "updater" / "apply_update_helper.py"),
        "--install-dir",
        str(tmp_path),
        "--package-dir",
        str(package_dir),
        "--app-exe",
        str(tmp_path / "AutoHeLlegado.exe"),
        "--wait-pid",
        "4242",
        "--restart",
        "--log-dir",
        str(tmp_path / "updates" / "update_logs"),
    ]
    assert seen["kwargs"] == {"cwd": str(tmp_path), "creationflags": 134218240}


def test_resolve_app_executable_path_accepts_macos_app_bundle(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(window_module, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(window_module.sys, "platform", "darwin")
    (tmp_path / "AutoHeLlegado.app").mkdir()
    window = _build_window()

    app_path = window._resolve_app_executable_path()

    assert app_path == tmp_path / "AutoHeLlegado.app"


def test_launch_integrated_updater_prefers_helper_exe(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(window_module, "PROJECT_ROOT", tmp_path)
    _write_helper_layout(tmp_path, use_exe=True)
    _write_updater_config(tmp_path)
    package_dir = _write_staged_package(tmp_path)
    (tmp_path / "AutoHeLlegado.exe").write_text("current exe", encoding="utf-8")
    monkeypatch.setattr(window_module.os, "getpid", lambda: 4242)
    monkeypatch.setattr(window_module.subprocess, "CREATE_NO_WINDOW", 134217728, raising=False)
    monkeypatch.setattr(window_module.subprocess, "CREATE_NEW_PROCESS_GROUP", 512, raising=False)
    window = _build_window()
    seen: dict[str, object] = {}

    monkeypatch.setattr(window, "_prepare_helper_runtime_copy", lambda path: path)  # type: ignore[method-assign]  # noqa: SLF001

    class _FakePopen:
        def __init__(self, command, **kwargs) -> None:
            seen["command"] = command
            seen["kwargs"] = kwargs

    monkeypatch.setattr(window_module.subprocess, "Popen", _FakePopen)

    ok = window._launch_integrated_updater()

    assert ok is True
    assert seen["command"] == [
        str(tmp_path / "AutoHeLlegadoUpdateHelper.exe"),
        "--install-dir",
        str(tmp_path),
        "--package-dir",
        str(package_dir),
        "--app-exe",
        str(tmp_path / "AutoHeLlegado.exe"),
        "--wait-pid",
        "4242",
        "--restart",
        "--log-dir",
        str(tmp_path / "updates" / "update_logs"),
    ]


def test_launch_integrated_updater_shows_error_when_popen_fails(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(window_module, "PROJECT_ROOT", tmp_path)
    _write_helper_layout(tmp_path)
    _write_updater_config(tmp_path)
    _write_staged_package(tmp_path)
    (tmp_path / "AutoHeLlegado.exe").write_text("current exe", encoding="utf-8")
    window = _build_window()
    errors: list[str] = []

    monkeypatch.setattr(window, "_prepare_helper_runtime_copy", lambda path: path)  # type: ignore[method-assign]  # noqa: SLF001
    monkeypatch.setattr(window_module.messagebox, "showerror", lambda _title, message, parent=None: errors.append(message))
    monkeypatch.setattr(window_module.subprocess, "Popen", lambda *args, **kwargs: (_ for _ in ()).throw(OSError("boom")))

    ok = window._launch_integrated_updater()

    assert ok is False
    assert errors == ["No se pudo iniciar el helper de actualizacion: boom"]


def test_request_external_update_does_not_close_when_validation_fails(monkeypatch) -> None:
    window = _build_window()
    errors: list[str] = []
    closed: list[bool] = []

    window._validate_updater_ready = lambda: "No se encontro el helper de actualizacion."  # type: ignore[method-assign]  # noqa: SLF001
    window._handle_app_close = lambda: closed.append(True)  # type: ignore[method-assign]  # noqa: SLF001
    monkeypatch.setattr(window_module.messagebox, "showerror", lambda _title, message, parent=None: errors.append(message))

    window.request_external_update()

    assert errors == ["No se encontro el helper de actualizacion."]
    assert closed == []


def test_request_external_update_does_not_close_when_launch_fails(monkeypatch) -> None:
    window = _build_window()
    closed: list[bool] = []
    messages: list[str] = []

    window._validate_updater_ready = lambda: None  # type: ignore[method-assign]  # noqa: SLF001
    window._launch_integrated_updater = lambda: False  # type: ignore[method-assign]  # noqa: SLF001
    window._handle_app_close = lambda: closed.append(True)  # type: ignore[method-assign]  # noqa: SLF001
    window._broadcast_status_message = lambda message, color=None: messages.append(message)  # type: ignore[method-assign]  # noqa: SLF001
    monkeypatch.setattr(window_module.messagebox, "showerror", lambda *args, **kwargs: None)

    window.request_external_update()

    assert messages == []
    assert closed == []


def test_request_external_update_launches_helper_shows_message_and_closes(monkeypatch) -> None:
    window = _build_window()
    closed: list[bool] = []
    messages: list[str] = []

    window._validate_updater_ready = lambda: None  # type: ignore[method-assign]  # noqa: SLF001
    window._launch_integrated_updater = lambda: True  # type: ignore[method-assign]  # noqa: SLF001
    window._handle_app_close = lambda: closed.append(True)  # type: ignore[method-assign]  # noqa: SLF001
    window._broadcast_status_message = lambda message, color=None: messages.append(message)  # type: ignore[method-assign]  # noqa: SLF001
    monkeypatch.setattr(window_module.messagebox, "showerror", lambda *args, **kwargs: None)

    window.request_external_update()

    assert messages == ["Actualizando, la app se reiniciará."]
    assert closed == [True]
