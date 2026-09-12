from __future__ import annotations

import json
from types import SimpleNamespace

from services.login_credentials_store import LoginCredentialsStore


def _settings(tmp_path):
    return SimpleNamespace(local_data_dir=tmp_path)


def test_save_uses_macos_keychain_for_password(tmp_path, monkeypatch) -> None:
    calls = []

    def fake_run(args, **kwargs):
        calls.append((args, kwargs))
        return SimpleNamespace(returncode=0, stdout="")

    monkeypatch.setattr("services.login_credentials_store.sys.platform", "darwin")
    monkeypatch.setattr("services.login_credentials_store.subprocess.run", fake_run)

    store = LoginCredentialsStore(settings=_settings(tmp_path))
    store.save(identifier="alvaro", password="Compi123.")

    data = json.loads((tmp_path / "remembered_login.json").read_text(encoding="utf-8"))
    assert data == {"identifier": "alvaro", "password_keychain": True}
    assert calls[0][0] == [
        "security",
        "add-generic-password",
        "-U",
        "-s",
        "AutoHeLlegado Login",
        "-a",
        "alvaro",
        "-w",
        "Compi123.",
    ]


def test_load_uses_macos_keychain_for_password(tmp_path, monkeypatch) -> None:
    (tmp_path / "remembered_login.json").write_text(
        json.dumps({"identifier": "alvaro", "password_keychain": True}),
        encoding="utf-8",
    )

    def fake_run(args, **kwargs):
        assert args == [
            "security",
            "find-generic-password",
            "-s",
            "AutoHeLlegado Login",
            "-a",
            "alvaro",
            "-w",
        ]
        return SimpleNamespace(returncode=0, stdout="Compi123.\n")

    monkeypatch.setattr("services.login_credentials_store.sys.platform", "darwin")
    monkeypatch.setattr("services.login_credentials_store.subprocess.run", fake_run)

    remembered = LoginCredentialsStore(settings=_settings(tmp_path)).load()

    assert remembered.identifier == "alvaro"
    assert remembered.password == "Compi123."


def test_clear_removes_macos_keychain_password(tmp_path, monkeypatch) -> None:
    (tmp_path / "remembered_login.json").write_text(
        json.dumps({"identifier": "alvaro", "password_keychain": True}),
        encoding="utf-8",
    )
    calls = []

    def fake_run(args, **kwargs):
        calls.append(args)
        if "find-generic-password" in args:
            return SimpleNamespace(returncode=0, stdout="Compi123.\n")
        return SimpleNamespace(returncode=0, stdout="")

    monkeypatch.setattr("services.login_credentials_store.sys.platform", "darwin")
    monkeypatch.setattr("services.login_credentials_store.subprocess.run", fake_run)

    store = LoginCredentialsStore(settings=_settings(tmp_path))
    store.clear()

    assert not (tmp_path / "remembered_login.json").exists()
    assert calls[-1] == [
        "security",
        "delete-generic-password",
        "-s",
        "AutoHeLlegado Login",
        "-a",
        "alvaro",
    ]
