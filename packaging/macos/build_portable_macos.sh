#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
SPEC_PATH="$SCRIPT_DIR/auto_he_llegado_macos.spec"
BUILD_ROOT="$PROJECT_ROOT/build/portable_macos"
DIST_ROOT="$PROJECT_ROOT/dist"
APP_OUTPUT="$DIST_ROOT/AutoHeLlegado.app"
PORTABLE_ROOT="$DIST_ROOT/AutoHeLlegadoMac"
RELEASES_ROOT="$PROJECT_ROOT/releases"
TIMESTAMP="$(date +"%Y%m%d_%H%M%S")"
MACOS_TARGET_ARCH="${MACOS_TARGET_ARCH:-x86_64}"
export MACOS_TARGET_ARCH
ZIP_PATH="$RELEASES_ROOT/AutoHeLlegado_Mac_${MACOS_TARGET_ARCH}_Portable_${TIMESTAMP}.zip"

run_step() {
  local label="$1"
  shift
  echo
  echo "==> $label"
  "$@"
}

find_base_python() {
  if [ -n "${PYTHON_BIN:-}" ]; then
    echo "$PYTHON_BIN"
    return
  fi
  for candidate in python3.12 python3.11 python3; do
    if command -v "$candidate" >/dev/null 2>&1; then
      echo "$candidate"
      return
    fi
  done
  echo "python3"
}

assert_supported_python() {
  local python_bin="$1"
  "$python_bin" - <<'PY'
from __future__ import annotations

import sys

if sys.version_info >= (3, 13):
    raise SystemExit(
        "Python 3.13+ no esta soportado para el build Mac por conflictos binarios "
        "con cryptography/OpenSSL. Usa Python 3.12 o 3.11."
    )
if sys.version_info < (3, 11):
    raise SystemExit("Usa Python 3.11 o 3.12 para generar el paquete Mac.")
PY
}

assert_tkinter_available() {
  local python_bin="$1"
  "$python_bin" - <<'PY'
from __future__ import annotations

try:
    import tkinter  # noqa: F401
except Exception as exc:
    raise SystemExit(
        "Este Python no tiene tkinter/Tk disponible. Instala Python 3.12 desde python.org "
        "o, si usas Homebrew, instala python-tk@3.12. Error: "
        f"{exc}"
    ) from exc
PY
}

assert_path_exists() {
  local path_value="$1"
  local message="$2"
  if [ ! -e "$path_value" ]; then
    echo "$message" >&2
    exit 1
  fi
}

copy_tree() {
  local source_dir="$1"
  local target_dir="$2"
  rm -rf "$target_dir"
  mkdir -p "$target_dir"
  rsync -a \
    --exclude "__pycache__" \
    --exclude "*.pyc" \
    --exclude ".pytest_cache" \
    "$source_dir/" "$target_dir/"
}

write_macos_updater_config() {
  local source_path="$1"
  local target_path="$2"
  "$PYTHON" - "$source_path" "$target_path" <<'PY'
from __future__ import annotations

import json
import sys
from pathlib import Path

source = Path(sys.argv[1])
target = Path(sys.argv[2])
payload = json.loads(source.read_text(encoding="utf-8-sig"))
payload["app_entrypoints"] = ["AutoHeLlegado.app"]
target.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
PY
}

cd "$PROJECT_ROOT"

PYTHON="$(find_base_python)"
run_step "Verificando Python" "$PYTHON" --version
assert_supported_python "$PYTHON"
assert_tkinter_available "$PYTHON"

if [ "${AUTO_VENV:-1}" = "1" ] && [ ! -x "$PROJECT_ROOT/.venv/bin/python" ]; then
  run_step "Creando entorno virtual .venv" "$PYTHON" -m venv "$PROJECT_ROOT/.venv"
  PYTHON="$PROJECT_ROOT/.venv/bin/python"
  run_step "Verificando Python del entorno virtual" "$PYTHON" --version
elif [ -x "$PROJECT_ROOT/.venv/bin/python" ]; then
  PYTHON="$PROJECT_ROOT/.venv/bin/python"
  run_step "Verificando Python del entorno virtual" "$PYTHON" --version
fi
assert_supported_python "$PYTHON"
assert_tkinter_available "$PYTHON"

if [ "${SKIP_DEP_INSTALL:-0}" != "1" ]; then
  run_step "Actualizando pip" "$PYTHON" -m pip install --upgrade pip
  run_step "Instalando dependencias" "$PYTHON" -m pip install -r requirements.txt -c packaging/macos/constraints-macos.txt pyinstaller
fi

if [ "${SKIP_TESTS:-0}" != "1" ]; then
  run_step "Ejecutando tests" "$PYTHON" -m pytest tests -q
fi

run_step "Compilando archivos Python clave" "$PYTHON" -m py_compile \
  app_main.py \
  updater/github_sync_updater.py \
  updater/apply_update_helper.py \
  updater/release_update_client.py \
  ui/main_app/window.py \
  automation/browser_manager.py

run_step "Verificando PyInstaller" "$PYTHON" -m PyInstaller --version

