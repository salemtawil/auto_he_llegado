from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_packaging_does_not_download_or_bundle_chromium() -> None:
    packaging_files = (
        PROJECT_ROOT / "packaging" / "macos" / "build_installer_macos.sh",
        PROJECT_ROOT / "packaging" / "macos" / "build_portable_macos.sh",
        PROJECT_ROOT / "packaging" / "windows" / "build_installer_windows.ps1",
        PROJECT_ROOT / "packaging" / "windows" / "build_portable_windows.ps1",
        PROJECT_ROOT / "packaging" / "windows" / "installer" / "auto_he_llegado.iss",
        PROJECT_ROOT / "scripts" / "build_release.py",
    )

    for path in packaging_files:
        contents = path.read_text(encoding="utf-8")
        assert "playwright install chromium" not in contents.lower(), path
        assert "playwright_browsers_path" not in contents.lower(), path
        legacy_cache_lines = [
            line.strip().lower()
            for line in contents.splitlines()
            if "ms-playwright" in line.lower()
        ]
        assert all(
            "rm -rf" in line or "type: filesandordirs" in line
            for line in legacy_cache_lines
        ), path


def test_browser_launches_explicit_google_chrome_channel() -> None:
    inspector = (PROJECT_ROOT / "debug_tools" / "inspector_service.py").read_text(encoding="utf-8")

    assert 'launch(channel="chrome", headless=False)' in inspector
