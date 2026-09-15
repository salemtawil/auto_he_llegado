from pathlib import Path


PROJECT_ROOT = Path(__file__).parents[1]
BUILD_SCRIPT = PROJECT_ROOT / "packaging" / "macos" / "build_installer_macos.sh"


def test_installer_validates_google_drive_configuration() -> None:
    script = BUILD_SCRIPT.read_text(encoding="utf-8")

    assert 'values.get("GOOGLE_DRIVE_FOLDER_ID", "").strip()' in script
    assert '"GOOGLE_DRIVE_OAUTH_CLIENT_FILE"' in script
    assert '"GOOGLE_DRIVE_SERVICE_ACCOUNT_FILE"' in script
    assert "credentials_path.is_file()" in script


def test_postinstall_replaces_env_and_keeps_backup() -> None:
    script = BUILD_SCRIPT.read_text(encoding="utf-8")

    assert 'cp -p "$SUPPORT_DIR/.env" "$SUPPORT_DIR/.env.backup"' in script
    assert 'cp "$PAYLOAD_ROOT/.env" "$SUPPORT_DIR/.env"' in script
    assert "env_needs_install" not in script
