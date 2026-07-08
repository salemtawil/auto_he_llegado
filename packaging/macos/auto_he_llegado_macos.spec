# -*- mode: python ; coding: utf-8 -*-
from __future__ import annotations

import os
from pathlib import Path

from PyInstaller.building.build_main import Analysis, BUNDLE, COLLECT, EXE, PYZ
from PyInstaller.utils.hooks import collect_all


PROJECT_ROOT = Path.cwd()
TARGET_ARCH = os.environ.get("MACOS_TARGET_ARCH") or None


datas: list[tuple[str, str]] = []
binaries: list[tuple[str, str, str]] = []
hiddenimports: list[str] = []

packages_to_collect = (
    "customtkinter",
    "playwright",
    "dotenv",
    "supabase",
    "postgrest",
    "storage3",
    "realtime",
    "httpx",
    "httpcore",
    "pydantic",
    "pydantic_core",
    "cv2",
    "numpy",
)

for package_name in packages_to_collect:
    package_datas, package_binaries, package_hiddenimports = collect_all(package_name)
    datas += package_datas
    binaries += package_binaries
    hiddenimports += package_hiddenimports

analysis = Analysis(
    [str(PROJECT_ROOT / "app_main.py")],
    pathex=[str(PROJECT_ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(analysis.pure)
exe = EXE(
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="AutoHeLlegado",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    target_arch=TARGET_ARCH,
)
coll = COLLECT(
    exe,
    analysis.binaries,
    analysis.zipfiles,
    analysis.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="AutoHeLlegado",
)
app = BUNDLE(
    coll,
    name="AutoHeLlegado.app",
    icon=None,
    bundle_identifier="com.autohellegado.app",
    info_plist={
        "CFBundleName": "Auto He Llegado",
        "CFBundleDisplayName": "Auto He Llegado",
        "CFBundleShortVersionString": "1.0.0",
        "CFBundleVersion": "1.0.0",
        "NSHighResolutionCapable": True,
    },
)
