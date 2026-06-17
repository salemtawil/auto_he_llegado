from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from threading import RLock


@dataclass(frozen=True)
class BackgroundVideoStatus:
    phase: str = "idle"
    message: str = ""
    current: int = 0
    total: int = 0
    is_running: bool = False
    is_complete: bool = False
    is_error: bool = False
    updated_at: str = ""

    @property
    def fraction(self) -> float:
        if self.total <= 0:
            return 0.0
        return max(0.0, min(self.current / self.total, 1.0))


_status_lock = RLock()
_status = BackgroundVideoStatus()


def set_video_status(
    *,
    phase: str,
    message: str,
    current: int = 0,
    total: int = 0,
    is_running: bool = False,
    is_complete: bool = False,
    is_error: bool = False,
) -> None:
    global _status
    with _status_lock:
        _status = BackgroundVideoStatus(
            phase=phase,
            message=message,
            current=current,
            total=total,
            is_running=is_running,
            is_complete=is_complete,
            is_error=is_error,
            updated_at=datetime.now(timezone.utc).isoformat(),
        )


def get_video_status() -> BackgroundVideoStatus:
    with _status_lock:
        return _status
