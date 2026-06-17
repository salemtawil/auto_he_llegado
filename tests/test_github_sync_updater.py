from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest

from updater.github_sync_updater import (
    GitHubSyncUpdater,
    InstallDirError,
    UpdaterConfig,
    build_raw_url,
    is_path_allowed,
    is_path_protected,
    load_config,
    normalize_relpath,
    sha256_bytes,
    sha256_file,
    validate_install_dir,
)


def make_install_dir(tmp_path: Path) -> Path:
    install_dir = tmp_path / "app"
    install_dir.mkdir()
    (install_dir / "app_main.py").write_text("print('app')\n", encoding="utf-8")
    (install_dir / "ui").mkdir()
    (install_dir / "services").mkdir()
    (install_dir / "automation").mkdir()
    return install_dir


def make_portable_install_dir(
    tmp_path: Path,
    *,
    entrypoints: tuple[str, ...] = ("AutoHeLlegado.exe",),
    with_internal: bool = True,
) -> Path:
    install_dir = tmp_path / "portable"
    install_dir.mkdir()
    for entrypoint in entrypoints:
        entrypoint_path = install_dir / entrypoint
        if entrypoint_path.suffix.lower() == ".app":
            entrypoint_path.mkdir()
        else:
            entrypoint_path.write_text("portable\n", encoding="utf-8")
    if with_internal:
        (install_dir / "_internal").mkdir()
    return install_dir


def make_config(install_dir: Path) -> UpdaterConfig:
    return UpdaterConfig(
        owner="demo",
        repo="demo-repo",
        branch="main",
        install_dir=str(install_dir),
        app_entrypoints=["app_main.py", "app_main.exe", "AutoHeLlegado.app"],
        allowed_roots=["app_main.py", "automation/", "core/", "services/", "storage/", "ui/", "requirements.txt"],
        protected_paths=[".env", "config/", "logs/", "exports/", "data/", "local_data/", "chrome_profiles/", "backups/", "updates/", ".venv/", "__pycache__/", "*.local.json"],
    )


def fake_tree_payload() -> dict:
    return {
        "tree": [
            {"path": "app_main.py", "type": "blob", "sha": "1"},
            {"path": "ui/main.py", "type": "blob", "sha": "2"},
            {"path": "ui/config.local.json", "type": "blob", "sha": "3"},
            {"path": "updates/old.txt", "type": "blob", "sha": "4"},
            {"path": "docs/readme.md", "type": "blob", "sha": "5"},
        ]
    }


def fake_fetch_bytes_factory(mapping: dict[str, bytes]):
    def _fetch(url: str) -> bytes:
        path = url.split("/main/", 1)[1]
        return mapping[path]

    return _fetch


def test_load_config(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"owner": "a", "repo": "b", "branch": "main", "install_dir": ".", "allowed_roots": ["ui/"], "protected_paths": ["config/"]}), encoding="utf-8")
    config = load_config(path)
    assert config.owner == "a"
    assert config.allowed_roots == ["ui/"]


def test_load_config_accepts_utf8_sig_bom(tmp_path: Path) -> None:
    path = tmp_path / "config_bom.json"
    path.write_text(
        json.dumps(
            {
                "owner": "a",
                "repo": "b",
                "branch": "main",
                "install_dir": ".",
                "allowed_roots": ["ui/"],
                "protected_paths": ["config/"],
            }
        ),
        encoding="utf-8-sig",
    )

    config = load_config(path)

    assert config.owner == "a"
    assert config.repo == "b"


def test_validate_install_dir_valid(tmp_path: Path) -> None:
    install_dir = make_install_dir(tmp_path)
    validate_install_dir(install_dir, ["app_main.py"])


def test_validate_install_dir_accepts_portable_layout(tmp_path: Path) -> None:
    install_dir = make_portable_install_dir(tmp_path)

    validate_install_dir(install_dir, ["AutoHeLlegado.exe"])


def test_validate_install_dir_accepts_portable_without_ui_services_automation(tmp_path: Path) -> None:
    install_dir = make_portable_install_dir(tmp_path)

    validate_install_dir(install_dir, ["AutoHeLlegado.exe"])


