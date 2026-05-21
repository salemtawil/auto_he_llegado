from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import shutil
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable
from urllib.request import Request, urlopen


APP_ENTRYPOINTS_DEFAULT = ["app_main.py", "app_main.exe"]
EXPECTED_DIRS = ("ui", "services", "automation")
BUILTIN_EXCLUDED_PREFIXES = (
    ".git/",
    ".venv/",
    "__pycache__/",
    "backups/",
    "updates/",
    "logs/",
    "exports/",
    "chrome_profiles/",
    "data/",
    "local_data/",
)


class UpdaterError(RuntimeError):
    pass


class ConfigError(UpdaterError):
    pass


class InstallDirError(UpdaterError):
    pass


class RemoteSyncError(UpdaterError):
    pass


@dataclass(slots=True)
class UpdaterConfig:
    owner: str
    repo: str
    branch: str
    install_dir: str = "."
    app_entrypoints: list[str] = field(default_factory=lambda: list(APP_ENTRYPOINTS_DEFAULT))
    allowed_roots: list[str] = field(default_factory=list)
    protected_paths: list[str] = field(default_factory=list)


@dataclass(slots=True)
class RemoteFile:
    path: str
    sha: str


@dataclass(slots=True)
class FileDecision:
    path: str
    status: str
    local_hash: str | None
    remote_hash: str


@dataclass(slots=True)
class CheckResult:
    repo: str
    branch: str
    install_dir: Path
    remote_allowed_count: int
    protected_ignored_count: int
    ignored_count: int
    protected_paths: list[str]
    ignored_paths: list[str]


@dataclass(slots=True)
class AnalysisResult:
    repo: str
    branch: str
    install_dir: Path
    remote_allowed_count: int
    protected_ignored_count: int
    ignored_count: int
    decisions: list[FileDecision]
    protected_paths: list[str]
    ignored_paths: list[str]
    download_payloads: dict[str, bytes] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    @property
    def new_files(self) -> list[FileDecision]:
        return [item for item in self.decisions if item.status == "NEW"]

    @property
    def modified_files(self) -> list[FileDecision]:
        return [item for item in self.decisions if item.status == "MODIFIED"]

    @property
    def same_files(self) -> list[FileDecision]:
        return [item for item in self.decisions if item.status == "SAME"]


@dataclass(slots=True)
class ApplyResult:
    analysis: AnalysisResult
    applied: bool
    backup_dir: Path | None
    staging_dir: Path | None
    log_path: Path | None
    rolled_back: bool
    warnings: list[str] = field(default_factory=list)


def normalize_relpath(value: str) -> str:
    return value.replace("\\", "/").lstrip("./")


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_config(path: Path) -> UpdaterConfig:
    payload = json.loads(path.read_text(encoding="utf-8"))
    missing = [key for key in ("owner", "repo", "branch", "install_dir", "allowed_roots", "protected_paths") if key not in payload]
    if missing:
        raise ConfigError(f"Faltan claves en config: {', '.join(missing)}")
    app_entrypoints = payload.get("app_entrypoints") or list(APP_ENTRYPOINTS_DEFAULT)
    return UpdaterConfig(
        owner=str(payload["owner"]).strip(),
        repo=str(payload["repo"]).strip(),
        branch=str(payload["branch"]).strip(),
        install_dir=str(payload.get("install_dir", ".")).strip() or ".",
        app_entrypoints=[str(item) for item in app_entrypoints],
        allowed_roots=[normalize_relpath(str(item)) for item in payload["allowed_roots"]],
        protected_paths=[normalize_relpath(str(item)) for item in payload["protected_paths"]],
    )


def validate_config(config: UpdaterConfig) -> None:
    if not config.owner or not config.repo or not config.branch:
        raise ConfigError("owner, repo y branch son obligatorios.")
    if not config.allowed_roots:
        raise ConfigError("allowed_roots no puede estar vacío.")


def resolve_install_dir(config: UpdaterConfig, install_dir_override: str | None = None) -> Path:
    return Path(install_dir_override or config.install_dir).expanduser().resolve()


