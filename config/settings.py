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


def _get_float_env(name: str, default: float) -> float:
    raw_value = _get_env(name)
    if raw_value in (None, ""):
        return default
    try:
        return float(raw_value)
    except ValueError as exc:
        raise ConfigurationError(
            f"Environment variable '{name}' must be a number."
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


def _get_csv_env(name: str) -> tuple[str, ...]:
    raw_value = _get_env(name, "") or ""
    values = []
    for item in raw_value.split(","):
        normalized = item.strip()
        if normalized:
            values.append(normalized)
    return tuple(values)


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
    supabase_photo_batches_table: str
    supabase_photo_candidates_table: str
    supabase_profiles_table: str
    supabase_timeout_seconds: int
    admin_access_password: str
    weekly_min_approved_photos: int
    video_frame_interval_seconds: float
    video_max_candidate_frames: int
    video_jpeg_quality: int
    video_requirement_days: int = 7
    video_submission_mode: str = "drive"
    video_min_duration_seconds: float = 10.0
    video_duplicate_similarity_threshold: float = 0.72
    video_duplicate_hamming_threshold: int = 10
    google_drive_auth_mode: str = "oauth"
    google_drive_service_account_file: Path | None = None
    google_drive_oauth_client_file: Path | None = None
    google_drive_oauth_token_file: Path | None = None
    google_drive_folder_id: str = ""
    google_drive_share_anyone: bool = False
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    use_chrome_profile_extension: bool = False
    chrome_profile_dir: Path | None = None
    chrome_executable_path: Path | None = None
    supabase_legacy_storage_buckets: tuple[str, ...] = ()
    supabase_storage_limit_mb: int = 0

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
    drive_credentials_value = _get_env("GOOGLE_DRIVE_SERVICE_ACCOUNT_FILE")
    drive_credentials_path = (
        Path(drive_credentials_value).expanduser()
        if drive_credentials_value
        else None
    )
    if drive_credentials_path is not None and not drive_credentials_path.is_absolute():
        drive_credentials_path = (PROJECT_ROOT / drive_credentials_path).resolve()
    drive_oauth_client_value = _get_env("GOOGLE_DRIVE_OAUTH_CLIENT_FILE")
    drive_oauth_client_path = (
        Path(drive_oauth_client_value).expanduser()
        if drive_oauth_client_value
        else None
    )
    if drive_oauth_client_path is not None and not drive_oauth_client_path.is_absolute():
        drive_oauth_client_path = (PROJECT_ROOT / drive_oauth_client_path).resolve()
    drive_oauth_token_value = _get_env("GOOGLE_DRIVE_OAUTH_TOKEN_FILE")
    drive_oauth_token_path = (
        Path(drive_oauth_token_value).expanduser()
        if drive_oauth_token_value
        else local_data_dir / "google_drive_token.json"
    )
    if not drive_oauth_token_path.is_absolute():
        drive_oauth_token_path = (PROJECT_ROOT / drive_oauth_token_path).resolve()

    return Settings(
        app_name=_get_env("APP_NAME", "auto_he_llegado") or "auto_he_llegado",
        app_env=_get_env("APP_ENV", "development") or "development",
        log_level=(_get_env("LOG_LEVEL", "INFO") or "INFO").upper(),
        project_root=PROJECT_ROOT,
        local_data_dir=local_data_dir,
        supabase_url=_get_env("SUPABASE_URL"),
        supabase_key=_get_env("SUPABASE_KEY"),
        supabase_storage_bucket=(
            _get_env("SUPABASE_STORAGE_BUCKET", "photo-pool") or "photo-pool"
        ),
        supabase_photos_table=(
            _get_env("SUPABASE_PHOTOS_TABLE", "photos") or "photos"
        ),
        supabase_process_logs_table=(
            _get_env("SUPABASE_PROCESS_LOGS_TABLE", "process_logs")
            or "process_logs"
        ),
        supabase_photo_batches_table=(
            _get_env("SUPABASE_PHOTO_BATCHES_TABLE", "photo_ingest_batches")
            or "photo_ingest_batches"
        ),
        supabase_photo_candidates_table=(
            _get_env("SUPABASE_PHOTO_CANDIDATES_TABLE", "photo_candidates")
            or "photo_candidates"
        ),
        supabase_profiles_table=(
            _get_env("SUPABASE_PROFILES_TABLE", "profiles") or "profiles"
        ),
        supabase_timeout_seconds=_get_int_env("SUPABASE_TIMEOUT_SECONDS", 30),
        supabase_storage_limit_mb=_get_int_env("SUPABASE_STORAGE_LIMIT_MB", 0),
        admin_access_password=_get_env("ADMIN_ACCESS_PASSWORD", "123456987") or "123456987",
        weekly_min_approved_photos=_get_int_env("WEEKLY_MIN_APPROVED_PHOTOS", 20),
        video_requirement_days=_get_int_env("VIDEO_REQUIREMENT_DAYS", 7),
        video_frame_interval_seconds=_get_float_env("VIDEO_FRAME_INTERVAL_SECONDS", 0.0),
        video_max_candidate_frames=_get_int_env("VIDEO_MAX_CANDIDATE_FRAMES", 300),
        video_jpeg_quality=_get_int_env("VIDEO_JPEG_QUALITY", 88),
        video_submission_mode=(
            _get_env("VIDEO_SUBMISSION_MODE", "drive") or "drive"
        ).lower(),
        video_min_duration_seconds=_get_float_env("VIDEO_MIN_DURATION_SECONDS", 10.0),
        video_duplicate_similarity_threshold=_get_float_env(
            "VIDEO_DUPLICATE_SIMILARITY_THRESHOLD",
            0.72,
        ),
        video_duplicate_hamming_threshold=_get_int_env(
            "VIDEO_DUPLICATE_HAMMING_THRESHOLD",
            10,
        ),
        google_drive_auth_mode=(
            _get_env("GOOGLE_DRIVE_AUTH_MODE", "oauth") or "oauth"
        ).lower(),
        google_drive_service_account_file=drive_credentials_path,
        google_drive_oauth_client_file=drive_oauth_client_path,
        google_drive_oauth_token_file=drive_oauth_token_path,
        google_drive_folder_id=_get_env("GOOGLE_DRIVE_FOLDER_ID", "") or "",
        google_drive_share_anyone=_get_bool_env("GOOGLE_DRIVE_SHARE_ANYONE", False),
        telegram_bot_token=_get_env("TELEGRAM_BOT_TOKEN", "") or "",
        telegram_chat_id=_get_env("TELEGRAM_CHAT_ID", "") or "",
        use_chrome_profile_extension=_get_bool_env(
            "AUTO_HE_LLEGADO_USE_CHROME_PROFILE_EXTENSION",
            False,
        ),
        chrome_profile_dir=chrome_profile_dir,
        chrome_executable_path=chrome_executable_path,
        supabase_legacy_storage_buckets=_get_csv_env("SUPABASE_LEGACY_STORAGE_BUCKETS"),
    )
