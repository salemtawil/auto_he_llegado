from __future__ import annotations

import argparse
import fnmatch
import os
import shutil
import subprocess
import sys
import time
import zipfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Callable


def _cargar_registro_de_revision():
    """Localiza `write_installed_revision`, y si no aparece sigue sin el.

    Este modulo corre de tres formas: congelado dentro de
    AutoHeLlegadoUpdateHelper.exe, como script suelto desde `updater/`, y como
    copia que la app deja en otro sitio para poder reemplazar el helper
    original. En alguna de ellas el import puede no resolverse.

    Si falla, NO se puede dejar que reviente: para cuando el helper arranca, la
    app ya se cerro sola. Un ImportError aqui dejaria al agente sin aplicar la
    actualizacion, sin log y sin app. Perder el registro de la revision solo
    cuesta una descarga de mas la proxima vez.
    """

    try:
        from updater.installed_revision import write_installed_revision

        return write_installed_revision
    except Exception:  # noqa: BLE001
        pass
    try:
        from installed_revision import write_installed_revision

        return write_installed_revision
    except Exception:  # noqa: BLE001
        pass

    def _sin_registro(_install_dir, _revision) -> bool:
        return False

    return _sin_registro


write_installed_revision = _cargar_registro_de_revision()


PROTECTED_PATH_PATTERNS = (
    ".env",
    "config/",
    "logs/",
    "exports/",
    "local_data/",
    "chrome_profiles/",
    "updates/backups/",
    "updates/update_logs/",
    "updater/updater_config.json",
    "*.local.json",
    # ---------------------------------------------------------------------
    # Lo que este helper NO puede reemplazar, por fisica de Windows.
    #
    # El helper congelado se ejecuta DESDE la carpeta de instalacion: la app
    # lanza `AutoHeLlegadoUpdateHelper.exe` tal cual, sin copiarlo a otro sitio
    # (ver _prepare_helper_runtime_copy, que solo copia cuando el helper es un
    # .py). Mientras corre, Windows mantiene bloqueados su propio ejecutable y
    # todo lo que carga de `_internal/`: python3XX.dll, base_library.zip,
    # MSVCP140.dll, los .pyd de psutil...
    #
    # Intentar reemplazarlos da WinError 32 a mitad de la copia, y entonces la
    # reversion intenta restaurar y choca con el mismo bloqueo. Paso de verdad
    # en la primera publicacion real (2026-10-15).
    #
    # Se saltan aqui, en el punto de aplicacion, aunque el paquete los traiga:
    # una actualizacion incompleta pero coherente es infinitamente mejor que
    # una instalacion rota. Para cambiar dependencias o el propio helper hace
    # falta un instalador completo.
    # ---------------------------------------------------------------------
    "_internal/",
    "AutoHeLlegadoUpdateHelper.exe",
)


@dataclass(slots=True)
class ApplyHelperResult:
    applied: bool
    backup_dir: Path | None
    log_path: Path
    rolled_back: bool
    restarted: bool
    warnings: list[str] = field(default_factory=list)
    error: str | None = None


class UnsafeUpdatePathError(ValueError):
    """Raised when an update package carries a path that escapes the install dir."""


def normalize_relpath(value: str | Path) -> str:
    raw = str(value).replace("\\", "/")
    if raw.startswith("//"):
        raise UnsafeUpdatePathError(f"Ruta de actualizacion no permitida: {value!r}")
    parts: list[str] = []
    for part in raw.split("/"):
        if part in ("", "."):
            continue
        if part == "..":
            raise UnsafeUpdatePathError(f"Ruta de actualizacion no permitida: {value!r}")
        parts.append(part)
    # Windows drive letters / absolute POSIX paths must never survive normalization.
    if PurePosixPath(raw).is_absolute() or (
        parts and len(parts[0]) == 2 and parts[0][1] == ":"
    ):
        raise UnsafeUpdatePathError(f"Ruta de actualizacion no permitida: {value!r}")
    normalized = "/".join(parts)
    if not normalized:
        return ""
    # Keep a trailing slash: protected patterns such as "config/" rely on it to
    # match a whole directory rather than a single file name.
    if raw.endswith("/"):
        normalized += "/"
    return normalized


def fold_relpath(value: str) -> str:
    """Case-folded form used ONLY to compare paths, never to build one.

    Windows and macOS resolve ``.ENV`` and ``.env`` to the same file, so a
    case-sensitive comparison would let ``config/Settings.json`` or ``.Env``
    slip past the protected list. ``casefold`` is used rather than ``lower``
    so non-ASCII names fold correctly too.
    """

    return value.casefold()