def test_validate_install_dir_accepts_portable_with_multiple_entrypoints_from_config(tmp_path: Path) -> None:
    install_dir = make_portable_install_dir(
        tmp_path,
        entrypoints=("AutoHeLlegado.exe", "AutoHeLlegadoUploader.exe", "AutoHeLlegadoDebugInspector.exe"),
    )

    validate_install_dir(
        install_dir,
        ["AutoHeLlegado.exe", "AutoHeLlegadoUploader.exe", "AutoHeLlegadoDebugInspector.exe"],
    )


def test_validate_install_dir_accepts_macos_app_bundle(tmp_path: Path) -> None:
    install_dir = make_portable_install_dir(
        tmp_path,
        entrypoints=("AutoHeLlegado.app",),
        with_internal=False,
    )

    validate_install_dir(install_dir, ["AutoHeLlegado.app"])


def test_validate_install_dir_invalid(tmp_path: Path) -> None:
    install_dir = tmp_path / "bad"
    install_dir.mkdir()
    with pytest.raises(Exception):
        validate_install_dir(install_dir, ["app_main.py"])


def test_validate_install_dir_reports_source_layout_failure(tmp_path: Path) -> None:
    install_dir = tmp_path / "bad_source"
    install_dir.mkdir()
    (install_dir / "app_main.py").write_text("print('app')\n", encoding="utf-8")

    with pytest.raises(InstallDirError) as exc_info:
        validate_install_dir(install_dir, ["app_main.py"])

    message = str(exc_info.value)
    assert "source/dev" in message
    assert str(install_dir) in message
    assert "app_main.py" in message
    assert "ui" in message


def test_validate_install_dir_reports_portable_layout_failure(tmp_path: Path) -> None:
    install_dir = make_portable_install_dir(tmp_path, entrypoints=(), with_internal=True)

    with pytest.raises(InstallDirError) as exc_info:
        validate_install_dir(install_dir, ["AutoHeLlegado.exe"])

    message = str(exc_info.value)
    assert "portable" in message
    assert str(install_dir) in message
    assert "_internal" in message
    assert "AutoHeLlegado.exe" in message


def test_path_allowed() -> None:
    assert is_path_allowed("ui/main.py", ["ui/", "services/"])
    assert not is_path_allowed("docs/readme.md", ["ui/", "services/"])


def test_path_protected() -> None:
    assert is_path_protected("config/app.json", ["config/"])
    assert is_path_protected("settings.local.json", ["*.local.json"])
    assert not is_path_protected("ui/main.py", ["config/"])


def test_raw_url_correct() -> None:
    assert build_raw_url("owner", "repo", "main", "ui/main.py") == "https://raw.githubusercontent.com/owner/repo/main/ui/main.py"


def test_sha256_correct(tmp_path: Path) -> None:
    content = b"hello"
    path = tmp_path / "demo.txt"
    path.write_bytes(content)
    assert sha256_file(path) == sha256_bytes(content)


def test_filter_remote_files(tmp_path: Path) -> None:
    install_dir = make_install_dir(tmp_path)
    updater = GitHubSyncUpdater(
        make_config(install_dir),
        fetch_json=lambda url: fake_tree_payload(),
        fetch_bytes=fake_fetch_bytes_factory({"app_main.py": b"x", "ui/main.py": b"y"}),
    )
    check = updater.check()
    assert check.remote_allowed_count == 2
    assert check.protected_ignored_count == 1
    assert "docs/readme.md" in check.ignored_paths


def test_compare_new_same_modified(tmp_path: Path) -> None:
    install_dir = make_install_dir(tmp_path)
    (install_dir / "ui" / "main.py").write_bytes(b"same")
    config = make_config(install_dir)
    updater = GitHubSyncUpdater(
        config,
        fetch_json=lambda url: {"tree": [{"path": "ui/main.py", "type": "blob", "sha": "1"}, {"path": "services/new.py", "type": "blob", "sha": "2"}]},
        fetch_bytes=fake_fetch_bytes_factory({"ui/main.py": b"same", "services/new.py": b"new"}),
    )
    analysis = updater.analyze()
    statuses = {item.path: item.status for item in analysis.decisions}
    assert statuses["ui/main.py"] == "SAME"
    assert statuses["services/new.py"] == "NEW"

    (install_dir / "ui" / "main.py").write_bytes(b"local")
    analysis = updater.analyze()
    statuses = {item.path: item.status for item in analysis.decisions}
    assert statuses["ui/main.py"] == "MODIFIED"


