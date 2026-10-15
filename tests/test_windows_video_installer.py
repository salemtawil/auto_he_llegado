from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
HELPER_PATH = PROJECT_ROOT / "packaging" / "windows" / "stage_drive_config.py"
SPEC = importlib.util.spec_from_file_location("stage_drive_config", HELPER_PATH)
assert SPEC is not None and SPEC.loader is not None
STAGER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(STAGER)


def test_oauth_client_is_staged_without_changing_source_env_or_shipping_token(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    private = tmp_path / "private" / "client.json"
    private.parent.mkdir()
    private.write_text('{"installed": {}}', encoding="utf-8")
    source_env = project / ".env"
    original = (
        "SUPABASE_URL=https://example.invalid\n"
        "GOOGLE_DRIVE_AUTH_MODE=oauth\n"
        "GOOGLE_DRIVE_FOLDER_ID=folder-id\n"
        f"GOOGLE_DRIVE_OAUTH_CLIENT_FILE={private}\n"
        "GOOGLE_DRIVE_OAUTH_TOKEN_FILE=C:/developer/private-token.json\n"
    )
    source_env.write_text(original, encoding="utf-8")
    stage = tmp_path / "stage"
    stage.mkdir()

    target = STAGER.stage_drive_config(source_env, project, stage)

    assert target == stage / "config" / "google_drive_oauth_client.json"
    assert target.read_bytes() == private.read_bytes()
    assert source_env.read_text(encoding="utf-8") == original
    staged_env = (stage / ".env").read_text(encoding="utf-8")
    assert "GOOGLE_DRIVE_OAUTH_CLIENT_FILE=config/google_drive_oauth_client.json" in staged_env
    assert "GOOGLE_DRIVE_OAUTH_TOKEN_FILE=local_data/google_drive_token.json" in staged_env
    assert str(private) not in staged_env
    assert not (stage / "local_data" / "google_drive_token.json").exists()


def test_service_account_path_is_resolved_from_project(tmp_path: Path) -> None:
    project = tmp_path / "project"
    private = project / "private" / "service.json"
    private.parent.mkdir(parents=True)
    private.write_text('{"type": "service_account"}', encoding="utf-8")
    source_env = project / ".env"
    source_env.write_text(
        "GOOGLE_DRIVE_AUTH_MODE=service_account\n"
        "GOOGLE_DRIVE_FOLDER_ID=folder-id\n"
        "GOOGLE_DRIVE_SERVICE_ACCOUNT_FILE=private/service.json\n",
        encoding="utf-8",
    )
    stage = tmp_path / "stage"
    stage.mkdir()

    target = STAGER.stage_drive_config(source_env, project, stage)

    assert target == stage / "config" / "google_drive_service_account.json"
    assert target.read_bytes() == private.read_bytes()
    assert (
        "GOOGLE_DRIVE_SERVICE_ACCOUNT_FILE=config/google_drive_service_account.json"
        in (stage / ".env").read_text(encoding="utf-8")
    )


def test_missing_drive_file_fails_before_any_staging(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    source_env = project / ".env"
    source_env.write_text(
        "GOOGLE_DRIVE_FOLDER_ID=folder-id\n"
        "GOOGLE_DRIVE_OAUTH_CLIENT_FILE=missing.json\n",
        encoding="utf-8",
    )
    stage = tmp_path / "stage"
    stage.mkdir()

    with pytest.raises(STAGER.DriveConfigError, match="GOOGLE_DRIVE_OAUTH_CLIENT_FILE"):
        STAGER.stage_drive_config(source_env, project, stage)

    assert list(stage.iterdir()) == []


def test_installer_includes_staged_drive_config_and_checks_imports() -> None:
    build_script = (
        PROJECT_ROOT / "packaging" / "windows" / "build_installer_windows.ps1"
    ).read_text(encoding="utf-8")
    inno_script = (
        PROJECT_ROOT / "packaging" / "windows" / "installer" / "auto_he_llegado.iss"
    ).read_text(encoding="utf-8")
    spec_script = (
        PROJECT_ROOT / "packaging" / "windows" / "auto_he_llegado.spec"
    ).read_text(encoding="utf-8")

    assert '"--stage-root", $DistAppRoot' in build_script
    assert "import googleapiclient.discovery" in build_script
    assert 'Source: "{#DistAppDir}\\config\\*"' in inno_script
    assert '"googleapiclient"' in spec_script
    assert '"google_auth_oauthlib"' in spec_script
