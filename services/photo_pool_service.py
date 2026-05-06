from __future__ import annotations

from dataclasses import dataclass

from core.exceptions import RepositoryError
from storage.photos_repository import PhotosRepository


@dataclass(frozen=True)
class PhotoPoolSnapshot:
    available_count: int
    color: str
    label: str


class PhotoPoolService:
    def __init__(self, photos_repository: PhotosRepository | None = None) -> None:
        self._photos_repository = photos_repository or PhotosRepository()

    def get_snapshot(self) -> PhotoPoolSnapshot:
        count = self._photos_repository.count_available()
        color, label = self._resolve_state(count)
        return PhotoPoolSnapshot(available_count=count, color=color, label=label)

    @staticmethod
    def _resolve_state(count: int) -> tuple[str, str]:
        if count <= 20:
            return "#b44545", "Nivel bajo"
        if count <= 60:
            return "#c28a1b", "Nivel medio"
        return "#2f7d4a", "Nivel alto"
