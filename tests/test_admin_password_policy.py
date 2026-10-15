"""The admin password must fail closed and never carry a shipped default."""

from __future__ import annotations

from types import SimpleNamespace

from ui.admin_auth import is_admin_password_valid


def test_unset_admin_password_unlocks_nothing() -> None:
    settings = SimpleNamespace(admin_access_password="")
    assert is_admin_password_valid("", settings) is False
    assert is_admin_password_valid("123456987", settings) is False
    assert is_admin_password_valid("anything", settings) is False


def test_configured_admin_password_still_matches() -> None:
    settings = SimpleNamespace(admin_access_password="una-clave-real")
    assert is_admin_password_valid("una-clave-real", settings) is True
    assert is_admin_password_valid("otra", settings) is False


def test_settings_do_not_ship_a_default_admin_password(monkeypatch) -> None:
    from config import settings as settings_module

    monkeypatch.delenv("ADMIN_ACCESS_PASSWORD", raising=False)
    settings_module.get_settings.cache_clear()
    try:
        assert settings_module.get_settings().admin_access_password == ""
    finally:
        settings_module.get_settings.cache_clear()
