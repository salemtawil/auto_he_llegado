# -*- mode: python ; coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path

from PyInstaller.building.build_main import Analysis, COLLECT, EXE, PYZ
from PyInstaller.utils.hooks import collect_all


PROJECT_ROOT = Path.cwd()


def collect_tree(source_dir: Path, destination_root: str) -> list[tuple[str, str]]:
    if not source_dir.exists():
        return []

    excluded_dir_names = {".git", ".venv", "__pycache__", ".pytest_cache"}
    excluded_suffixes = {".pyc", ".pyo"}
    datas: list[tuple[str, str]] = []

    for path in source_dir.rglob("*"):
        if not path.is_file():
            continue
        if any(part in excluded_dir_names for part in path.parts):
            continue
        if path.suffix.lower() in excluded_suffixes:
            continue
        relative_parent = path.relative_to(source_dir).parent
        target_dir = Path(destination_root) / relative_parent
        datas.append((str(path), str(target_dir).replace("\\", "/")))
    return datas


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

if (PROJECT_ROOT / ".env.example").exists():
    datas.append((str(PROJECT_ROOT / ".env.example"), "."))

datas += collect_tree(PROJECT_ROOT / "browser_extension", "browser_extension")
datas += collect_tree(PROJECT_ROOT / "sql", "sql")
datas += collect_tree(PROJECT_ROOT / "updater" / "launchers", "updater/launchers")

updater_files = (
    PROJECT_ROOT / "updater" / "github_sync_updater.py",
    PROJECT_ROOT / "updater" / "apply_update_helper.py",
    PROJECT_ROOT / "updater" / "README.md",
    PROJECT_ROOT / "updater" / "updater_config.example.json",
)
for updater_file in updater_files:
    if updater_file.exists():
        datas.append((str(updater_file), "updater"))

analysis_kwargs = dict(
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


def build_executable(script_name: str, exe_name: str):
    analysis = Analysis([str(PROJECT_ROOT / script_name)], **analysis_kwargs)
    pyz = PYZ(analysis.pure)
    exe = EXE(
        pyz,
        analysis.scripts,
        [],
        exclude_binaries=True,
        name=exe_name,
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=False,
        console=False,
    )
    return analysis, exe


a_main, exe_main = build_executable("app_main.py", "AutoHeLlegado")
a_uploader, exe_uploader = build_executable("app_uploader.py", "AutoHeLlegadoUploader")
a_debug, exe_debug = build_executable("app_debug_inspector.py", "AutoHeLlegadoDebugInspector")
a_helper, exe_helper = build_executable("app_update_helper.py", "AutoHeLlegadoUpdateHelper")

coll = COLLECT(
    exe_main,
    exe_uploader,
    exe_debug,
    exe_helper,
    a_main.binaries,
    a_main.datas,
    a_uploader.binaries,
    a_uploader.datas,
    a_debug.binaries,
    a_debug.datas,
    a_helper.binaries,
    a_helper.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="AutoHeLlegado",
)
