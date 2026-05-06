# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path

from PyInstaller.building.build_main import Analysis, COLLECT, EXE, PYZ
from PyInstaller.utils.hooks import collect_all


project_root = Path.cwd()

datas = []
binaries = []
hiddenimports = []

packages_to_collect = (
    "customtkinter",
    "playwright",
    "dotenv",
    "supabase",
    "postgrest",
    "storage3",
    "gotrue",
    "realtime",
    "httpx",
    "httpcore",
    "pydantic",
    "pydantic_core",
)

for package_name in packages_to_collect:
    package_datas, package_binaries, package_hiddenimports = collect_all(package_name)
    datas += package_datas
    binaries += package_binaries
    hiddenimports += package_hiddenimports

datas += [
    (str(project_root / ".env.example"), "."),
]

analysis_kwargs = dict(
    pathex=[str(project_root)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

a_main = Analysis(["app_main.py"], **analysis_kwargs)
pyz_main = PYZ(a_main.pure)
exe_main = EXE(
    pyz_main,
    a_main.scripts,
    [],
    exclude_binaries=True,
    name="app_main",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
)

a_uploader = Analysis(["app_uploader.py"], **analysis_kwargs)
pyz_uploader = PYZ(a_uploader.pure)
exe_uploader = EXE(
    pyz_uploader,
    a_uploader.scripts,
    [],
    exclude_binaries=True,
    name="app_uploader",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
)

a_debug = Analysis(["app_debug_inspector.py"], **analysis_kwargs)
pyz_debug = PYZ(a_debug.pure)
exe_debug = EXE(
    pyz_debug,
    a_debug.scripts,
    [],
    exclude_binaries=True,
    name="app_debug_inspector",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
)

coll = COLLECT(
    exe_main,
    exe_uploader,
    exe_debug,
    a_main.binaries,
    a_main.datas,
    a_uploader.binaries,
    a_uploader.datas,
    a_debug.binaries,
    a_debug.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="AutoHeLlegadoPortable",
)
