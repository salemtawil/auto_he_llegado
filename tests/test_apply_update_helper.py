from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

import updater.apply_update_helper as helper_module
from updater.apply_update_helper import apply_staged_update, build_restart_command, wait_for_process_exit


def _write_file(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_wait_for_process_exit_returns_true_when_process_ends() -> None:
    states = iter([True, True, False])
    sleeps: list[float] = []

    result = wait_for_process_exit(
        1234,
        timeout_seconds=1.0,
        process_exists=lambda _pid: next(states),
        sleep=sleeps.append,
    )

    assert result is True
    assert sleeps


def test_wait_for_process_exit_returns_false_on_timeout() -> None:
    sleeps: list[float] = []

    result = wait_for_process_exit(
        1234,
        timeout_seconds=0.05,
        process_exists=lambda _pid: True,
        sleep=sleeps.append,
    )

    assert result is False
    assert sleeps


def test_apply_staged_update_replaces_files_and_creates_backup(tmp_path: Path) -> None:
    install_dir = tmp_path / "install"
    package_dir = tmp_path / "package"
    _write_file(install_dir / "AutoHeLlegado.exe", "old-exe")
    _write_file(install_dir / "_internal" / "core.bin", "old-core")
    _write_file(package_dir / "AutoHeLlegado.exe", "new-exe")
    _write_file(package_dir / "_internal" / "core.bin", "new-core")
    _write_file(package_dir / "browser_extension" / "manifest.json", "manifest")

    result = apply_staged_update(
        install_dir=install_dir,
        package_dir=package_dir,
        app_exe="AutoHeLlegado.exe",
        now_factory=lambda: datetime(2026, 5, 30, 17, 0, 0),
    )

    assert result.applied is True
    assert (install_dir / "AutoHeLlegado.exe").read_text(encoding="utf-8") == "new-exe"
    assert (install_dir / "_internal" / "core.bin").read_text(encoding="utf-8") == "new-core"
    assert (install_dir / "browser_extension" / "manifest.json").read_text(encoding="utf-8") == "manifest"
    assert result.backup_dir is not None
    assert (result.backup_dir / "AutoHeLlegado.exe").read_text(encoding="utf-8") == "old-exe"
    assert (result.backup_dir / "_internal" / "core.bin").read_text(encoding="utf-8") == "old-core"


def test_apply_staged_update_preserves_protected_files(tmp_path: Path) -> None:
    install_dir = tmp_path / "install"
    package_dir = tmp_path / "package"
    _write_file(install_dir / ".env", "SECRET=old")
    _write_file(install_dir / "config" / "settings.json", '{"mode":"old"}')
    _write_file(install_dir / "local_data" / "data.txt", "old-local")
    _write_file(install_dir / "logs" / "app.log", "old-log")
    _write_file(install_dir / "updater" / "updater_config.json", "old-config")
    _write_file(package_dir / ".env", "SECRET=new")
    _write_file(package_dir / "config" / "settings.json", '{"mode":"new"}')
    _write_file(package_dir / "local_data" / "data.txt", "new-local")
    _write_file(package_dir / "logs" / "app.log", "new-log")
    _write_file(package_dir / "updater" / "updater_config.json", "new-config")
    _write_file(package_dir / "AutoHeLlegado.exe", "new-exe")

    result = apply_staged_update(
        install_dir=install_dir,
        package_dir=package_dir,
        app_exe="AutoHeLlegado.exe",
        now_factory=lambda: datetime(2026, 5, 30, 17, 1, 0),
    )

    assert result.applied is True
    assert (install_dir / ".env").read_text(encoding="utf-8") == "SECRET=old"
    assert (install_dir / "config" / "settings.json").read_text(encoding="utf-8") == '{"mode":"old"}'
    assert (install_dir / "local_data" / "data.txt").read_text(encoding="utf-8") == "old-local"
    assert (install_dir / "logs" / "app.log").read_text(encoding="utf-8") == "old-log"
    assert (install_dir / "updater" / "updater_config.json").read_text(encoding="utf-8") == "old-config"


def test_apply_staged_update_accepts_package_zip(tmp_path: Path) -> None:
    install_dir = tmp_path / "install"
    package_dir = tmp_path / "package"
    package_zip = tmp_path / "AutoHeLlegado_Update.zip"
    _write_file(install_dir / "AutoHeLlegado.exe", "old-exe")
    _write_file(package_dir / "AutoHeLlegado.exe", "new-exe")
    _write_file(package_dir / "_internal" / "core.bin", "new-core")

    import zipfile

    with zipfile.ZipFile(package_zip, "w") as archive:
        for file_path in package_dir.rglob("*"):
            if file_path.is_file():
                archive.write(file_path, file_path.relative_to(package_dir))

    result = apply_staged_update(
        install_dir=install_dir,
        package_zip=package_zip,
        app_exe="AutoHeLlegado.exe",
        now_factory=lambda: datetime(2026, 5, 30, 17, 1, 30),
    )

    assert result.applied is True
    assert (install_dir / "AutoHeLlegado.exe").read_text(encoding="utf-8") == "new-exe"
    assert (install_dir / "_internal" / "core.bin").read_text(encoding="utf-8") == "new-core"


def test_apply_staged_update_rolls_back_if_copy_fails(tmp_path: Path) -> None:
    install_dir = tmp_path / "install"
    package_dir = tmp_path / "package"
    _write_file(install_dir / "AutoHeLlegado.exe", "old-exe")
    _write_file(install_dir / "_internal" / "core.bin", "old-core")
    _write_file(package_dir / "AutoHeLlegado.exe", "new-exe")
    _write_file(package_dir / "_internal" / "core.bin", "new-core")
    copied_targets: list[Path] = []

    def failing_copy(source: Path, target: Path) -> None:
        copied_targets.append(target)
        if target.name == "core.bin":
            raise PermissionError("locked")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source.read_bytes())

    result = apply_staged_update(
        install_dir=install_dir,
        package_dir=package_dir,
        app_exe="AutoHeLlegado.exe",
        copy_file=failing_copy,
        now_factory=lambda: datetime(2026, 5, 30, 17, 2, 0),
    )

    assert copied_targets
    assert result.applied is False
    assert result.rolled_back is True
    assert (install_dir / "AutoHeLlegado.exe").read_text(encoding="utf-8") == "old-exe"
    assert (install_dir / "_internal" / "core.bin").read_text(encoding="utf-8") == "old-core"


