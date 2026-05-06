from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
import os

from dotenv import load_dotenv

from config.paths import DEFAULT_LOCAL_DATA_DIR, ENV_FILE, PROJECT_ROOT
from core.exceptions import ConfigurationError


load_dotenv(ENV_FILE, override=False)


def _get_env(name: str, default: str | None = None) -> str | None:
    value = os.getenv(name, default)
    if value is None:
        return None
    return value.strip()


def _get_int_env(name: str, default: int) -> int:
    raw_value = _get_env(name)
    if raw_value in (None, ""):
        return default
    try:
        return int(raw_value)
    except ValueError as exc:
        raise ConfigurationError(
            f"Environment variable '{name}' must be an integer."
        ) from exc


def _get_bool_env(name: str, default: bool = False) -> bool:
    raw_value = _get_env(name)
    if raw_value in (None, ""):
        return default
    normalized = raw_value.strip().lower()
    if normalized in {"1", "true", "yes", "si", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ConfigurationError(
        f"Environment variable '{name}' must be a boolean."
    )


@dataclass(frozen=True)
class Settings:
    app_name: str
    app_env: str
    log_level: str
    project_root: Path
    local_data_dir: Path
    supabase_url: str | None
    supabase_key: str | None
    supabase_storage_bucket: str
    supabase_photos_table: str
    supabase_process_logs_table: str
    supabase_timeout_seconds: int
    admin_access_password: str
    use_chrome_profile_extension: bool = False
    chrome_profile_dir: Path | None = None
    chrome_executable_path: Path | None = None

    @property
    def supabase_enabled(self) -> bool:
        return bool(self.supabase_url and self.supabase_key)

    def require_supabase(self) -> None:
        if not self.supabase_enabled:
            raise ConfigurationError(
                "Supabase is not configured. Define SUPABASE_URL and SUPABASE_KEY."
            )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    local_data_value = _get_env("LOCAL_DATA_DIR")
    local_data_dir = (
        Path(local_data_value).expanduser()
        if local_data_value
        else DEFAULT_LOCAL_DATA_DIR
    )
    if not local_data_dir.is_absolute():
        local_data_dir = (PROJECT_ROOT / local_data_dir).resolve()
    chrome_profile_value = _get_env("AUTO_HE_LLEGADO_CHROME_PROFILE_DIR")
    chrome_profile_dir = (
        Path(chrome_profile_value).expanduser()
        if chrome_profile_value
        else None
    )
    if chrome_profile_dir is not None and not chrome_profile_dir.is_absolute():
        chrome_profile_dir = (PROJECT_ROOT / chrome_profile_dir).resolve()
    chrome_executable_value = _get_env("AUTO_HE_LLEGADO_CHROME_EXECUTABLE_PATH")
    chrome_executable_path = (
        Path(chrome_executable_value).expanduser()
        if chrome_executable_value
        else None
    )
    if chrome_executable_path is not None and not chrome_executable_path.is_absolute():
        chrome_executable_path = (PROJECT_ROOT / chrome_executable_path).resolve()

    return Settings(
        app_name=_get_env("APP_NAME", "auto_he_llegado") or "auto_he_llegado",
        app_env=_get_env("APP_ENV", "development") or "development",
        log_level=(_get_env("LOG_LEVEL", "INFO") or "INFO").upper(),
        project_root=PROJECT_ROOT,
        local_data_dir=local_data_dir,
        supabase_url=_get_env("SUPABASE_URL"),
        supabase_key=_get_env("SUPABASE_KEY"),
        supabase_storage_bucket=(
            _get_env("SUPABASE_STORAGE_BUCKET", "photos") or "photos"
        ),
        supabase_photos_table=(
            _get_env("SUPABASE_PHOTOS_TABLE", "photos") or "photos"
        ),
        supabase_process_logs_table=(
            _get_env("SUPABASE_PROCESS_LOGS_TABLE", "process_logs")
            or "process_logs"
        ),
        supabase_timeout_seconds=_get_int_env("SUPABASE_TIMEOUT_SECONDS", 30),
        admin_access_password=_get_env("ADMIN_ACCESS_PASSWORD", "123456987") or "123456987",
        use_chrome_profile_extension=_get_bool_env(
            "AUTO_HE_LLEGADO_USE_CHROME_PROFILE_EXTENSION",
            False,
        ),
        chrome_profile_dir=chrome_profile_dir,
        chrome_executable_path=chrome_executable_path,
    )
