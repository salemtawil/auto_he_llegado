"""Regression tests for update-package path handling.

Both updaters take file paths from a remote source (a GitHub tree listing, or a
downloaded zip) and write them under the install directory. Before these tests a
crafted "../" entry escaped that directory (Zip Slip / path traversal).
"""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from updater.apply_update_helper import (
    UnsafeUpdatePathError,
    extract_package_zip,
    is_protected_path,
    normalize_relpath,
)
from updater.github_sync_updater import (
    is_path_allowed,
    is_path_protected,
    is_path_traversal,
    resolve_inside,
)


@pytest.mark.parametrize(
    "value",
    ["../evil.py", "a/../../evil.py", "..", "/etc/passwd", "//host/share/x", "C:/Windows/x"],
)
def test_normalize_relpath_rejects_escaping_paths(value: str) -> None:
    with pytest.raises(UnsafeUpdatePathError):
        normalize_relpath(value)


def test_normalize_relpath_keeps_ordinary_paths_and_directory_patterns() -> None:
    assert normalize_relpath("./ui/main_app/window.py") == "ui/main_app/window.py"
    assert normalize_relpath("ui\\main_app\\window.py") == "ui/main_app/window.py"
    # Trailing slash carries meaning for the protected-directory patterns.
    assert normalize_relpath("config/") == "config/"
    assert is_protected_path("config/settings.json") is True


def test_is_protected_path_blocks_traversal_instead_of_mangling_it() -> None:
    # Previously "../../.env".lstrip("./") became "env", which matched nothing.
    assert is_protected_path("../../.env") is True


def test_extract_package_zip_refuses_zip_slip(tmp_path: Path) -> None:
    package = tmp_path / "update.zip"
    with zipfile.ZipFile(package, "w") as archive:
        archive.writestr("ui/window.py", "ok")
        archive.writestr("../../pwned.py", "malicious")

    with pytest.raises(UnsafeUpdatePathError):
        extract_package_zip(package, tmp_path / "target")

    assert not (tmp_path.parent / "pwned.py").exists()


def test_extract_package_zip_still_extracts_a_clean_package(tmp_path: Path) -> None:
    package = tmp_path / "update.zip"
    with zipfile.ZipFile(package, "w") as archive:
        archive.writestr("payload/ui/window.py", "ok")

    extracted = extract_package_zip(package, tmp_path / "target")

    assert (extracted / "ui" / "window.py").read_text(encoding="utf-8") == "ok"


@pytest.mark.parametrize(
    "value", ["../x", "a/../../x", "/abs/x", "~/x", "C:/x", ""]
)
def test_is_path_traversal_flags_escaping_paths(value: str) -> None:
    assert is_path_traversal(value) is True


def test_is_path_traversal_accepts_normal_paths() -> None:
    assert is_path_traversal("ui/main_app/window.py") is False


def test_sync_path_rules_fail_closed_on_traversal() -> None:
    # "ui/../../../evil.py" used to pass is_path_allowed because it starts with "ui/".
    assert is_path_allowed("ui/../../../evil.py", ["ui/"]) is False
    assert is_path_allowed("ui/main_app/window.py", ["ui/"]) is True
    assert is_path_protected("ui/../../../.env", [".env"]) is True


def test_resolve_inside_contains_paths(tmp_path: Path) -> None:
    assert resolve_inside(tmp_path, "ui/window.py") == (tmp_path / "ui" / "window.py").resolve()
    with pytest.raises(ValueError):
        resolve_inside(tmp_path, "../escape.py")


# --------------------------------------------------------------------------
# Case-insensitive protected paths
#
# Windows and macOS resolve ".ENV" and ".env" to the same file, so a
# case-sensitive comparison let a protected path through under another spelling
# and the updater overwrote it.
# --------------------------------------------------------------------------


@pytest.mark.parametrize("value", [".env", ".ENV", ".Env", ".eNv"])
def test_protected_dotenv_is_matched_in_any_case(value: str) -> None:
    assert is_protected_path(value) is True


@pytest.mark.parametrize(
    "value",
    [
        "config/settings.json",
        "CONFIG/settings.json",
        "Config/Settings.json",
        "local_data/a.txt",
        "LOCAL_DATA/a.txt",
        "Local_Data/logs/x.log",
        "logs/app.log",
        "LOGS/app.log",
        "chrome_profiles/default/x",
        "CHROME_PROFILES/default/x",
        "updates/backups/x",
        "UPDATES/BACKUPS/x",
    ],
)
def test_protected_directories_are_matched_in_any_case(value: str) -> None:
    assert is_protected_path(value) is True


