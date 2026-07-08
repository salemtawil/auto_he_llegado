from __future__ import annotations

from pathlib import Path
import os
import sys


SOURCE_ROOT = Path(__file__).resolve().parent.parent
BUNDLE_ROOT = Path(getattr(sys, "_MEIPASS", SOURCE_ROOT)).resolve()
APP_NAME = "AutoHeLlegado"


def _macos_application_support_root() -> Path:
    override = os.getenv("AUTO_HE_LLEGADO_APP_SUPPORT_DIR", "").strip()
    if override:
        return Path(override).expanduser().resolve()
    return (Path.home() / "Library" / "Application Support" / APP_NAME).resolve()


def _macos_app_bundle_from_executable(executable_dir: Path) -> Path | None:
    if (
        sys.platform == "darwin"
        and executable_dir.name == "MacOS"
        and executable_dir.parent.name == "Contents"
        and executable_dir.parent.parent.suffix == ".app"
    ):
        return executable_dir.parent.parent
    return None


def _is_installed_macos_app(app_bundle: Path) -> bool:
    normalized = app_bundle.as_posix()
    marker = f"/Applications/{APP_NAME}.app"
    return (
        normalized == marker
        or normalized.endswith(marker)
        or normalized.startswith(f"{marker}/")
        or f"{marker}/" in normalized
    )


def _resolve_runtime_root() -> Path:
    override = os.getenv("AUTO_HE_LLEGADO_RUNTIME_ROOT", "").strip()
    if override:
        return Path(override).expanduser().resolve()

    if not getattr(sys, "frozen", False):
        return SOURCE_ROOT

    executable_dir = Path(sys.executable).resolve().parent

    # PyInstaller app bundles on macOS run from:
    #   <release>/AutoHeLlegado.app/Contents/MacOS/AutoHeLlegado
    app_bundle = _macos_app_bundle_from_executable(executable_dir)
    if app_bundle is not None:
        if _is_installed_macos_app(app_bundle):
            return _macos_application_support_root()
        return app_bundle.parent

    return executable_dir


RUNTIME_ROOT = _resolve_runtime_root()

PROJECT_ROOT = RUNTIME_ROOT
CONFIG_DIR = BUNDLE_ROOT / "config"
CORE_DIR = BUNDLE_ROOT / "core"
STORAGE_DIR = BUNDLE_ROOT / "storage"
SERVICES_DIR = BUNDLE_ROOT / "services"
TESTS_DIR = BUNDLE_ROOT / "tests"

DEFAULT_LOCAL_DATA_DIR = PROJECT_ROOT / "local_data"
DEFAULT_CONFIG_DATA_DIR = DEFAULT_LOCAL_DATA_DIR / "config"
DEFAULT_LOGS_DIR = DEFAULT_LOCAL_DATA_DIR / "logs"
DEFAULT_FAILED_UPLOADS_DIR = DEFAULT_LOCAL_DATA_DIR / "failed_uploads"

ENV_FILE = PROJECT_ROOT / ".env"
ENV_EXAMPLE_FILE = PROJECT_ROOT / ".env.example"


def resolve_from_project(*parts: str) -> Path:
    return PROJECT_ROOT.joinpath(*parts).resolve()


def resolve_from_bundle(*parts: str) -> Path:
    return BUNDLE_ROOT.joinpath(*parts).resolve()