def is_protected_path(relative_path: str) -> bool:
    try:
        normalized = normalize_relpath(relative_path)
    except UnsafeUpdatePathError:
        # A traversal path is never safe to write: treat it as protected.
        return True
    folded = fold_relpath(normalized)
    for pattern in PROTECTED_PATH_PATTERNS:
        current = fold_relpath(normalize_relpath(pattern))
        if "*" in current or "?" in current:
            if fnmatch.fnmatchcase(folded, current) or fnmatch.fnmatchcase(
                fold_relpath(PurePosixPath(normalized).name), current
            ):
                return True
            continue
        if current.endswith("/"):
            prefix = current.rstrip("/") + "/"
            if folded.startswith(prefix):
                return True
            continue
        if folded == current:
            return True
    return False


def process_exists(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def wait_for_process_exit(
    pid: int | None,
    *,
    timeout_seconds: float = 60.0,
    process_exists: Callable[[int], bool] | None = None,
    sleep: Callable[[float], None] | None = None,
) -> bool:
    if pid is None:
        return True
    checker = process_exists or globals()["process_exists"]
    sleeper = sleep or time.sleep
    deadline = time.monotonic() + max(timeout_seconds, 0.0)
    while time.monotonic() < deadline:
        if not checker(pid):
            return True
        sleeper(0.1)
    return not checker(pid)


def extract_package_zip(package_zip: Path, target_root: Path) -> Path:
    extract_dir = target_root / f"extracted_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    extract_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(package_zip, "r") as archive:
        # SECURITY: guard against Zip Slip. extractall() honours "../" and
        # absolute member names, which would let a package write anywhere the
        # user can write (autorun locations included).
        safe_root = extract_dir.resolve()
        for member in archive.infolist():
            normalize_relpath(member.filename)
            destination = (extract_dir / member.filename).resolve()
            if destination != safe_root and safe_root not in destination.parents:
                raise UnsafeUpdatePathError(
                    f"El paquete de actualizacion contiene una ruta fuera del destino: {member.filename!r}"
                )
        archive.extractall(extract_dir)
    children = [item for item in extract_dir.iterdir()]
    if len(children) == 1 and children[0].is_dir():
        return children[0]
    return extract_dir


def copy_file(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)


def _write_log(log_path: Path, result: ApplyHelperResult, install_dir: Path, package_source: Path) -> None:
    lines = [
        f"Install dir: {install_dir}",
        f"Package source: {package_source}",
        f"Aplicado: {'si' if result.applied else 'no'}",
        f"Rollback: {'si' if result.rolled_back else 'no'}",
        f"Restart: {'si' if result.restarted else 'no'}",
        f"Backup: {result.backup_dir or 'N/A'}",
    ]
    if result.warnings:
        lines.extend(f"Warning: {warning}" for warning in result.warnings)
    if result.error:
        lines.append(f"Error: {result.error}")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _restart_app(install_dir: Path, app_exe: str, starter) -> bool:
    """Reabre la app. Devuelve si lo consiguio; nunca propaga el fallo.

    Se llama tanto tras aplicar bien como tras revertir: en los dos casos la
    instalacion esta en un estado coherente y la app deberia volver a abrirse.
    """

    app_path = Path(app_exe)
    if not app_path.is_absolute():
        app_path = install_dir / app_path
    try:
        starter(build_restart_command(app_path), cwd=str(install_dir))
    except Exception:  # noqa: BLE001
        return False
    return True


def build_restart_command(app_path: Path) -> list[str]:
    if sys.platform == "darwin" and app_path.suffix.lower() == ".app":
        return ["open", str(app_path)]
    if app_path.suffix.lower() == ".py":
        return [sys.executable, str(app_path)]
    return [str(app_path)]


def resolve_update_target_path(install_dir: Path, app_exe: str, relative_path: Path) -> Path:
    app_path = Path(app_exe)
    if not app_path.is_absolute():
        app_path = install_dir / app_path
    parts = relative_path.parts
    if (
        sys.platform == "darwin"
        and app_path.suffix.lower() == ".app"
        and parts
        and parts[0] == app_path.name
    ):
        return app_path.joinpath(*parts[1:])
    return install_dir / relative_path


def apply_staged_update(
    *,
    install_dir: Path,
    package_dir: Path | None = None,
    package_zip: Path | None = None,
    app_exe: str,
    wait_pid: int | None = None,
    restart: bool = False,
    revision: str | None = None,
    log_dir: Path | None = None,
    process_exists: Callable[[int], bool] | None = None,
    sleep: Callable[[float], None] | None = None,
    copy_file: Callable[[Path, Path], None] | None = None,
    popen_factory: Callable[..., object] | None = None,
    now_factory: Callable[[], datetime] | None = None,
) -> ApplyHelperResult:
    now = now_factory or datetime.now
    install_dir = install_dir.resolve()
    timestamp = now().strftime("%Y%m%d_%H%M%S")
    updates_root = install_dir / "updates"
    backup_dir = updates_root / "backups" / timestamp
    effective_log_dir = (log_dir or (updates_root / "update_logs")).resolve()
    log_path = effective_log_dir / f"{timestamp}_helper.log"
    copier = copy_file or globals()["copy_file"]
    starter = popen_factory or subprocess.Popen
    warnings: list[str] = []
    applied_new: list[Path] = []
    replaced_files: list[tuple[Path, Path]] = []
    package_source: Path

    if package_dir is None and package_zip is None:
        result = ApplyHelperResult(applied=False, backup_dir=None, log_path=log_path, rolled_back=False, restarted=False, error="Debe indicar --package-dir o --package-zip.")
        _write_log(log_path, result, install_dir, install_dir)
        return result

    if package_zip is not None:
        # Un zip corrupto o con rutas maliciosas no puede tumbar el helper con
        # un traceback: la app ya se cerro, y el agente se quedaria mirando una
        # ventana que no vuelve, sin log y sin explicacion.
        try:
            package_source = extract_package_zip(package_zip.resolve(), updates_root / "staging")
        except Exception as exc:  # noqa: BLE001
            result = ApplyHelperResult(
                applied=False,
                backup_dir=None,
                log_path=log_path,
                rolled_back=False,
                restarted=_restart_app(install_dir, app_exe, starter) if restart else False,
                error=f"No se pudo extraer el paquete: {exc}",
            )
            _write_log(log_path, result, install_dir, package_zip)
            return result
    else:
        package_source = package_dir.resolve()

    if not wait_for_process_exit(wait_pid, process_exists=process_exists, sleep=sleep):
        warnings.append(f"No se confirmo el cierre del PID {wait_pid}. Se intentara continuar.")

    backup_dir.mkdir(parents=True, exist_ok=True)
    try:
        source_files = sorted(path for path in package_source.rglob("*") if path.is_file())
        for source_path in source_files:
            relative_path = source_path.relative_to(package_source)
            relative_text = normalize_relpath(relative_path)
            if is_protected_path(relative_text):
                continue
            target_path = resolve_update_target_path(install_dir, app_exe, relative_path)
            if target_path.exists():
                backup_path = backup_dir / relative_path
                if not backup_path.exists():
                    backup_path.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(target_path, backup_path)
                replaced_files.append((target_path, backup_path))
            else:
                applied_new.append(target_path)
            copier(source_path, target_path)
    except Exception as exc:  # noqa: BLE001
        for target_path in reversed(applied_new):
            if target_path.exists():
                target_path.unlink()
        restored: set[Path] = set()
        for target_path, backup_path in reversed(replaced_files):
            if target_path in restored:
                continue
            # Si un archivo concreto no se puede restaurar (bloqueado, permisos),
            # se sigue con los demas: revertir a medias es malo, pero abandonar
            # la reversion en el primer tropiezo es peor. Queda anotado.
            try:
                target_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(backup_path, target_path)
            except Exception as restore_error:  # noqa: BLE001
                warnings.append(
                    f"No se pudo restaurar {target_path.name}: {restore_error}. "
                    f"Hay copia en {backup_path}."
                )
                continue
            restored.add(target_path)
        # Tras revertir, la instalacion quedo como estaba: dejar al agente con
        # la app cerrada seria peor que el propio fallo.
        result = ApplyHelperResult(
            applied=False,
            backup_dir=backup_dir,
            log_path=log_path,
            rolled_back=True,
            restarted=_restart_app(install_dir, app_exe, starter) if restart else False,
            warnings=warnings,
            error=str(exc),
        )
        _write_log(log_path, result, install_dir, package_source)
        return result

    # Solo aqui: si hubo rollback, no se llega a esta linea y el archivo
    # sigue diciendo la verdad sobre lo que hay instalado.
    if revision and not write_installed_revision(install_dir, revision):
        warnings.append("No se pudo registrar la revision instalada.")

    restarted = _restart_app(install_dir, app_exe, starter) if restart else False

    result = ApplyHelperResult(
        applied=True,
        backup_dir=backup_dir,
        log_path=log_path,
        rolled_back=False,
        restarted=restarted,
        warnings=warnings,
    )
    _write_log(log_path, result, install_dir, package_source)
    return result


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Aplica una actualizacion staged para Auto He Llegado.")
    parser.add_argument("--install-dir", required=True)
    parser.add_argument("--package-dir", default=None)
    parser.add_argument("--package-zip", default=None)
    parser.add_argument("--app-exe", required=True)
    parser.add_argument("--wait-pid", type=int, default=None)
    parser.add_argument("--restart", action="store_true")
    parser.add_argument("--log-dir", default=None)
    parser.add_argument("--revision", default=None)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    result = apply_staged_update(
        install_dir=Path(args.install_dir),
        package_dir=Path(args.package_dir) if args.package_dir else None,
        package_zip=Path(args.package_zip) if args.package_zip else None,
        app_exe=args.app_exe,
        wait_pid=args.wait_pid,
        restart=args.restart,
        log_dir=Path(args.log_dir) if args.log_dir else None,
        revision=args.revision,
    )
    if result.applied:
        return 0
    print(result.error or "No se pudo aplicar la actualizacion.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