@pytest.mark.parametrize(
    "value",
    ["updater/updater_config.json", "updater/UPDATER_CONFIG.JSON", "Updater/Updater_Config.json"],
)
def test_protected_file_is_matched_in_any_case(value: str) -> None:
    assert is_protected_path(value) is True


@pytest.mark.parametrize("value", ["app.local.json", "App.LOCAL.json", "x/y/Z.Local.Json"])
def test_protected_glob_is_matched_in_any_case(value: str) -> None:
    assert is_protected_path(value) is True


@pytest.mark.parametrize(
    "value",
    [
        "config\\settings.json",
        "CONFIG\\Settings.json",
        "local_data\\temp\\a.txt",
        ".\\config\\settings.json",
    ],
)
def test_protected_paths_match_with_windows_separators(value: str) -> None:
    assert is_protected_path(value) is True


@pytest.mark.parametrize(
    "value",
    [
        "ui/main_app/window.py",
        "UI/main_app/Window.py",
        "ui\\main_app\\window.py",
        "automation/paripe_site.py",
        "requirements.txt",
        "configuration.py",  # not "config/" — a prefix match would be wrong
        "config_helper.py",
        "local_dataset.py",
    ],
)
def test_ordinary_paths_stay_unprotected(value: str) -> None:
    assert is_protected_path(value) is False


def test_dotfiles_keep_their_leading_dot_through_normalization() -> None:
    assert normalize_relpath(".gitignore") == ".gitignore"
    assert normalize_relpath("./.github/workflows/ci.yml") == ".github/workflows/ci.yml"
    assert normalize_relpath(".env.example") == ".env.example"
    # ".env.example" is a distinct file from the protected ".env"
    assert is_protected_path(".env.example") is False


@pytest.mark.parametrize("value", ["//host/share/x", "\\\\host\\share\\x"])
def test_unc_paths_are_rejected(value: str) -> None:
    with pytest.raises(UnsafeUpdatePathError):
        normalize_relpath(value)
    assert is_path_traversal(value) is True


# --------------------------------------------------------------------------
# Same rules on the GitHub sync side
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("path", "roots"),
    [("UI/main_app/window.py", ["ui/"]), ("ui/Main_App/Window.py", ["UI/"]), ("App_Main.py", ["app_main.py"])],
)
def test_sync_allowed_roots_are_case_insensitive(path: str, roots: list[str]) -> None:
    assert is_path_allowed(path, roots) is True


@pytest.mark.parametrize(
    ("path", "protected"),
    [
        (".ENV", [".env"]),
        ("CONFIG/settings.json", ["config/"]),
        ("Local_Data/x", ["local_data/"]),
        ("App.LOCAL.json", ["*.local.json"]),
    ],
)
def test_sync_protected_paths_are_case_insensitive(path: str, protected: list[str]) -> None:
    assert is_path_protected(path, protected) is True


def test_sync_ordinary_paths_are_not_protected() -> None:
    assert is_path_protected("ui/main_app/window.py", [".env", "config/"]) is False
    assert is_path_protected(".env.example", [".env"]) is False


def test_builtin_ignored_is_case_insensitive() -> None:
    from updater.github_sync_updater import BUILTIN_EXCLUDED_PREFIXES, is_builtin_ignored

    prefix = BUILTIN_EXCLUDED_PREFIXES[0]
    assert is_builtin_ignored(prefix + "x") is True
    assert is_builtin_ignored(prefix.upper() + "x") is True


# --------------------------------------------------------------------------
# Containment of staging / backup / install targets
# --------------------------------------------------------------------------


def test_resolve_inside_confines_staging_backup_and_install(tmp_path: Path) -> None:
    for root_name in ("staging", "backups", "install"):
        root = tmp_path / root_name
        root.mkdir()
        assert resolve_inside(root, "ui/main_app/window.py") == (
            root / "ui" / "main_app" / "window.py"
        ).resolve()
        # dotfiles must keep their name, not be relocated
        assert resolve_inside(root, ".env.example") == (root / ".env.example").resolve()
        for hostile in ("../escape.py", "a/../../escape.py", "/etc/passwd", "//host/share/x"):
            with pytest.raises(ValueError):
                resolve_inside(root, hostile)