def validate_install_dir(install_dir: Path, app_entrypoints: list[str]) -> None:
    if not install_dir.exists() or not install_dir.is_dir():
        raise InstallDirError(f"install_dir inválido: {install_dir}")
    has_entrypoint = any((install_dir / item).exists() for item in app_entrypoints)
    has_expected_dir = any((install_dir / item).is_dir() for item in EXPECTED_DIRS)
    if not has_entrypoint or not has_expected_dir:
        raise InstallDirError(
            f"install_dir no parece una instalación válida: {install_dir}. "
            "Debe contener un entrypoint y al menos una carpeta ui/services/automation."
        )


def is_path_allowed(path: str, allowed_roots: list[str]) -> bool:
    normalized = normalize_relpath(path)
    for root in allowed_roots:
        current = normalize_relpath(root)
        if current.endswith("/"):
            if normalized.startswith(current):
                return True
        elif normalized == current:
            return True
    return False


def is_path_protected(path: str, protected_paths: list[str]) -> bool:
    normalized = normalize_relpath(path)
    for pattern in protected_paths:
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
        if normalized == current or Path(normalized).name == current:
            return True
    return False


def is_builtin_ignored(path: str) -> bool:
    normalized = normalize_relpath(path)
    return any(normalized.startswith(prefix) for prefix in BUILTIN_EXCLUDED_PREFIXES)


def github_tree_url(owner: str, repo: str, branch: str) -> str:
    return f"https://api.github.com/repos/{owner}/{repo}/git/trees/{branch}?recursive=1"


def build_raw_url(owner: str, repo: str, branch: str, path: str) -> str:
    return f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/{normalize_relpath(path)}"


def _default_fetch_json(url: str) -> dict:
    request = Request(url, headers={"User-Agent": "auto-he-llegado-updater"})
    with urlopen(request) as response:  # noqa: S310
        return json.loads(response.read().decode("utf-8"))


def _default_fetch_bytes(url: str) -> bytes:
    request = Request(url, headers={"User-Agent": "auto-he-llegado-updater"})
    with urlopen(request) as response:  # noqa: S310
        return response.read()


