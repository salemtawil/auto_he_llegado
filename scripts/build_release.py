from __future__ import annotations

import shutil
import subprocess
import sys
import textwrap
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
BUILD_DIR = PROJECT_ROOT / "build"
DIST_DIR = PROJECT_ROOT / "dist"
RELEASE_ROOT = PROJECT_ROOT / "release"
WINDOWS_RELEASE_DIR = RELEASE_ROOT / "windows" / "AutoHeLlegadoPortable"
WINDOWS_SPEC_FILE = PROJECT_ROOT / "windows_portable.spec"


def main() -> int:
    _ensure_windows()
    _ensure_pyinstaller_available()
    _clean_outputs()
    _run_pyinstaller()
    _assemble_release_folder()
    _stage_playwright_browsers()
    _prepare_runtime_files()
    archive_path = _create_archive()
    print(f"Release listo en: {WINDOWS_RELEASE_DIR}")
    print(f"Zip listo en: {archive_path}")
    return 0


def _ensure_windows() -> None:
    if sys.platform != "win32":
        raise SystemExit("La build portable de Windows debe generarse en Windows.")


def _ensure_pyinstaller_available() -> None:
    try:
        import PyInstaller  # noqa: F401
    except ImportError as exc:
        raise SystemExit(
            "PyInstaller no esta instalado en este entorno. Ejecuta:\n"
            "  .\\.venv\\Scripts\\python.exe -m pip install pyinstaller"
        ) from exc


def _clean_outputs() -> None:
    for path in (BUILD_DIR, DIST_DIR, WINDOWS_RELEASE_DIR):
        if path.exists():
            shutil.rmtree(path)
    WINDOWS_RELEASE_DIR.parent.mkdir(parents=True, exist_ok=True)


def _run_pyinstaller() -> None:
    subprocess.run(
        [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", str(WINDOWS_SPEC_FILE)],
        cwd=PROJECT_ROOT,
        check=True,
    )


def _assemble_release_folder() -> None:
    built_dir = DIST_DIR / "AutoHeLlegadoPortable"
    if not built_dir.exists():
        raise RuntimeError(f"No se encontro la salida de PyInstaller: {built_dir}")
    shutil.copytree(built_dir, WINDOWS_RELEASE_DIR)


def _stage_playwright_browsers() -> None:
    source_cache = Path.home() / "AppData" / "Local" / "ms-playwright"
    target_dir = WINDOWS_RELEASE_DIR / "ms-playwright"
    if target_dir.exists():
        shutil.rmtree(target_dir)
    if not source_cache.exists() or not any(source_cache.iterdir()):
        raise SystemExit(
            "No se encontro la cache local de Playwright en AppData\\Local\\ms-playwright.\n"
            "Ejecuta antes: .\\.venv\\Scripts\\python.exe -m playwright install chromium"
        )
    shutil.copytree(source_cache, target_dir)


def _prepare_runtime_files() -> None:
    _copy_env_files()
    _create_local_directories()
    _write_run_scripts()
    _write_readme()


def _copy_env_files() -> None:
    env_example = PROJECT_ROOT / ".env.example"
    if env_example.exists():
        shutil.copy2(env_example, WINDOWS_RELEASE_DIR / ".env.example")
    env_file = PROJECT_ROOT / ".env"
    if env_file.exists():
        shutil.copy2(env_file, WINDOWS_RELEASE_DIR / ".env")
    elif env_example.exists():
        shutil.copy2(env_example, WINDOWS_RELEASE_DIR / ".env")


def _create_local_directories() -> None:
    for relative in (
        "local_data",
        "local_data/config",
        "local_data/logs",
        "local_data/failed_uploads",
        "local_data/temp",
        "local_data/temp_photos",
        "local_data/debug",
        "local_data/results",
        "local_data/results/screenshots",
    ):
        (WINDOWS_RELEASE_DIR / relative).mkdir(parents=True, exist_ok=True)


def _write_run_scripts() -> None:
    scripts = {
        "run_main.bat": "app_main.exe",
        "run_uploader.bat": "app_uploader.exe",
        "run_debug.bat": "app_debug_inspector.exe",
    }
    for filename, binary_name in scripts.items():
        content = textwrap.dedent(
            f"""\
            @echo off
            setlocal
            cd /d "%~dp0"
            set "PLAYWRIGHT_BROWSERS_PATH=%~dp0ms-playwright"
            start "" "%~dp0{binary_name}"
            """
        )
        (WINDOWS_RELEASE_DIR / filename).write_text(content, encoding="utf-8", newline="\r\n")


def _write_readme() -> None:
    readme = textwrap.dedent(
        """\
        AUTO HE LLEGADO - WINDOWS PORTABLE
        =================================

        Como abrir la app
        1. Copia la carpeta completa AutoHeLlegadoPortable a la PC de prueba.
        2. Revisa el archivo .env.
        3. Ejecuta run_main.bat.

        Archivos principales
        - app_main.exe: app principal
        - app_uploader.exe: carga de fotos
        - app_debug_inspector.exe: inspector/debug
        - run_main.bat / run_uploader.bat / run_debug.bat: lanzadores
        - .env.example: plantilla de configuracion
        - .env: configuracion activa usada por la app
        - ms-playwright/: Chromium portable para Playwright

        Que hacer con .env
        - Si necesitas cambiar configuracion, edita .env.
        - Si solo existe .env.example, renombralo a .env y completa:
          SUPABASE_URL
          SUPABASE_KEY
          SUPABASE_STORAGE_BUCKET
          SUPABASE_PHOTOS_TABLE
          SUPABASE_PROCESS_LOGS_TABLE
          ADMIN_ACCESS_PASSWORD

        Requisitos en la PC de prueba
        - No hace falta instalar Python.
        - Si hace falta acceso real a los sitios y a Supabase, la PC debe tener internet.

        Donde revisar errores basicos
        - local_data/logs
        - local_data/debug
        - local_data/results

        Notas
        - No borres la carpeta ms-playwright.
        - La app guarda datos locales dentro de local_data.
        """
    )
    (WINDOWS_RELEASE_DIR / "README_WINDOWS.txt").write_text(readme, encoding="utf-8", newline="\r\n")


def _create_archive() -> Path:
    archive_base = WINDOWS_RELEASE_DIR.parent / "AutoHeLlegadoPortableWindows"
    zip_path = archive_base.with_suffix(".zip")
    if zip_path.exists():
        zip_path.unlink()
    archive_file = shutil.make_archive(
        str(archive_base),
        "zip",
        root_dir=WINDOWS_RELEASE_DIR.parent,
        base_dir=WINDOWS_RELEASE_DIR.name,
    )
    return Path(archive_file)


if __name__ == "__main__":
    raise SystemExit(main())
