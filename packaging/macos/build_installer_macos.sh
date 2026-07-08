#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
SPEC_PATH="$SCRIPT_DIR/auto_he_llegado_macos.spec"
BUILD_ROOT="$PROJECT_ROOT/build/installer_macos"
DIST_ROOT="$PROJECT_ROOT/dist"
APP_OUTPUT="$DIST_ROOT/AutoHeLlegado.app"
RELEASES_ROOT="$PROJECT_ROOT/releases"
PKG_ROOT="$BUILD_ROOT/pkg_root"
PKG_SCRIPTS="$BUILD_ROOT/pkg_scripts"
PAYLOAD_ROOT="$PKG_ROOT/private/tmp/AutoHeLlegadoInstallerPayload"
VERSION="${AUTO_HE_LLEGADO_VERSION:-1.0.0}"
TIMESTAMP="$(date +"%Y%m%d_%H%M%S")"
MACOS_TARGET_ARCH="${MACOS_TARGET_ARCH:-x86_64}"
export MACOS_TARGET_ARCH
PKG_PATH="$RELEASES_ROOT/AutoHeLlegado_Mac_${MACOS_TARGET_ARCH}_Installer_${VERSION}_${TIMESTAMP}.pkg"
UPDATE_ZIP_PATH="$RELEASES_ROOT/AutoHeLlegado_Mac_${MACOS_TARGET_ARCH}_Update_${VERSION}_${TIMESTAMP}.zip"

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
    raise SystemExit("Usa Python 3.11 o 3.12 para generar el instalador Mac.")
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

write_installed_updater_config() {
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
payload["install_dir"] = "~/Library/Application Support/AutoHeLlegado"
payload["app_entrypoints"] = ["AutoHeLlegado.app"]
payload["protected_paths"] = sorted(
    set(payload.get("protected_paths") or [])
    | {
        ".env",
        "local_data/",
        "logs/",
        "exports/",
        "updates/",
        "ms-playwright/",
    }
)
target.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
PY
}

write_postinstall_script() {
  local target_path="$1"
  cat > "$target_path" <<'SH'
#!/bin/bash
set -euo pipefail

APP_NAME="AutoHeLlegado"
PAYLOAD_ROOT="/private/tmp/AutoHeLlegadoInstallerPayload"
CONSOLE_USER="$(/usr/bin/stat -f %Su /dev/console)"

if [ -z "$CONSOLE_USER" ] || [ "$CONSOLE_USER" = "root" ]; then
  echo "No se pudo detectar el usuario de consola." >&2
  exit 1
fi

USER_HOME="$(/usr/bin/dscl . -read "/Users/$CONSOLE_USER" NFSHomeDirectory | /usr/bin/awk '{print $2}')"
SUPPORT_DIR="$USER_HOME/Library/Application Support/$APP_NAME"
APP_TARGET="/Applications/AutoHeLlegado.app"

/bin/mkdir -p "$SUPPORT_DIR"

if [ -d "$PAYLOAD_ROOT/AutoHeLlegado.app" ]; then
  /bin/rm -rf "$APP_TARGET"
  /bin/cp -R "$PAYLOAD_ROOT/AutoHeLlegado.app" "$APP_TARGET"
  /usr/sbin/chown -R "$CONSOLE_USER":staff "$APP_TARGET"
fi

copy_dir() {
  local name="$1"
  if [ -d "$PAYLOAD_ROOT/$name" ]; then
    /bin/rm -rf "$SUPPORT_DIR/$name"
    /bin/cp -R "$PAYLOAD_ROOT/$name" "$SUPPORT_DIR/$name"
  fi
}

copy_dir "browser_extension"
copy_dir "sql"
copy_dir "updater"
copy_dir "ms-playwright"

if [ -f "$PAYLOAD_ROOT/.env.example" ]; then
  /bin/cp "$PAYLOAD_ROOT/.env.example" "$SUPPORT_DIR/.env.example"
fi

if [ ! -f "$SUPPORT_DIR/.env" ]; then
  if [ -f "$PAYLOAD_ROOT/.env" ]; then
    /bin/cp "$PAYLOAD_ROOT/.env" "$SUPPORT_DIR/.env"
  elif [ -f "$PAYLOAD_ROOT/.env.example" ]; then
    /bin/cp "$PAYLOAD_ROOT/.env.example" "$SUPPORT_DIR/.env"
  fi
fi

/bin/mkdir -p \
  "$SUPPORT_DIR/logs" \
  "$SUPPORT_DIR/exports" \
  "$SUPPORT_DIR/updates" \
  "$SUPPORT_DIR/local_data/config" \
  "$SUPPORT_DIR/local_data/logs" \
  "$SUPPORT_DIR/local_data/debug" \
  "$SUPPORT_DIR/local_data/results/screenshots" \
  "$SUPPORT_DIR/local_data/failed_uploads" \
  "$SUPPORT_DIR/local_data/temp_photos"

/usr/sbin/chown -R "$CONSOLE_USER":staff "$SUPPORT_DIR"
/bin/chmod +x "$SUPPORT_DIR/updater/launchers/ActualizarApp.command" 2>/dev/null || true
/usr/bin/xattr -dr com.apple.quarantine "/Applications/AutoHeLlegado.app" 2>/dev/null || true
/bin/rm -rf "$PAYLOAD_ROOT"

exit 0
SH
  chmod +x "$target_path"
}

cd "$PROJECT_ROOT"

PYTHON="$(find_base_python)"
run_step "Verificando macOS" test "$(uname -s)" = "Darwin"
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
  config/paths.py \
  updater/github_sync_updater.py \
  updater/apply_update_helper.py \
  updater/release_update_client.py \
  ui/main_app/window.py \
  automation/browser_manager.py