run_step "Instalando Chromium de Playwright si falta" "$PYTHON" -m playwright install chromium

PLAYWRIGHT_CACHE="${PLAYWRIGHT_BROWSERS_PATH:-$HOME/Library/Caches/ms-playwright}"
assert_path_exists "$PLAYWRIGHT_CACHE" "No se encontro la cache de Playwright en $PLAYWRIGHT_CACHE."

run_step "Limpiando salidas anteriores" rm -rf "$BUILD_ROOT" "$APP_OUTPUT" "$PORTABLE_ROOT"
mkdir -p "$DIST_ROOT" "$RELEASES_ROOT"

PYINSTALLER_ARGS=(
  -m PyInstaller
  --noconfirm
  --clean
  --distpath "$DIST_ROOT"
  --workpath "$BUILD_ROOT"
)

PYINSTALLER_ARGS+=("$SPEC_PATH")

run_step "Generando AutoHeLlegado.app ($MACOS_TARGET_ARCH)" "$PYTHON" "${PYINSTALLER_ARGS[@]}"

assert_path_exists "$APP_OUTPUT" "No se genero $APP_OUTPUT."

run_step "Armando carpeta portable" mkdir -p "$PORTABLE_ROOT"
cp -R "$APP_OUTPUT" "$PORTABLE_ROOT/AutoHeLlegado.app"

copy_tree "$PROJECT_ROOT/browser_extension" "$PORTABLE_ROOT/browser_extension"
copy_tree "$PROJECT_ROOT/sql" "$PORTABLE_ROOT/sql"
copy_tree "$PROJECT_ROOT/updater" "$PORTABLE_ROOT/updater"
copy_tree "$PLAYWRIGHT_CACHE" "$PORTABLE_ROOT/ms-playwright"

if [ -f "$PROJECT_ROOT/.env.example" ]; then
  cp "$PROJECT_ROOT/.env.example" "$PORTABLE_ROOT/.env.example"
fi

if [ -f "$PROJECT_ROOT/.env" ]; then
  cp "$PROJECT_ROOT/.env" "$PORTABLE_ROOT/.env"
elif [ -f "$PROJECT_ROOT/.env.example" ]; then
  cp "$PROJECT_ROOT/.env.example" "$PORTABLE_ROOT/.env"
fi

mkdir -p \
  "$PORTABLE_ROOT/logs" \
  "$PORTABLE_ROOT/exports" \
  "$PORTABLE_ROOT/updates" \
  "$PORTABLE_ROOT/local_data/config" \
  "$PORTABLE_ROOT/local_data/logs" \
  "$PORTABLE_ROOT/local_data/debug" \
  "$PORTABLE_ROOT/local_data/results/screenshots" \
  "$PORTABLE_ROOT/local_data/failed_uploads" \
  "$PORTABLE_ROOT/local_data/temp_photos"

write_macos_updater_config \
  "$PROJECT_ROOT/updater/updater_config.example.json" \
  "$PORTABLE_ROOT/updater/updater_config.example.json"

if [ -f "$PROJECT_ROOT/updater/updater_config.json" ]; then
  write_macos_updater_config \
    "$PROJECT_ROOT/updater/updater_config.json" \
    "$PORTABLE_ROOT/updater/updater_config.json"
fi

chmod +x "$PORTABLE_ROOT/updater/launchers/ActualizarApp.command" || true
xattr -cr "$PORTABLE_ROOT" 2>/dev/null || true

if [ "${SKIP_CODESIGN:-0}" != "1" ] && command -v codesign >/dev/null 2>&1; then
  run_step "Firmando localmente con ad-hoc codesign" codesign --force --deep --sign - "$PORTABLE_ROOT/AutoHeLlegado.app"
fi

run_step "Validando contenido portable" test -d "$PORTABLE_ROOT/AutoHeLlegado.app"
assert_path_exists "$PORTABLE_ROOT/browser_extension/manifest.json" "Falta browser_extension/manifest.json."
assert_path_exists "$PORTABLE_ROOT/updater/github_sync_updater.py" "Falta updater/github_sync_updater.py."
assert_path_exists "$PORTABLE_ROOT/updater/apply_update_helper.py" "Falta updater/apply_update_helper.py."
assert_path_exists "$PORTABLE_ROOT/updater/release_update_client.py" "Falta updater/release_update_client.py."
assert_path_exists "$PORTABLE_ROOT/updater/launchers/ActualizarApp.command" "Falta ActualizarApp.command."
assert_path_exists "$PORTABLE_ROOT/ms-playwright" "Falta ms-playwright."

echo
echo "==> Generando zip final"
rm -f "$ZIP_PATH"
(
  cd "$DIST_ROOT"
  ditto -c -k --sequesterRsrc --keepParent "AutoHeLlegadoMac" "$ZIP_PATH"
)
assert_path_exists "$ZIP_PATH" "No se genero el zip final."

echo
echo "Paquete Mac generado:"
echo "  $PORTABLE_ROOT"
echo "Zip final:"
echo "  $ZIP_PATH"
