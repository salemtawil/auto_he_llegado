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
    _write_file(install_dir / "browser_extension" / "content.js", "old-content")
    _write_file(package_dir / "AutoHeLlegado.exe", "new-exe")
    _write_file(package_dir / "browser_extension" / "content.js", "new-content")
    _write_file(package_dir / "browser_extension" / "manifest.json", "manifest")

    result = apply_staged_update(
        install_dir=install_dir,
        package_dir=package_dir,
        app_exe="AutoHeLlegado.exe",
        now_factory=lambda: datetime(2026, 5, 30, 17, 0, 0),
    )

    assert result.applied is True
    assert (install_dir / "AutoHeLlegado.exe").read_text(encoding="utf-8") == "new-exe"
    assert (install_dir / "browser_extension" / "content.js").read_text(encoding="utf-8") == "new-content"
    assert (install_dir / "browser_extension" / "manifest.json").read_text(encoding="utf-8") == "manifest"
    assert result.backup_dir is not None
    assert (result.backup_dir / "AutoHeLlegado.exe").read_text(encoding="utf-8") == "old-exe"
    assert (result.backup_dir / "browser_extension" / "content.js").read_text(encoding="utf-8") == "old-content"


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
    _write_file(package_dir / "browser_extension" / "content.js", "new-content")

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
    assert (install_dir / "browser_extension" / "content.js").read_text(encoding="utf-8") == "new-content"


def test_apply_staged_update_rolls_back_if_copy_fails(tmp_path: Path) -> None:
    install_dir = tmp_path / "install"
    package_dir = tmp_path / "package"
    _write_file(install_dir / "AutoHeLlegado.exe", "old-exe")
    _write_file(install_dir / "browser_extension" / "content.js", "old-content")
    _write_file(package_dir / "AutoHeLlegado.exe", "new-exe")
    _write_file(package_dir / "browser_extension" / "content.js", "new-content")
    copied_targets: list[Path] = []

    def failing_copy(source: Path, target: Path) -> None:
        copied_targets.append(target)
        if target.name == "content.js":
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
    assert (install_dir / "browser_extension" / "content.js").read_text(encoding="utf-8") == "old-content"


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


def test_apply_staged_update_restarts_after_rollback(tmp_path: Path) -> None:
    """Cambio deliberado (2026-10-16): tras revertir, la app SI se relanza.

    Antes no se relanzaba. Pero la app se cierra sola antes de lanzar el helper,
    y una reversion deja la instalacion exactamente como estaba: no reabrirla
    dejaba al agente con la ventana cerrada, sin app y sin ningun aviso.
    """
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
    assert result.rolled_back is True
    assert result.restarted is True
    assert len(popen_calls) == 1, "la instalacion quedo intacta: hay que reabrirla"
    assert (install_dir / "AutoHeLlegado.exe").read_text(encoding="utf-8") == "old-exe"


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


# ---------------------------------------------------------------------------
# Re-firma del bundle en macOS.
#
# El build firma AutoHeLlegado.app con ad-hoc codesign y lo verifica con
# --deep --strict. Al reemplazar archivos dentro del bundle el sello se rompe y
# en Apple Silicon la app deja de abrir. Estas pruebas fijan QUE se vuelve a
# firmar y, sobre todo, que se firma ANTES de reiniciar.
#
# Lo que estas pruebas NO demuestran: que codesign haga su trabajo en un Mac
# real. Eso necesita un Mac. Aqui se verifica la logica que lo invoca.
# ---------------------------------------------------------------------------


