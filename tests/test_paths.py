from __future__ import annotations

from pathlib import Path

import config.paths as paths


def test_installed_macos_app_uses_application_support(monkeypatch, tmp_path: Path) -> None:
    support_dir = tmp_path / "Application Support" / "AutoHeLlegado"
    monkeypatch.setenv("AUTO_HE_LLEGADO_APP_SUPPORT_DIR", str(support_dir))
    monkeypatch.delenv("AUTO_HE_LLEGADO_RUNTIME_ROOT", raising=False)
    monkeypatch.setattr(paths.sys, "platform", "darwin")
    monkeypatch.setattr(paths.sys, "frozen", True, raising=False)
    monkeypatch.setattr(paths.sys, "executable", "/Applications/AutoHeLlegado.app/Contents/MacOS/AutoHeLlegado")

    assert paths._resolve_runtime_root() == support_dir.resolve()  # noqa: SLF001


def test_portable_macos_app_uses_folder_next_to_bundle(monkeypatch, tmp_path: Path) -> None:
    portable_root = tmp_path / "AutoHeLlegadoMac"
    executable = portable_root / "AutoHeLlegado.app" / "Contents" / "MacOS" / "AutoHeLlegado"
    monkeypatch.delenv("AUTO_HE_LLEGADO_APP_SUPPORT_DIR", raising=False)
    monkeypatch.delenv("AUTO_HE_LLEGADO_RUNTIME_ROOT", raising=False)
    monkeypatch.setattr(paths.sys, "platform", "darwin")
    monkeypatch.setattr(paths.sys, "frozen", True, raising=False)
    monkeypatch.setattr(paths.sys, "executable", str(executable))

    assert paths._resolve_runtime_root() == portable_root.resolve()  # noqa: SLF001


def test_runtime_root_override_wins(monkeypatch, tmp_path: Path) -> None:
    runtime_root = tmp_path / "custom-runtime"
    monkeypatch.setenv("AUTO_HE_LLEGADO_RUNTIME_ROOT", str(runtime_root))
    monkeypatch.setattr(paths.sys, "frozen", True, raising=False)

    assert paths._resolve_runtime_root() == runtime_root.resolve()  # noqa: SLF001