def test_dry_run_does_not_modify_files(tmp_path: Path) -> None:
    install_dir = make_install_dir(tmp_path)
    target = install_dir / "ui" / "main.py"
    target.write_bytes(b"local")
    updater = GitHubSyncUpdater(
        make_config(install_dir),
        fetch_json=lambda url: {"tree": [{"path": "ui/main.py", "type": "blob", "sha": "1"}]},
        fetch_bytes=fake_fetch_bytes_factory({"ui/main.py": b"remote"}),
    )
    updater.dry_run()
    assert target.read_bytes() == b"local"


def test_apply_creates_staging_and_backup_and_updates_files(tmp_path: Path) -> None:
    install_dir = make_install_dir(tmp_path)
    existing = install_dir / "ui" / "main.py"
    existing.write_bytes(b"local")
    updater = GitHubSyncUpdater(
        make_config(install_dir),
        fetch_json=lambda url: {"tree": [{"path": "ui/main.py", "type": "blob", "sha": "1"}, {"path": "services/new.py", "type": "blob", "sha": "2"}]},
        fetch_bytes=fake_fetch_bytes_factory({"ui/main.py": b"remote", "services/new.py": b"new"}),
        now_factory=lambda: datetime(2026, 1, 2, 3, 4, 5),
    )
    result = updater.apply()
    assert result.applied is True
    assert result.staging_dir is not None and result.staging_dir.exists()
    assert result.backup_dir is not None and result.backup_dir.exists()
    assert existing.read_bytes() == b"remote"
    assert (install_dir / "services" / "new.py").read_bytes() == b"new"
    assert (result.backup_dir / "ui" / "main.py").read_bytes() == b"local"
    assert result.log_path is not None and result.log_path.exists()


def test_apply_respects_protected_paths_and_does_not_delete_obsolete(tmp_path: Path) -> None:
    install_dir = make_install_dir(tmp_path)
    protected = install_dir / "config"
    protected.mkdir()
    (protected / "app.json").write_text("keep", encoding="utf-8")
    obsolete = install_dir / "services" / "obsolete.py"
    obsolete.write_text("old", encoding="utf-8")
    updater = GitHubSyncUpdater(
        make_config(install_dir),
        fetch_json=lambda url: {"tree": [{"path": "config/app.json", "type": "blob", "sha": "1"}, {"path": "ui/main.py", "type": "blob", "sha": "2"}]},
        fetch_bytes=fake_fetch_bytes_factory({"ui/main.py": b"remote"}),
        now_factory=lambda: datetime(2026, 1, 2, 3, 4, 6),
    )
    result = updater.apply()
    assert result.analysis.protected_ignored_count == 0
    assert (protected / "app.json").read_text(encoding="utf-8") == "keep"
    assert obsolete.exists()


def test_rollback_restores_file_if_copy_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    install_dir = make_install_dir(tmp_path)
    existing = install_dir / "ui" / "main.py"
    existing.write_bytes(b"local")
    updater = GitHubSyncUpdater(
        make_config(install_dir),
        fetch_json=lambda url: {"tree": [{"path": "ui/main.py", "type": "blob", "sha": "1"}, {"path": "services/new.py", "type": "blob", "sha": "2"}]},
        fetch_bytes=fake_fetch_bytes_factory({"ui/main.py": b"remote", "services/new.py": b"new"}),
        now_factory=lambda: datetime(2026, 1, 2, 3, 4, 7),
    )
    calls = {"count": 0}

    def failing_copy(source: Path, target: Path) -> None:
        calls["count"] += 1
        if calls["count"] == 2:
            raise PermissionError("locked")
        target.write_bytes(source.read_bytes())

    monkeypatch.setattr(updater, "_copy_file", failing_copy)

    with pytest.raises(Exception):
        updater.apply()

    assert existing.read_bytes() == b"local"
    assert not (install_dir / "services" / "new.py").exists()


def test_logs_are_created(tmp_path: Path) -> None:
    install_dir = make_install_dir(tmp_path)
    updater = GitHubSyncUpdater(
        make_config(install_dir),
        fetch_json=lambda url: {"tree": [{"path": "ui/main.py", "type": "blob", "sha": "1"}]},
        fetch_bytes=fake_fetch_bytes_factory({"ui/main.py": b"remote"}),
        now_factory=lambda: datetime(2026, 1, 2, 3, 4, 8),
    )
    result = updater.apply()
    assert result.log_path is not None
    assert result.log_path.exists()
    assert "Repo:" in result.log_path.read_text(encoding="utf-8")
