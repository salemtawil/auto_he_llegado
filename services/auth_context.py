from __future__ import annotations

from dataclasses import dataclass
from dataclasses import replace
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


def update_current_session_tokens(*, access_token: str, refresh_token: str) -> AuthSession | None:
    global _current_session
    with _session_lock:
        if _current_session is None:
            return None
        _current_session = replace(
            _current_session,
            access_token=access_token,
            refresh_token=refresh_token,
        )
        return _current_session


def require_current_session() -> AuthSession:
    session = get_current_session()
    if session is None:
        raise RuntimeError("No hay una sesion activa. Inicia sesion para continuar.")
    return session
