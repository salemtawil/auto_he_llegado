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
from pathlib import Path
from typing import Callable


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


def normalize_relpath(value: str | Path) -> str:
    return str(value).replace("\\", "/").lstrip("./")


def is_protected_path(relative_path: str) -> bool:
    normalized = normalize_relpath(relative_path)
    for pattern in PROTECTED_PATH_PATTERNS:
        current = normalize_relpath(pattern)
        if "*" in current or "?" in current:
            if fnmatch.fnmatch(normalized, current) or fnmatch.fnmatch(Path(normalized).name, current):
                return True
            continue
        if current.endswith("/"):
            prefix = current.rstrip("/") + "/"
            if normalized.startswith(prefix):
                return True
            continue
        if normalized == current:
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


def build_restart_command(app_path: Path) -> list[str]:
    if sys.platform == "darwin" and app_path.suffix.lower() == ".app":
        return ["open", str(app_path)]
    if app_path.suffix.lower() == ".py":
        return [sys.executable, str(app_path)]
    return [str(app_path)]


def apply_staged_update(
    *,
    install_dir: Path,
    package_dir: Path | None = None,
    package_zip: Path | None = None,
    app_exe: str,
    wait_pid: int | None = None,
    restart: bool = False,
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
        package_source = extract_package_zip(package_zip.resolve(), updates_root / "staging")
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
            target_path = install_dir / relative_path
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
            target_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(backup_path, target_path)
            restored.add(target_path)
        result = ApplyHelperResult(
            applied=False,
            backup_dir=backup_dir,
            log_path=log_path,
            rolled_back=True,
            restarted=False,
            warnings=warnings,
            error=str(exc),
        )
        _write_log(log_path, result, install_dir, package_source)
        return result

    restarted = False
    if restart:
        app_path = Path(app_exe)
        if not app_path.is_absolute():
            app_path = install_dir / app_path
        starter(build_restart_command(app_path), cwd=str(install_dir))
        restarted = True

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
    )
    if result.applied:
        return 0
    print(result.error or "No se pudo aplicar la actualizacion.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
