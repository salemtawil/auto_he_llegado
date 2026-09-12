#!/bin/bash
set -euo pipefail

APP_NAME="AutoHeLlegado"
TARGET_DIR="$HOME/Library/Application Support/$APP_NAME"
TARGET_ENV="$TARGET_DIR/.env"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SOURCE_ENV="$SCRIPT_DIR/.env"

pause() {
    echo
    read -r -p "Presiona Enter para cerrar..." _
}

fail() {
    echo
    echo "ERROR: $1"
    pause
    exit 1
}

echo "Instalador de configuracion para $APP_NAME"
echo

if [[ ! -f "$SOURCE_ENV" ]]; then
    fail "No encontre el archivo .env junto a este script. Pon install_env_macos.command y .env en la misma carpeta."
fi

if ! grep -q '^SUPABASE_URL=https://.*\.supabase\.co' "$SOURCE_ENV"; then
    fail "El .env no tiene un SUPABASE_URL valido."
fi

if ! grep -q '^SUPABASE_KEY=.' "$SOURCE_ENV"; then
    fail "El .env no tiene SUPABASE_KEY."
fi

if grep -Eq 'tu-proyecto|tu-anon|example\.supabase\.co|xxxxx|xxxx' "$SOURCE_ENV"; then
    fail "El .env parece tener valores de ejemplo. Revisa las claves reales antes de instalarlo."
fi

mkdir -p "$TARGET_DIR"
cp "$SOURCE_ENV" "$TARGET_ENV"
chmod 600 "$TARGET_ENV"

echo "Listo. El .env quedo instalado en:"
echo "$TARGET_ENV"

MISPLACED_ENV="/Applications/$APP_NAME.app/Contents/.env"
if [[ -f "$MISPLACED_ENV" ]]; then
    echo
    echo "Aviso: tambien existe un .env dentro de la app:"
    echo "$MISPLACED_ENV"
    echo "Ese archivo no es necesario. Puedes borrarlo si quieres, pero la app usara el de Application Support."
fi

echo
echo "Ahora cierra y abre $APP_NAME de nuevo."
pause
