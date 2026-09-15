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
PAYLOAD_ROOT="$PKG_SCRIPTS/payload"
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

assert_internal_env_usable() {
  local env_path="$PROJECT_ROOT/.env"
  if [ ! -f "$env_path" ]; then
    echo "No se encontro .env en la raiz del proyecto. El instalador interno requiere .env real para Supabase." >&2
    exit 1
  fi
  "$PYTHON" - "$env_path" <<'PY'
from __future__ import annotations

import sys
from pathlib import Path

env_path = Path(sys.argv[1])
values: dict[str, str] = {}
for raw_line in env_path.read_text(encoding="utf-8-sig").splitlines():
    line = raw_line.strip()
    if not line or line.startswith("#") or "=" not in line:
        continue
    key, value = line.split("=", 1)
    values[key.strip()] = value.strip().strip('"').strip("'")

url = values.get("SUPABASE_URL", "")
key = values.get("SUPABASE_KEY", "")
bad_markers = ("tu-proyecto", "tu-anon", "example.supabase.co", "xxxxx", "xxxx")
if not url.startswith("https://") or ".supabase.co" not in url or any(marker in url.lower() for marker in bad_markers):
    raise SystemExit("SUPABASE_URL en .env no parece real. Corrige .env antes de construir el instalador.")
if not key or any(marker in key.lower() for marker in bad_markers):
    raise SystemExit("SUPABASE_KEY en .env no parece real. Corrige .env antes de construir el instalador.")

auth_mode = values.get("GOOGLE_DRIVE_AUTH_MODE", "oauth").strip().lower()
if auth_mode not in {"oauth", "service_account"}:
    raise SystemExit("GOOGLE_DRIVE_AUTH_MODE debe ser 'oauth' o 'service_account'.")
if not values.get("GOOGLE_DRIVE_FOLDER_ID", "").strip():
    raise SystemExit("Falta configurar GOOGLE_DRIVE_FOLDER_ID en .env.")

credentials_key = (
    "GOOGLE_DRIVE_OAUTH_CLIENT_FILE"
    if auth_mode == "oauth"
    else "GOOGLE_DRIVE_SERVICE_ACCOUNT_FILE"
)
configured_file = values.get(credentials_key, "").strip()
if not configured_file:
    raise SystemExit(f"Falta configurar {credentials_key} en .env.")
credentials_path = Path(configured_file).expanduser()
if not credentials_path.is_absolute():
    credentials_path = (env_path.parent / credentials_path).resolve()
if not credentials_path.is_file():
    raise SystemExit(f"No existe el archivo configurado en {credentials_key}: {credentials_path}")
PY
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

copy_private_drive_config() {
  local env_path="$1"
  local target_dir="$2"
  "$PYTHON" - "$env_path" "$PROJECT_ROOT" "$target_dir" <<'PY'
from __future__ import annotations

import shutil
import sys
from pathlib import Path

env_path = Path(sys.argv[1])
project_root = Path(sys.argv[2]).resolve()
target_dir = Path(sys.argv[3])
values: dict[str, str] = {}
for raw_line in env_path.read_text(encoding="utf-8-sig").splitlines():
    line = raw_line.strip()
    if not line or line.startswith("#") or "=" not in line:
        continue
    key, value = line.split("=", 1)
    values[key.strip()] = value.strip().strip('"').strip("'")

auth_mode = values.get("GOOGLE_DRIVE_AUTH_MODE", "oauth").strip().lower()
keys = (
    ("GOOGLE_DRIVE_SERVICE_ACCOUNT_FILE",)
    if auth_mode == "service_account"
    else ("GOOGLE_DRIVE_OAUTH_CLIENT_FILE",)
)
rewrites: dict[str, str] = {}

for key in keys:
    configured = values.get(key, "").strip()
    if not configured:
        raise SystemExit(f"Falta configurar {key} en .env.")
    source = Path(configured).expanduser()
    if not source.is_absolute():
        source = (project_root / source).resolve()
    if not source.is_file():
        raise SystemExit(f"No existe el archivo configurado en {key}: {source}")

    relative = Path("config") / source.name
    if configured != relative.as_posix():
        rewrites[key] = relative.as_posix()
    destination = target_dir / relative
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)

if rewrites:
    rendered = []
    handled: set[str] = set()
    for raw_line in env_path.read_text(encoding="utf-8-sig").splitlines():
        if "=" not in raw_line or raw_line.lstrip().startswith("#"):
            rendered.append(raw_line)
            continue
        key = raw_line.split("=", 1)[0].strip()
        if key in rewrites:
            rendered.append(f"{key}={rewrites[key]}")
            handled.add(key)
        else:
            rendered.append(raw_line)
    for key in keys:
        if key in rewrites and key not in handled:
            rendered.append(f"{key}={rewrites[key]}")
    env_path.write_text("\n".join(rendered) + "\n", encoding="utf-8")
PY
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
PAYLOAD_ROOT="$(cd "$(dirname "$0")" && pwd)/payload"
trap 'echo "AutoHeLlegado: fallo postinstall en linea $LINENO (codigo $?)" >&2' ERR
CONSOLE_USER="$(/usr/bin/stat -f %Su /dev/console)"

if [ -z "$CONSOLE_USER" ] || [ "$CONSOLE_USER" = "root" ]; then
  echo "No se pudo detectar el usuario de consola." >&2
  exit 1
fi

USER_HOME="$(/usr/bin/dscl . -read "/Users/$CONSOLE_USER" NFSHomeDirectory | /usr/bin/sed 's/^NFSHomeDirectory: //')"
if [ ! -d "$USER_HOME" ] || [ "$USER_HOME" = "/" ]; then
  echo "No se pudo resolver la carpeta del usuario de consola." >&2
  exit 1
fi
SUPPORT_DIR="$USER_HOME/Library/Application Support/$APP_NAME"
APP_TARGET="/Applications/AutoHeLlegado.app"

/bin/mkdir -p "$SUPPORT_DIR"

test -x "$APP_TARGET/Contents/MacOS/AutoHeLlegado"

copy_dir() {
  local name="$1"
  if [ -d "$PAYLOAD_ROOT/$name" ]; then
    /bin/mkdir -p "$SUPPORT_DIR/$name"
    /usr/bin/ditto "$PAYLOAD_ROOT/$name" "$SUPPORT_DIR/$name"
  fi
}

copy_dir "browser_extension"
copy_dir "config"
copy_dir "sql"
copy_dir "updater"

if [ -f "$PAYLOAD_ROOT/.env.example" ]; then
  /bin/cp "$PAYLOAD_ROOT/.env.example" "$SUPPORT_DIR/.env.example"
fi

if [ -f "$PAYLOAD_ROOT/.env" ]; then
  if [ -f "$SUPPORT_DIR/.env" ]; then
    /bin/cp -p "$SUPPORT_DIR/.env" "$SUPPORT_DIR/.env.backup"
  fi
  /bin/cp "$PAYLOAD_ROOT/.env" "$SUPPORT_DIR/.env"
elif [ ! -f "$SUPPORT_DIR/.env" ]; then
  echo "El instalador no contiene .env y tampoco existe una configuracion instalada." >&2
  exit 1
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
/bin/chmod -R u+rwX "$SUPPORT_DIR"
if [ -f "$SUPPORT_DIR/.env" ]; then
  /bin/chmod 600 "$SUPPORT_DIR/.env"
fi
if [ -f "$SUPPORT_DIR/.env.backup" ]; then
  /bin/chmod 600 "$SUPPORT_DIR/.env.backup"
fi
/bin/chmod +x "$SUPPORT_DIR/updater/launchers/ActualizarApp.command" 2>/dev/null || true
/bin/rm -rf "$SUPPORT_DIR/ms-playwright"
/usr/bin/xattr -dr com.apple.quarantine "/Applications/AutoHeLlegado.app" 2>/dev/null || true

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
run_step "Validando .env interno" assert_internal_env_usable

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

mkdir -p "$BUILD_ROOT/pycache"
run_step "Compilando archivos Python clave" env \
  PYTHONPYCACHEPREFIX="$BUILD_ROOT/pycache" \
  "$PYTHON" -m py_compile \
  app_main.py \
  config/paths.py \
  updater/github_sync_updater.py \
  updater/apply_update_helper.py \
  updater/release_update_client.py \
  ui/main_app/window.py \
  automation/browser_manager.py

run_step "Verificando PyInstaller" "$PYTHON" -m PyInstaller --version

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

copy_tree "$PROJECT_ROOT/browser_extension" "$PAYLOAD_ROOT/browser_extension"
copy_tree "$PROJECT_ROOT/sql" "$PAYLOAD_ROOT/sql"
copy_tree "$PROJECT_ROOT/updater" "$PAYLOAD_ROOT/updater"

if [ -f "$PROJECT_ROOT/.env.example" ]; then
  cp "$PROJECT_ROOT/.env.example" "$PAYLOAD_ROOT/.env.example"
fi

cp "$PROJECT_ROOT/.env" "$PAYLOAD_ROOT/.env"
copy_private_drive_config "$PAYLOAD_ROOT/.env" "$PAYLOAD_ROOT"

write_installed_updater_config \
  "$PROJECT_ROOT/updater/updater_config.example.json" \
  "$PAYLOAD_ROOT/updater/updater_config.example.json"

if [ -f "$PROJECT_ROOT/updater/updater_config.json" ]; then
  write_installed_updater_config \
    "$PROJECT_ROOT/updater/updater_config.json" \
    "$PAYLOAD_ROOT/updater/updater_config.json"
fi

write_postinstall_script "$PKG_SCRIPTS/postinstall"
run_step "Validando script de instalacion" /bin/bash -n "$PKG_SCRIPTS/postinstall"

if [ "${SKIP_CODESIGN:-0}" != "1" ] && command -v codesign >/dev/null 2>&1; then
  run_step "Firmando localmente con ad-hoc codesign" codesign --force --deep --sign - "$PKG_ROOT/Applications/AutoHeLlegado.app"
fi
run_step "Verificando firma de la app" codesign --verify --deep --strict "$PKG_ROOT/Applications/AutoHeLlegado.app"

run_step "Validando payload" test -d "$PKG_ROOT/Applications/AutoHeLlegado.app"
assert_path_exists "$PAYLOAD_ROOT/browser_extension/manifest.json" "Falta browser_extension/manifest.json."
assert_path_exists "$PAYLOAD_ROOT/updater/github_sync_updater.py" "Falta updater/github_sync_updater.py."
assert_path_exists "$PAYLOAD_ROOT/updater/apply_update_helper.py" "Falta updater/apply_update_helper.py."
assert_path_exists "$PAYLOAD_ROOT/updater/release_update_client.py" "Falta updater/release_update_client.py."

run_step "Generando update zip para GitHub" bash -c '
  set -euo pipefail
  update_stage_root="$1"
  payload_root="$2"
  update_zip_path="$3"
  rm -rf "$update_stage_root"
  mkdir -p "$update_stage_root"
  rsync -a "$payload_root/" "$update_stage_root/"
  /usr/bin/ditto "$4" "$update_stage_root/AutoHeLlegado.app"
  rm -f "$update_stage_root/.env" "$update_stage_root/updater/updater_config.json"
  rm -rf "$update_stage_root/config"
  rm -f "$update_zip_path"
  (cd "$update_stage_root" && /usr/bin/ditto -c -k --sequesterRsrc --rsrc . "$update_zip_path")
' _ "$BUILD_ROOT/update_payload" "$PAYLOAD_ROOT" "$UPDATE_ZIP_PATH" "$PKG_ROOT/Applications/AutoHeLlegado.app"

run_step "Analizando componentes" pkgbuild --analyze --root "$PKG_ROOT" "$BUILD_ROOT/components.plist"
"$PYTHON" - "$BUILD_ROOT/components.plist" <<'PY'
import plistlib
import sys
from pathlib import Path

path = Path(sys.argv[1])
components = plistlib.loads(path.read_bytes())
for component in components:
    component["BundleIsRelocatable"] = False
path.write_bytes(plistlib.dumps(components))
PY

run_step "Generando instalador pkg" pkgbuild \
  --root "$PKG_ROOT" \
  --scripts "$PKG_SCRIPTS" \
  --component-plist "$BUILD_ROOT/components.plist" \
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