run_step "Verificando PyInstaller" "$PYTHON" -m PyInstaller --version
run_step "Instalando Chromium de Playwright si falta" "$PYTHON" -m playwright install chromium

PLAYWRIGHT_CACHE="${PLAYWRIGHT_BROWSERS_PATH:-$HOME/Library/Caches/ms-playwright}"
assert_path_exists "$PLAYWRIGHT_CACHE" "No se encontro la cache de Playwright en $PLAYWRIGHT_CACHE."

run_step "Limpiando salidas anteriores" rm -rf "$BUILD_ROOT" "$APP_OUTPUT"
mkdir -p "$DIST_ROOT" "$RELEASES_ROOT"

PYINSTALLER_ARGS=(
  -m PyInstaller
  --noconfirm
  --clean
  --distpath "$DIST_ROOT"
  --workpath "$BUILD_ROOT/pyinstaller"
)

PYINSTALLER_ARGS+=("$SPEC_PATH")

run_step "Generando AutoHeLlegado.app ($MACOS_TARGET_ARCH)" "$PYTHON" "${PYINSTALLER_ARGS[@]}"
assert_path_exists "$APP_OUTPUT" "No se genero $APP_OUTPUT."

run_step "Preparando payload del instalador" mkdir -p "$PKG_ROOT/Applications" "$PAYLOAD_ROOT" "$PKG_SCRIPTS"
cp -R "$APP_OUTPUT" "$PKG_ROOT/Applications/AutoHeLlegado.app"
cp -R "$APP_OUTPUT" "$PAYLOAD_ROOT/AutoHeLlegado.app"

copy_tree "$PROJECT_ROOT/browser_extension" "$PAYLOAD_ROOT/browser_extension"
copy_tree "$PROJECT_ROOT/sql" "$PAYLOAD_ROOT/sql"
copy_tree "$PROJECT_ROOT/updater" "$PAYLOAD_ROOT/updater"
copy_tree "$PLAYWRIGHT_CACHE" "$PAYLOAD_ROOT/ms-playwright"

if [ -f "$PROJECT_ROOT/.env.example" ]; then
  cp "$PROJECT_ROOT/.env.example" "$PAYLOAD_ROOT/.env.example"
fi

if [ -f "$PROJECT_ROOT/.env" ]; then
  cp "$PROJECT_ROOT/.env" "$PAYLOAD_ROOT/.env"
elif [ -f "$PROJECT_ROOT/.env.example" ]; then
  cp "$PROJECT_ROOT/.env.example" "$PAYLOAD_ROOT/.env"
fi

write_installed_updater_config \
  "$PROJECT_ROOT/updater/updater_config.example.json" \
  "$PAYLOAD_ROOT/updater/updater_config.example.json"

if [ -f "$PROJECT_ROOT/updater/updater_config.json" ]; then
  write_installed_updater_config \
    "$PROJECT_ROOT/updater/updater_config.json" \
    "$PAYLOAD_ROOT/updater/updater_config.json"
fi

write_postinstall_script "$PKG_SCRIPTS/postinstall"

if [ "${SKIP_CODESIGN:-0}" != "1" ] && command -v codesign >/dev/null 2>&1; then
  run_step "Firmando localmente con ad-hoc codesign" codesign --force --deep --sign - "$PKG_ROOT/Applications/AutoHeLlegado.app"
fi

run_step "Validando payload" test -d "$PKG_ROOT/Applications/AutoHeLlegado.app"
assert_path_exists "$PAYLOAD_ROOT/AutoHeLlegado.app" "Falta AutoHeLlegado.app en payload temporal."
assert_path_exists "$PAYLOAD_ROOT/browser_extension/manifest.json" "Falta browser_extension/manifest.json."
assert_path_exists "$PAYLOAD_ROOT/updater/github_sync_updater.py" "Falta updater/github_sync_updater.py."
assert_path_exists "$PAYLOAD_ROOT/updater/apply_update_helper.py" "Falta updater/apply_update_helper.py."
assert_path_exists "$PAYLOAD_ROOT/updater/release_update_client.py" "Falta updater/release_update_client.py."
assert_path_exists "$PAYLOAD_ROOT/ms-playwright" "Falta ms-playwright."

run_step "Generando update zip para GitHub" bash -c '
  set -euo pipefail
  update_stage_root="$1"
  payload_root="$2"
  update_zip_path="$3"
  rm -rf "$update_stage_root"
  mkdir -p "$update_stage_root"
  rsync -a "$payload_root/" "$update_stage_root/"
  rm -f "$update_stage_root/.env" "$update_stage_root/updater/updater_config.json"
  rm -f "$update_zip_path"
  (cd "$update_stage_root" && /usr/bin/ditto -c -k --sequesterRsrc --rsrc . "$update_zip_path")
' _ "$BUILD_ROOT/update_payload" "$PAYLOAD_ROOT" "$UPDATE_ZIP_PATH"

run_step "Generando instalador pkg" pkgbuild \
  --root "$PKG_ROOT" \
  --scripts "$PKG_SCRIPTS" \
  --identifier "com.autohellegado.app" \
  --version "$VERSION" \
  --install-location "/" \
  "$PKG_PATH"

assert_path_exists "$PKG_PATH" "No se genero el instalador pkg."
assert_path_exists "$UPDATE_ZIP_PATH" "No se genero el update zip."

echo
echo "Instalador Mac generado:"
echo "  $PKG_PATH"
echo "Update zip Mac generado:"
echo "  $UPDATE_ZIP_PATH"