def test_apply_staged_update_restarts_app_on_success(tmp_path: Path) -> None:
    install_dir = tmp_path / "install"
    package_dir = tmp_path / "package"
    _write_file(install_dir / "AutoHeLlegado.exe", "old-exe")
    _write_file(package_dir / "AutoHeLlegado.exe", "new-exe")
    popen_calls: list[tuple[list[str], dict[str, object]]] = []

    def fake_popen(command: list[str], **kwargs):
        popen_calls.append((command, kwargs))
        return object()

    result = apply_staged_update(
        install_dir=install_dir,
        package_dir=package_dir,
        app_exe="AutoHeLlegado.exe",
        restart=True,
        popen_factory=fake_popen,
        now_factory=lambda: datetime(2026, 5, 30, 17, 3, 0),
    )

    assert result.applied is True
    assert result.restarted is True
    assert popen_calls == [([str(install_dir / "AutoHeLlegado.exe")], {"cwd": str(install_dir)})]


def test_build_restart_command_uses_open_for_macos_app_bundle(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(helper_module.sys, "platform", "darwin")
    app_path = tmp_path / "AutoHeLlegado.app"

    command = build_restart_command(app_path)

    assert command == ["open", str(app_path)]


def test_apply_staged_update_restarts_macos_app_bundle_with_open(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(helper_module.sys, "platform", "darwin")
    install_dir = tmp_path / "install"
    package_dir = tmp_path / "package"
    (install_dir / "AutoHeLlegado.app").mkdir(parents=True)
    _write_file(package_dir / "AutoHeLlegado.app" / "Contents" / "Info.plist", "plist")
    popen_calls: list[tuple[list[str], dict[str, object]]] = []

    def fake_popen(command: list[str], **kwargs):
        popen_calls.append((command, kwargs))
        return object()

    result = apply_staged_update(
        install_dir=install_dir,
        package_dir=package_dir,
        app_exe="AutoHeLlegado.app",
        restart=True,
        popen_factory=fake_popen,
        now_factory=lambda: datetime(2026, 5, 30, 17, 3, 30),
    )

    assert result.applied is True
    assert result.restarted is True
    assert popen_calls == [(["open", str(install_dir / "AutoHeLlegado.app")], {"cwd": str(install_dir)})]


def test_apply_staged_update_replaces_absolute_macos_app_bundle(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(helper_module.sys, "platform", "darwin")
    install_dir = tmp_path / "Application Support" / "AutoHeLlegado"
    package_dir = tmp_path / "package"
    app_path = tmp_path / "Applications" / "AutoHeLlegado.app"
    _write_file(app_path / "Contents" / "Info.plist", "old-plist")
    _write_file(package_dir / "AutoHeLlegado.app" / "Contents" / "Info.plist", "new-plist")

    result = apply_staged_update(
        install_dir=install_dir,
        package_dir=package_dir,
        app_exe=str(app_path),
        restart=False,
        now_factory=lambda: datetime(2026, 5, 30, 17, 3, 30),
    )

    assert result.applied is True
    assert (app_path / "Contents" / "Info.plist").read_text(encoding="utf-8") == "new-plist"
    backup_file = install_dir / "updates" / "backups" / "20260530_170330" / "AutoHeLlegado.app" / "Contents" / "Info.plist"
    assert backup_file.read_text(encoding="utf-8") == "old-plist"


def test_apply_staged_update_does_not_restart_on_failure(tmp_path: Path) -> None:
    install_dir = tmp_path / "install"
    package_dir = tmp_path / "package"
    _write_file(install_dir / "AutoHeLlegado.exe", "old-exe")
    _write_file(package_dir / "AutoHeLlegado.exe", "new-exe")
    popen_calls: list[tuple[list[str], dict[str, object]]] = []

    result = apply_staged_update(
        install_dir=install_dir,
        package_dir=package_dir,
        app_exe="AutoHeLlegado.exe",
        restart=True,
        popen_factory=lambda command, **kwargs: popen_calls.append((command, kwargs)),
        copy_file=lambda _source, _target: (_ for _ in ()).throw(PermissionError("blocked")),
        now_factory=lambda: datetime(2026, 5, 30, 17, 4, 0),
    )

    assert result.applied is False
    assert result.restarted is False
    assert popen_calls == []


def test_apply_staged_update_writes_log(tmp_path: Path) -> None:
    install_dir = tmp_path / "install"
    package_dir = tmp_path / "package"
    _write_file(package_dir / "AutoHeLlegado.exe", "new-exe")

    result = apply_staged_update(
        install_dir=install_dir,
        package_dir=package_dir,
        app_exe="AutoHeLlegado.exe",
        now_factory=lambda: datetime(2026, 5, 30, 17, 5, 0),
    )

    assert result.log_path is not None
    log_text = result.log_path.read_text(encoding="utf-8")
    assert "Aplicado: si" in log_text
    assert "Restart: no" in log_text
