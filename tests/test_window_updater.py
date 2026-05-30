from __future__ import annotations

import json
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


def _write_updater_layout(
    root: Path,
    *,
    owner: str | None = "salemtawil",
    repo: str | None = "auto_he_llegado",
    branch: str | None = "main",
    relative_dir: str = "updater",
    encoding: str = "utf-8",
) -> None:
    updater_dir = root / relative_dir
    updater_dir.mkdir(parents=True)
    (updater_dir / "github_sync_updater.py").write_text("# demo", encoding="utf-8")
    config = {
        "owner": owner,
        "repo": repo,
        "branch": branch,
    }
    (updater_dir / "updater_config.json").write_text(
        json.dumps(config, ensure_ascii=True),
        encoding=encoding,
    )


def test_validate_updater_ready_rejects_active_processes(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(window_module, "PROJECT_ROOT", tmp_path)
    _write_updater_layout(tmp_path)
    window = _build_window(thread=object())

    error = window._validate_updater_ready()

    assert error == "Hay procesos activos. Espera a que terminen o cancelalos antes de actualizar."


def test_validate_updater_ready_rejects_missing_script(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(window_module, "PROJECT_ROOT", tmp_path)
    (tmp_path / "updater").mkdir()
    (tmp_path / "updater" / "updater_config.json").write_text("{}", encoding="utf-8")
    window = _build_window()

    error = window._validate_updater_ready()

    assert error == "No se encontro el updater externo."


def test_validate_updater_ready_accepts_internal_updater_fallback(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(window_module, "PROJECT_ROOT", tmp_path)
    _write_updater_layout(tmp_path, relative_dir="_internal/updater")
    window = _build_window()

    error = window._validate_updater_ready()

    assert error is None


def test_validate_updater_ready_rejects_missing_config(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(window_module, "PROJECT_ROOT", tmp_path)
    (tmp_path / "updater").mkdir()
    (tmp_path / "updater" / "github_sync_updater.py").write_text("# demo", encoding="utf-8")
    window = _build_window()

    error = window._validate_updater_ready()

    assert error == "No se encontro updater/updater_config.json. Configura el updater antes de actualizar."


def test_validate_updater_ready_rejects_placeholder_owner_repo(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(window_module, "PROJECT_ROOT", tmp_path)
    _write_updater_layout(tmp_path, owner="TU_USUARIO", repo="TU_REPO")
    window = _build_window()

    error = window._validate_updater_ready()

    assert error == "El updater_config.json no esta configurado con owner/repo reales."


def test_validate_updater_ready_rejects_missing_owner_repo_or_branch(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(window_module, "PROJECT_ROOT", tmp_path)
    _write_updater_layout(tmp_path, owner="", repo="auto_he_llegado", branch=None)
    window = _build_window()

    error = window._validate_updater_ready()

    assert error == "El updater_config.json no esta configurado con owner/repo reales."


def test_is_updater_config_valid_accepts_utf8_sig_bom(tmp_path: Path) -> None:
    config_path = tmp_path / "updater_config.json"
    config_path.write_text(
        json.dumps({"owner": "demo", "repo": "repo", "branch": "main"}, ensure_ascii=True),
        encoding="utf-8-sig",
    )

    assert MainAppWindow._is_updater_config_valid(config_path) is True


def test_resolve_updater_paths_prefers_root_updater(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(window_module, "PROJECT_ROOT", tmp_path)
    _write_updater_layout(tmp_path, relative_dir="updater")
    _write_updater_layout(tmp_path, relative_dir="_internal/updater", owner="fallback", repo="fallback")
    window = _build_window()

    updater_script, updater_config = window._resolve_updater_paths()

    assert updater_script == tmp_path / "updater" / "github_sync_updater.py"
    assert updater_config == tmp_path / "updater" / "updater_config.json"


def test_resolve_updater_paths_uses_internal_fallback(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(window_module, "PROJECT_ROOT", tmp_path)
    _write_updater_layout(tmp_path, relative_dir="_internal/updater")
    window = _build_window()

    updater_script, updater_config = window._resolve_updater_paths()

    assert updater_script == tmp_path / "_internal" / "updater" / "github_sync_updater.py"
    assert updater_config == tmp_path / "_internal" / "updater" / "updater_config.json"


def test_resolve_external_updater_launch_uses_command_launcher_on_macos(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(window_module, "PROJECT_ROOT", tmp_path)
    _write_updater_layout(tmp_path)
    launcher_dir = tmp_path / "updater" / "launchers"
    launcher_dir.mkdir()
    (launcher_dir / "ActualizarApp.command").write_text("#!/bin/bash\n", encoding="utf-8")
    window = _build_window()

    command, kwargs = window._resolve_external_updater_launch(system_name="Darwin")

    assert command == ["open", str(launcher_dir / "ActualizarApp.command")]
    assert kwargs == {"cwd": str(tmp_path), "start_new_session": True}


def test_resolve_external_updater_launch_uses_bat_launcher_on_windows(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(window_module, "PROJECT_ROOT", tmp_path)
    _write_updater_layout(tmp_path)
    launcher_dir = tmp_path / "updater" / "launchers"
    launcher_dir.mkdir()
    (launcher_dir / "ActualizarApp.bat").write_text("@echo off\r\n", encoding="utf-8")
    monkeypatch.setattr(window_module.subprocess, "CREATE_NEW_CONSOLE", 16, raising=False)
    window = _build_window()

    command, kwargs = window._resolve_external_updater_launch(system_name="Windows")

    assert command == [str(launcher_dir / "ActualizarApp.bat")]
    assert kwargs == {"cwd": str(tmp_path), "creationflags": 16}


def test_resolve_external_updater_launch_falls_back_to_python_on_macos(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(window_module, "PROJECT_ROOT", tmp_path)
    _write_updater_layout(tmp_path)
    window = _build_window()

    command, kwargs = window._resolve_external_updater_launch(system_name="Darwin")

    assert command == [
        "python3",
        "updater/github_sync_updater.py",
        "--apply",
        "--config",
        "updater/updater_config.json",
    ]
    assert kwargs == {"cwd": str(tmp_path), "start_new_session": True}


def test_resolve_external_updater_launch_prefers_root_updater_on_windows(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(window_module, "PROJECT_ROOT", tmp_path)
    _write_updater_layout(tmp_path, relative_dir="updater")
    _write_updater_layout(tmp_path, relative_dir="_internal/updater")
    monkeypatch.setattr(window_module.subprocess, "CREATE_NEW_CONSOLE", 16, raising=False)
    window = _build_window()

    command, kwargs = window._resolve_external_updater_launch(system_name="Windows")

    assert command == [
        "python",
        "updater\\github_sync_updater.py",
        "--apply",
        "--config",
        "updater\\updater_config.json",
    ]
    assert kwargs == {"cwd": str(tmp_path), "creationflags": 16}


def test_resolve_external_updater_launch_uses_internal_fallback_on_windows(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(window_module, "PROJECT_ROOT", tmp_path)
    _write_updater_layout(tmp_path, relative_dir="_internal/updater")
    monkeypatch.setattr(window_module.subprocess, "CREATE_NEW_CONSOLE", 16, raising=False)
    window = _build_window()

    command, kwargs = window._resolve_external_updater_launch(system_name="Windows")

    assert command == [
        "python",
        "_internal\\updater\\github_sync_updater.py",
        "--apply",
        "--config",
        "_internal\\updater\\updater_config.json",
    ]
    assert kwargs == {"cwd": str(tmp_path), "creationflags": 16}


def test_resolve_external_updater_launch_falls_back_to_python_on_windows(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(window_module, "PROJECT_ROOT", tmp_path)
    _write_updater_layout(tmp_path)
    monkeypatch.setattr(window_module.subprocess, "CREATE_NEW_CONSOLE", 16, raising=False)
    window = _build_window()

    command, kwargs = window._resolve_external_updater_launch(system_name="Windows")

    assert command == [
        "python",
        "updater\\github_sync_updater.py",
        "--apply",
        "--config",
        "updater\\updater_config.json",
    ]
    assert kwargs == {"cwd": str(tmp_path), "creationflags": 16}


def test_resolve_external_updater_launch_uses_python3_on_linux(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(window_module, "PROJECT_ROOT", tmp_path)
    _write_updater_layout(tmp_path)
    launcher_dir = tmp_path / "updater" / "launchers"
    launcher_dir.mkdir()
    (launcher_dir / "ActualizarApp.command").write_text("#!/bin/bash\n", encoding="utf-8")
    window = _build_window()

    command, kwargs = window._resolve_external_updater_launch(system_name="Linux")

    assert command == [
        "python3",
        "updater/github_sync_updater.py",
        "--apply",
        "--config",
        "updater/updater_config.json",
    ]
    assert kwargs == {"cwd": str(tmp_path), "start_new_session": True}


def test_launch_external_updater_uses_project_root_as_cwd(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(window_module, "PROJECT_ROOT", tmp_path)
    _write_updater_layout(tmp_path)
    monkeypatch.setattr(window_module.platform, "system", lambda: "Windows")
    monkeypatch.setattr(window_module.subprocess, "CREATE_NEW_CONSOLE", 16, raising=False)
    window = _build_window()
    seen: dict[str, object] = {}

    class _FakePopen:
        def __init__(self, command, **kwargs) -> None:
            seen["command"] = command
            seen["kwargs"] = kwargs

    monkeypatch.setattr(window_module.subprocess, "Popen", _FakePopen)

    ok = window._launch_external_updater()

    assert ok is True
    assert seen["command"] == [
        "python",
        "updater\\github_sync_updater.py",
        "--apply",
        "--config",
        "updater\\updater_config.json",
    ]
    assert seen["kwargs"] == {"cwd": str(tmp_path), "creationflags": 16}


def test_launch_external_updater_shows_error_and_does_not_close_when_popen_fails(monkeypatch) -> None:
    window = _build_window()
    errors: list[str] = []

    def _raise_popen(*args, **kwargs):
        raise OSError("boom")

    window._resolve_external_updater_launch = lambda system_name=None: (  # type: ignore[method-assign]  # noqa: SLF001
        ["python3", "updater/github_sync_updater.py"],
        {"cwd": "D:/demo"},
    )
    monkeypatch.setattr(window_module.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(window_module.subprocess, "Popen", _raise_popen)
    monkeypatch.setattr(window_module.messagebox, "showerror", lambda _title, message, parent=None: errors.append(message))

    ok = window._launch_external_updater()

    assert ok is False
    assert len(errors) == 1
    assert "No se pudo iniciar el actualizador externo: boom" in errors[0]


def test_request_external_update_does_not_close_when_validation_fails(monkeypatch) -> None:
    window = _build_window()
    errors: list[str] = []
    launched: list[bool] = []
    closed: list[bool] = []

    window._validate_updater_ready = lambda: "No se encontro el updater externo."  # type: ignore[method-assign]  # noqa: SLF001
    window._launch_external_updater = lambda: launched.append(True) or True  # type: ignore[method-assign]  # noqa: SLF001
    window._handle_app_close = lambda: closed.append(True)  # type: ignore[method-assign]  # noqa: SLF001
    monkeypatch.setattr(window_module.messagebox, "showerror", lambda _title, message, parent=None: errors.append(message))

    window.request_external_update()

    assert errors == ["No se encontro el updater externo."]
    assert launched == []
    assert closed == []


def test_request_external_update_does_not_close_when_launch_fails(monkeypatch) -> None:
    window = _build_window()
    closed: list[bool] = []

    window._validate_updater_ready = lambda: None  # type: ignore[method-assign]  # noqa: SLF001
    window._launch_external_updater = lambda: False  # type: ignore[method-assign]  # noqa: SLF001
    window._handle_app_close = lambda: closed.append(True)  # type: ignore[method-assign]  # noqa: SLF001
    monkeypatch.setattr(window_module.messagebox, "askyesno", lambda *args, **kwargs: True)

    window.request_external_update()

    assert closed == []


def test_request_external_update_closes_when_launch_succeeds(monkeypatch) -> None:
    window = _build_window()
    closed: list[bool] = []
    messages: list[str] = []

    window._validate_updater_ready = lambda: None  # type: ignore[method-assign]  # noqa: SLF001
    window._launch_external_updater = lambda: True  # type: ignore[method-assign]  # noqa: SLF001
    window._handle_app_close = lambda: closed.append(True)  # type: ignore[method-assign]  # noqa: SLF001
    window._broadcast_status_message = lambda message, color=None: messages.append(message)  # type: ignore[method-assign]  # noqa: SLF001
    monkeypatch.setattr(window_module.messagebox, "askyesno", lambda *args, **kwargs: True)

    window.request_external_update()

    assert messages == ["Actualizador iniciado. Cerrando app..."]
    assert closed == [True]
