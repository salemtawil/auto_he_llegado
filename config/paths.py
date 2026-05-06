from __future__ import annotations

from pathlib import Path
import sys


SOURCE_ROOT = Path(__file__).resolve().parent.parent
BUNDLE_ROOT = Path(getattr(sys, "_MEIPASS", SOURCE_ROOT)).resolve()


def _resolve_runtime_root() -> Path:
    if not getattr(sys, "frozen", False):
        return SOURCE_ROOT

    executable_dir = Path(sys.executable).resolve().parent

    # PyInstaller app bundles on macOS run from:
    #   <release>/app_main.app/Contents/MacOS/app_main
    # The portable release needs .env, local_data and ms-playwright next to the .app.
    if (
        sys.platform == "darwin"
        and executable_dir.name == "MacOS"
        and executable_dir.parent.name == "Contents"
        and executable_dir.parent.parent.suffix == ".app"
    ):
        return executable_dir.parent.parent.parent

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
