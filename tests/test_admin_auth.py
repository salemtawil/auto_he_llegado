from __future__ import annotations

from types import SimpleNamespace

import app_debug_inspector
import app_uploader
from ui.admin_auth import is_admin_password_valid, request_admin_access


def _settings(password: str = "secret") -> SimpleNamespace:
    return SimpleNamespace(admin_access_password=password)


def _session(*, is_admin: bool = True) -> SimpleNamespace:
    return SimpleNamespace(is_admin=is_admin)


def test_is_admin_password_valid_accepts_correct_password() -> None:
    assert is_admin_password_valid("secret", _settings()) is True


def test_is_admin_password_valid_rejects_incorrect_password() -> None:
    assert is_admin_password_valid("wrong", _settings()) is False


def test_request_admin_access_allows_correct_password_from_dialog_factory() -> None:
    assert request_admin_access(settings=_settings(), dialog_factory=lambda: "secret") is True


def test_request_admin_access_blocks_incorrect_password_from_dialog_factory() -> None:
    assert request_admin_access(settings=_settings(), dialog_factory=lambda: "wrong") is False


def test_request_admin_access_blocks_cancel_from_dialog_factory() -> None:
    assert request_admin_access(settings=_settings(), dialog_factory=lambda: None) is False


def test_app_uploader_does_not_open_window_if_admin_fails(monkeypatch) -> None:
    calls: list[str] = []

    monkeypatch.setattr(app_uploader, "setup_theme", lambda: calls.append("theme"))
    monkeypatch.setattr(app_uploader, "request_app_access", lambda: _session())
    monkeypatch.setattr(app_uploader, "request_admin_access", lambda: False)
    monkeypatch.setattr(app_uploader, "UploaderWindow", lambda: calls.append("window"))

    app_uploader.main()

    assert calls == ["theme"]


def test_app_uploader_opens_window_if_admin_succeeds(monkeypatch) -> None:
    calls: list[str] = []

    class _FakeWindow:
        def __init__(self) -> None:
            calls.append("window")

        def mainloop(self) -> None:
            calls.append("mainloop")

    monkeypatch.setattr(app_uploader, "setup_theme", lambda: calls.append("theme"))
    monkeypatch.setattr(app_uploader, "request_app_access", lambda: _session())
    monkeypatch.setattr(app_uploader, "request_admin_access", lambda: True)
    monkeypatch.setattr(app_uploader, "UploaderWindow", _FakeWindow)

    app_uploader.main()

    assert calls == ["theme", "window", "mainloop"]


def test_app_uploader_does_not_request_admin_if_login_fails(monkeypatch) -> None:
    calls: list[str] = []

    monkeypatch.setattr(app_uploader, "setup_theme", lambda: calls.append("theme"))
    monkeypatch.setattr(app_uploader, "request_app_access", lambda: None)
    monkeypatch.setattr(app_uploader, "request_admin_access", lambda: calls.append("admin"))
    monkeypatch.setattr(app_uploader, "UploaderWindow", lambda: calls.append("window"))

    app_uploader.main()

    assert calls == ["theme"]


def test_app_uploader_does_not_request_admin_if_user_is_not_admin(monkeypatch) -> None:
    calls: list[str] = []

    monkeypatch.setattr(app_uploader, "setup_theme", lambda: calls.append("theme"))
    monkeypatch.setattr(app_uploader, "request_app_access", lambda: _session(is_admin=False))
    monkeypatch.setattr(app_uploader, "request_admin_access", lambda: calls.append("admin"))
    monkeypatch.setattr(app_uploader, "UploaderWindow", lambda: calls.append("window"))

    app_uploader.main()

    assert calls == ["theme"]


def test_app_debug_inspector_does_not_open_window_if_admin_fails(monkeypatch) -> None:
    calls: list[str] = []

    monkeypatch.setattr(app_debug_inspector, "setup_theme", lambda: calls.append("theme"))
    monkeypatch.setattr(app_debug_inspector, "request_app_access", lambda: _session())
    monkeypatch.setattr(app_debug_inspector, "request_admin_access", lambda: False)
    monkeypatch.setattr(app_debug_inspector, "DebugInspectorWindow", lambda: calls.append("window"))

    app_debug_inspector.main()

    assert calls == ["theme"]


def test_app_debug_inspector_opens_window_if_admin_succeeds(monkeypatch) -> None:
    calls: list[str] = []

    class _FakeWindow:
        def __init__(self) -> None:
            calls.append("window")

        def mainloop(self) -> None:
            calls.append("mainloop")

    monkeypatch.setattr(app_debug_inspector, "setup_theme", lambda: calls.append("theme"))
    monkeypatch.setattr(app_debug_inspector, "request_app_access", lambda: _session())
    monkeypatch.setattr(app_debug_inspector, "request_admin_access", lambda: True)
    monkeypatch.setattr(app_debug_inspector, "DebugInspectorWindow", _FakeWindow)

    app_debug_inspector.main()

    assert calls == ["theme", "window", "mainloop"]


def test_app_debug_inspector_does_not_request_admin_if_login_fails(monkeypatch) -> None:
    calls: list[str] = []

    monkeypatch.setattr(app_debug_inspector, "setup_theme", lambda: calls.append("theme"))
    monkeypatch.setattr(app_debug_inspector, "request_app_access", lambda: None)
    monkeypatch.setattr(app_debug_inspector, "request_admin_access", lambda: calls.append("admin"))
    monkeypatch.setattr(app_debug_inspector, "DebugInspectorWindow", lambda: calls.append("window"))

    app_debug_inspector.main()

    assert calls == ["theme"]


def test_app_debug_inspector_does_not_request_admin_if_user_is_not_admin(monkeypatch) -> None:
    calls: list[str] = []

    monkeypatch.setattr(app_debug_inspector, "setup_theme", lambda: calls.append("theme"))
    monkeypatch.setattr(app_debug_inspector, "request_app_access", lambda: _session(is_admin=False))
    monkeypatch.setattr(app_debug_inspector, "request_admin_access", lambda: calls.append("admin"))
    monkeypatch.setattr(app_debug_inspector, "DebugInspectorWindow", lambda: calls.append("window"))

    app_debug_inspector.main()

    assert calls == ["theme"]
