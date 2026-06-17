from __future__ import annotations

from dataclasses import dataclass
from threading import RLock


@dataclass(frozen=True)
class AuthSession:
    user_id: str
    email: str
    access_token: str
    refresh_token: str
    display_name: str = ""
    role: str = "member"
    approved: bool = False
    disabled: bool = False

    @property
    def is_admin(self) -> bool:
        return self.role.strip().lower() == "admin"


_session_lock = RLock()
_current_session: AuthSession | None = None


def set_current_session(session: AuthSession | None) -> None:
    global _current_session
    with _session_lock:
        _current_session = session


def get_current_session() -> AuthSession | None:
    with _session_lock:
        return _current_session


def require_current_session() -> AuthSession:
    session = get_current_session()
    if session is None:
        raise RuntimeError("No hay una sesion activa. Inicia sesion para continuar.")
    return session
