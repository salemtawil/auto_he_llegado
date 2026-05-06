from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from config.settings import Settings, get_settings


class TempFileService:
    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._temp_dir = self._settings.local_data_dir / "temp_photos"
        self._temp_dir.mkdir(parents=True, exist_ok=True)

    def create_photo_copy(
        self,
        *,
        content: bytes,
        original_filename: str,
    ) -> Path:
        suffix = Path(original_filename).suffix or ".jpg"
        target_path = self._temp_dir / f"{uuid4()}{suffix.lower()}"
        target_path.write_bytes(content)
        return target_path

    def delete_file(self, path_value: str | Path) -> None:
        path = Path(path_value)
        if path.exists():
            path.unlink()