class GitHubSyncUpdater:
    def __init__(
        self,
        config: UpdaterConfig,
        *,
        install_dir: Path | None = None,
        fetch_json: Callable[[str], dict] | None = None,
        fetch_bytes: Callable[[str], bytes] | None = None,
        now_factory: Callable[[], datetime] | None = None,
    ) -> None:
        validate_config(config)
        self.config = config
        self.install_dir = install_dir or resolve_install_dir(config)
        validate_install_dir(self.install_dir, self.config.app_entrypoints)
        self.fetch_json = fetch_json or _default_fetch_json
        self.fetch_bytes = fetch_bytes or _default_fetch_bytes
        self.now_factory = now_factory or datetime.now

    def check(self) -> CheckResult:
        remote_files, protected_paths, ignored_paths = self._fetch_remote_files()
        return CheckResult(
            repo=f"{self.config.owner}/{self.config.repo}",
            branch=self.config.branch,
            install_dir=self.install_dir,
            remote_allowed_count=len(remote_files),
            protected_ignored_count=len(protected_paths),
            ignored_count=len(ignored_paths),
            protected_paths=protected_paths,
            ignored_paths=ignored_paths,
        )

    def analyze(self) -> AnalysisResult:
        remote_files, protected_paths, ignored_paths = self._fetch_remote_files()
        decisions: list[FileDecision] = []
        payloads: dict[str, bytes] = {}
        errors: list[str] = []

        for remote_file in remote_files:
            try:
                remote_bytes = self.fetch_bytes(build_raw_url(self.config.owner, self.config.repo, self.config.branch, remote_file.path))
                remote_hash = sha256_bytes(remote_bytes)
                local_path = self.install_dir / remote_file.path
                if not local_path.exists():
                    status = "NEW"
                    local_hash = None
                else:
                    local_hash = sha256_file(local_path)
                    status = "SAME" if local_hash == remote_hash else "MODIFIED"
                decisions.append(FileDecision(remote_file.path, status, local_hash, remote_hash))
                if status in {"NEW", "MODIFIED"}:
                    payloads[remote_file.path] = remote_bytes
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{remote_file.path}: {exc}")

        decisions.sort(key=lambda item: item.path)
        return AnalysisResult(
            repo=f"{self.config.owner}/{self.config.repo}",
            branch=self.config.branch,
            install_dir=self.install_dir,
            remote_allowed_count=len(remote_files),
            protected_ignored_count=len(protected_paths),
            ignored_count=len(ignored_paths),
            decisions=decisions,
            protected_paths=protected_paths,
            ignored_paths=ignored_paths,
            download_payloads=payloads,
            errors=errors,
        )

    def dry_run(self) -> AnalysisResult:
        return self.analyze()

    def apply(self) -> ApplyResult:
        analysis = self.analyze()
        warnings = ["Cierre Auto He Llegado antes de aplicar."]
        timestamp = self.now_factory().strftime("%Y%m%d_%H%M%S")
        updates_root = self.install_dir / "updates"
        staging_dir = updates_root / "staging" / timestamp
        backup_dir = updates_root / "backups" / timestamp
        logs_dir = updates_root / "update_logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        log_path = logs_dir / f"{timestamp}.log"

        if analysis.errors:
            self._write_log(log_path, analysis, applied=False, backup_dir=None, staging_dir=None, rolled_back=False, warnings=warnings)
            raise RemoteSyncError("No se pudo completar el análisis remoto.")

        changed = analysis.new_files + analysis.modified_files
        if not changed:
            self._write_log(log_path, analysis, applied=False, backup_dir=None, staging_dir=None, rolled_back=False, warnings=warnings)
            return ApplyResult(analysis=analysis, applied=False, backup_dir=None, staging_dir=None, log_path=log_path, rolled_back=False, warnings=warnings)

        staging_dir.mkdir(parents=True, exist_ok=True)
        backup_dir.mkdir(parents=True, exist_ok=True)

        for decision in changed:
            staged_target = staging_dir / decision.path
            staged_target.parent.mkdir(parents=True, exist_ok=True)
            content = analysis.download_payloads[decision.path]
            staged_target.write_bytes(content)
            if sha256_file(staged_target) != decision.remote_hash:
                raise RemoteSyncError(f"Hash inválido en staging para {decision.path}")

        for decision in analysis.modified_files:
            source = self.install_dir / decision.path
            backup_target = backup_dir / decision.path
            backup_target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, backup_target)

        applied_new: list[Path] = []
        applied_replaced: list[Path] = []
        rolled_back = False
        try:
            for decision in changed:
                source = staging_dir / decision.path
                target = self.install_dir / decision.path
                target.parent.mkdir(parents=True, exist_ok=True)
                self._copy_file(source, target)
                if decision.status == "NEW":
                    applied_new.append(target)
                else:
                    applied_replaced.append(target)
        except Exception as exc:  # noqa: BLE001
            rolled_back = True
            self._rollback(backup_dir, applied_new, applied_replaced)
            self._write_log(log_path, analysis, applied=False, backup_dir=backup_dir, staging_dir=staging_dir, rolled_back=True, warnings=warnings, extra_error=str(exc))
            raise RemoteSyncError(f"Falló la aplicación: {exc}") from exc

        self._write_log(log_path, analysis, applied=True, backup_dir=backup_dir, staging_dir=staging_dir, rolled_back=False, warnings=warnings)
        return ApplyResult(analysis=analysis, applied=True, backup_dir=backup_dir, staging_dir=staging_dir, log_path=log_path, rolled_back=rolled_back, warnings=warnings)

    def _fetch_remote_files(self) -> tuple[list[RemoteFile], list[str], list[str]]:
        payload = self.fetch_json(github_tree_url(self.config.owner, self.config.repo, self.config.branch))
        tree = payload.get("tree")
        if not isinstance(tree, list):
            raise RemoteSyncError("Respuesta inválida de GitHub tree API.")

        allowed: list[RemoteFile] = []
        protected_paths: list[str] = []
        ignored_paths: list[str] = []

        for item in tree:
            if item.get("type") != "blob":
                continue
            path = normalize_relpath(str(item.get("path") or ""))
            if not path:
                continue
            if not is_path_allowed(path, self.config.allowed_roots):
                ignored_paths.append(path)
                continue
            if is_builtin_ignored(path):
                ignored_paths.append(path)
                continue
            if is_path_protected(path, self.config.protected_paths):
                protected_paths.append(path)
                continue
            allowed.append(RemoteFile(path=path, sha=str(item.get("sha") or "")))

        allowed.sort(key=lambda item: item.path)
        protected_paths.sort()
        ignored_paths.sort()
        return allowed, protected_paths, ignored_paths

    @staticmethod
    def _copy_file(source: Path, target: Path) -> None:
        shutil.copy2(source, target)

    def _rollback(self, backup_dir: Path, applied_new: list[Path], applied_replaced: list[Path]) -> None:
        for target in applied_new:
            if target.exists():
                target.unlink()
        for target in applied_replaced:
            relative = target.relative_to(self.install_dir)
            backup_source = backup_dir / relative
            if backup_source.exists():
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(backup_source, target)

    def _write_log(
        self,
        log_path: Path,
        analysis: AnalysisResult,
        *,
        applied: bool,
        backup_dir: Path | None,
        staging_dir: Path | None,
        rolled_back: bool,
        warnings: list[str],
        extra_error: str | None = None,
    ) -> None:
        lines = [
            f"Repo: {analysis.repo}",
            f"Branch: {analysis.branch}",
            f"Install dir: {analysis.install_dir}",
            f"Remotos permitidos: {analysis.remote_allowed_count}",
            f"Nuevos: {len(analysis.new_files)}",
            f"Modificados: {len(analysis.modified_files)}",
            f"Iguales: {len(analysis.same_files)}",
            f"Protegidos ignorados: {analysis.protected_ignored_count}",
            f"Errores: {len(analysis.errors)}",
            f"Aplicado: {'si' if applied else 'no'}",
            f"Rollback: {'si' if rolled_back else 'no'}",
            f"Backup: {backup_dir or 'N/A'}",
            f"Staging: {staging_dir or 'N/A'}",
        ]
        if warnings:
            lines.extend(f"Warning: {warning}" for warning in warnings)
        if extra_error:
            lines.append(f"Error: {extra_error}")
        log_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def render_summary(result: CheckResult | AnalysisResult | ApplyResult, *, dry_run: bool = False) -> str:
    if isinstance(result, ApplyResult):
        analysis = result.analysis
        applied = "sí" if result.applied else "no"
        backup = str(result.backup_dir) if result.backup_dir else "N/A"
        log = str(result.log_path) if result.log_path else "N/A"
    elif isinstance(result, AnalysisResult):
        analysis = result
        applied = "no"
        backup = "N/A"
        log = "N/A"
    else:
        return "\n".join(
            [
                f"Repo: {result.repo}",
                f"Branch: {result.branch}",
                f"Install dir: {result.install_dir}",
                f"Remotos permitidos: {result.remote_allowed_count}",
                f"Protegidos ignorados: {result.protected_ignored_count}",
                f"Ignorados: {result.ignored_count}",
                "Aplicado: no",
            ]
        )

    lines = [
        f"Repo: {analysis.repo}",
        f"Branch: {analysis.branch}",
        f"Install dir: {analysis.install_dir}",
        f"Remotos permitidos: {analysis.remote_allowed_count}",
        f"Nuevos: {len(analysis.new_files)}",
        f"Modificados: {len(analysis.modified_files)}",
        f"Iguales: {len(analysis.same_files)}",
        f"Protegidos ignorados: {analysis.protected_ignored_count}",
        f"Errores: {len(analysis.errors)}",
        f"Aplicado: {applied}",
        f"Backup: {backup}",
        f"Log: {log}",
    ]
    if dry_run:
        lines.append("No se aplicó ningún cambio porque es dry-run.")
    return "\n".join(lines)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Updater externo por GitHub API para Auto He Llegado.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--check", action="store_true")
    group.add_argument("--dry-run", action="store_true")
    group.add_argument("--apply", action="store_true")
    parser.add_argument("--config", default="updater/updater_config.json")
    parser.add_argument("--install-dir", default=None)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    config_path = Path(args.config)
    try:
        config = load_config(config_path)
        updater = GitHubSyncUpdater(config, install_dir=resolve_install_dir(config, args.install_dir))
        if args.check:
            result = updater.check()
            print(render_summary(result))
            return 0
        if args.dry_run:
            result = updater.dry_run()
            print(render_summary(result, dry_run=True))
            return 0 if not result.errors else 1
        result = updater.apply()
        print(render_summary(result))
        if result.applied:
            print("Actualización aplicada. Puede abrir Auto He Llegado.")
        return 0
    except UpdaterError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR inesperado: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
