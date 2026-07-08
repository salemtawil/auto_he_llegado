from __future__ import annotations

from services.auth_context import AuthSession, set_current_session
from ui.main_app.window import MainAppWindow


class _FakeTile:
    def __init__(self, name: str) -> None:
        self.name = name
        self.visible = False
        self.grid_calls: list[dict] = []

    def grid(self, **kwargs) -> None:
        self.visible = True
        self.grid_calls.append(kwargs)

    def grid_forget(self) -> None:
        self.visible = False


def _session(*, role: str) -> AuthSession:
    return AuthSession(
        user_id="user-1",
        email="usuario",
        access_token="token",
        refresh_token="refresh",
        role=role,
        approved=True,
        disabled=False,
    )


def _window_with_tiles(session: AuthSession) -> tuple[MainAppWindow, dict[str, _FakeTile]]:
    window = MainAppWindow.__new__(MainAppWindow)
    window._auth_session = session  # noqa: SLF001
    tiles = {
        "refresh": _FakeTile("refresh"),
        "admin": _FakeTile("admin"),
        "uploader": _FakeTile("uploader"),
        "cleanup": _FakeTile("cleanup"),
        "video": _FakeTile("video"),
        "theme": _FakeTile("theme"),
        "settings": _FakeTile("settings"),
    }
    window.refresh_button = tiles["refresh"]  # type: ignore[assignment]
    window.admin_button = tiles["admin"]  # type: ignore[assignment]
    window.uploader_button = tiles["uploader"]  # type: ignore[assignment]
    window.cleanup_button = tiles["cleanup"]  # type: ignore[assignment]
    window.video_button = tiles["video"]  # type: ignore[assignment]
    window.theme_toggle_button = tiles["theme"]  # type: ignore[assignment]
    window.settings_button = tiles["settings"]  # type: ignore[assignment]
    return window, tiles


def test_member_header_only_shows_basic_actions_and_video() -> None:
    set_current_session(None)
    window, tiles = _window_with_tiles(_session(role="member"))

    window._layout_header_actions()  # noqa: SLF001

    assert [name for name, tile in tiles.items() if tile.visible] == [
        "refresh",
        "video",
        "theme",
        "settings",
    ]


def test_admin_header_shows_all_actions() -> None:
    set_current_session(None)
    window, tiles = _window_with_tiles(_session(role="admin"))

    window._layout_header_actions()  # noqa: SLF001

    assert [name for name, tile in tiles.items() if tile.visible] == [
        "refresh",
        "admin",
        "uploader",
        "cleanup",
        "video",
        "theme",
        "settings",
    ]