def _como_mac(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(helper_module.sys, "platform", "darwin")


def test_resolve_app_bundle_devuelve_none_fuera_de_mac(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(helper_module.sys, "platform", "win32")

    assert helper_module.resolve_app_bundle(Path("C:/inst"), "AutoHeLlegado.app") is None


def test_resolve_app_bundle_ignora_lo_que_no_es_bundle(monkeypatch: pytest.MonkeyPatch) -> None:
    _como_mac(monkeypatch)

    assert helper_module.resolve_app_bundle(Path("/inst"), "AutoHeLlegado.exe") is None
    assert helper_module.resolve_app_bundle(Path("/inst"), "app_main.py") is None


def test_resolve_app_bundle_resuelve_ruta_relativa(monkeypatch: pytest.MonkeyPatch) -> None:
    _como_mac(monkeypatch)

    assert helper_module.resolve_app_bundle(Path("/inst"), "AutoHeLlegado.app") == Path(
        "/inst/AutoHeLlegado.app"
    )


def test_build_resign_command_usa_el_mismo_comando_que_el_build() -> None:
    # Si esto cambia, tiene que cambiar tambien build_installer_macos.sh.
    assert helper_module.build_resign_command(Path("/Applications/AutoHeLlegado.app")) == [
        "codesign",
        "--force",
        "--deep",
        "--sign",
        "-",
        "/Applications/AutoHeLlegado.app",
    ]


def test_resign_no_invoca_codesign_fuera_de_mac(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(helper_module.sys, "platform", "win32")
    llamadas: list[list[str]] = []

    ok, error = helper_module.resign_app_bundle(
        Path("C:/inst"), "AutoHeLlegado.exe", runner=lambda cmd: llamadas.append(cmd) or 0
    )

    assert (ok, error) == (True, None)
    assert llamadas == []


def test_resign_reporta_fallo_sin_lanzar(monkeypatch: pytest.MonkeyPatch) -> None:
    _como_mac(monkeypatch)

    ok, error = helper_module.resign_app_bundle(
        Path("/inst"), "AutoHeLlegado.app", runner=lambda _cmd: 1
    )

    assert ok is False
    assert error is not None and "codesign" in error


def test_resign_aguanta_que_codesign_ni_exista(monkeypatch: pytest.MonkeyPatch) -> None:
    _como_mac(monkeypatch)

    def _revienta(_cmd: list[str]) -> int:
        raise FileNotFoundError("codesign")

    ok, error = helper_module.resign_app_bundle(
        Path("/inst"), "AutoHeLlegado.app", runner=_revienta
    )

    assert ok is False
    assert error is not None and "codesign" in error


def test_al_aplicar_en_mac_se_firma_antes_de_reiniciar(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _como_mac(monkeypatch)
    install_dir = tmp_path / "Applications"
    package_dir = tmp_path / "package"
    _write_file(install_dir / "AutoHeLlegado.app" / "Contents" / "MacOS" / "cli.py", "viejo")
    _write_file(package_dir / "AutoHeLlegado.app" / "Contents" / "MacOS" / "cli.py", "nuevo")

    orden: list[str] = []

    def _firmar(cmd: list[str]) -> int:
        orden.append(f"firma:{cmd[0]}")
        return 0

    def _lanzar(cmd, cwd=None):  # noqa: ANN001, ARG001
        orden.append("reinicio")
        return object()

    result = apply_staged_update(
        install_dir=install_dir,
        package_dir=package_dir,
        app_exe="AutoHeLlegado.app",
        restart=True,
        resign_runner=_firmar,
        popen_factory=_lanzar,
        now_factory=lambda: datetime(2026, 10, 16, 12, 0, 0),
    )

    assert result.applied is True
    assert result.warnings == []
    # El orden es lo que importa: firmar despues de reiniciar no sirve de nada.
    assert orden == ["firma:codesign", "reinicio"]
    bundle_file = install_dir / "AutoHeLlegado.app" / "Contents" / "MacOS" / "cli.py"
    assert bundle_file.read_text(encoding="utf-8") == "nuevo"


def test_al_revertir_en_mac_tambien_se_firma_antes_de_reiniciar(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _como_mac(monkeypatch)
    install_dir = tmp_path / "Applications"
    package_dir = tmp_path / "package"
    _write_file(install_dir / "AutoHeLlegado.app" / "Contents" / "MacOS" / "uno.py", "viejo-uno")
    _write_file(package_dir / "AutoHeLlegado.app" / "Contents" / "MacOS" / "uno.py", "nuevo-uno")
    _write_file(package_dir / "AutoHeLlegado.app" / "Contents" / "MacOS" / "dos.py", "nuevo-dos")

    orden: list[str] = []
    copiados: list[Path] = []

    def _copiar_fallando(source: Path, target: Path) -> None:
        copiados.append(target)
        if len(copiados) == 2:
            raise PermissionError("Operation not permitted")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source.read_bytes())

    result = apply_staged_update(
        install_dir=install_dir,
        package_dir=package_dir,
        app_exe="AutoHeLlegado.app",
        restart=True,
        copy_file=_copiar_fallando,
        resign_runner=lambda _cmd: orden.append("firma") or 0,
        popen_factory=lambda cmd, cwd=None: orden.append("reinicio") or object(),  # noqa: ARG005
        now_factory=lambda: datetime(2026, 10, 16, 12, 0, 0),
    )

    assert result.applied is False
    assert result.rolled_back is True
    # La reversion escribe dentro del bundle: la firma tambien hay que rehacerla.
    assert orden == ["firma", "reinicio"]


def test_fallo_de_firma_queda_anotado_en_los_avisos(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _como_mac(monkeypatch)
    install_dir = tmp_path / "Applications"
    package_dir = tmp_path / "package"
    _write_file(install_dir / "AutoHeLlegado.app" / "Contents" / "MacOS" / "cli.py", "viejo")
    _write_file(package_dir / "AutoHeLlegado.app" / "Contents" / "MacOS" / "cli.py", "nuevo")

    result = apply_staged_update(
        install_dir=install_dir,
        package_dir=package_dir,
        app_exe="AutoHeLlegado.app",
        restart=False,
        resign_runner=lambda _cmd: 2,
        now_factory=lambda: datetime(2026, 10, 16, 12, 0, 0),
    )

    assert result.applied is True
    assert any("codesign" in aviso for aviso in result.warnings)
    # El log es lo unico que le queda al agente si la app no vuelve a abrir.
    assert "codesign" in result.log_path.read_text(encoding="utf-8")


def test_en_windows_no_se_llama_a_codesign(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(helper_module.sys, "platform", "win32")
    install_dir = tmp_path / "install"
    package_dir = tmp_path / "package"
    _write_file(install_dir / "ui" / "window.py", "viejo")
    _write_file(package_dir / "ui" / "window.py", "nuevo")
    llamadas: list[list[str]] = []

    result = apply_staged_update(
        install_dir=install_dir,
        package_dir=package_dir,
        app_exe="AutoHeLlegado.exe",
        restart=False,
        resign_runner=lambda cmd: llamadas.append(cmd) or 0,
        now_factory=lambda: datetime(2026, 10, 16, 12, 0, 0),
    )

    assert result.applied is True
    assert llamadas == []
