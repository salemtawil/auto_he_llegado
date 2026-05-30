#!/bin/bash

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
APP_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

cd "$APP_ROOT" || {
  echo "No se pudo abrir la carpeta de la app."
  read -r -p "Presiona Enter para cerrar..."
  exit 1
}

clear
echo "========================================"
echo "  Actualizador Auto He Llegado"
echo "========================================"
echo
echo "Cierra Auto He Llegado antes de continuar."
read -r -p "Presiona Enter para iniciar la actualizacion..."

run_step() {
  local label="$1"
  shift

  echo
  echo "[$label]"
  "$@"
  local status=$?
  if [ "$status" -ne 0 ]; then
    echo
    echo "La actualizacion se detuvo durante: $label"
    echo "Si aparece CERTIFICATE_VERIFY_FAILED, ejecuta:"
    echo 'open "/Applications/Python 3.11/Install Certificates.command"'
    echo "o"
    echo 'open "/Applications/Python 3.12/Install Certificates.command"'
    read -r -p "Presiona Enter para cerrar..."
    exit "$status"
  fi
}

run_step "Verificando configuracion remota" python3 updater/github_sync_updater.py --check --config updater/updater_config.json
run_step "Simulando cambios" python3 updater/github_sync_updater.py --dry-run --config updater/updater_config.json
run_step "Aplicando actualizacion" python3 updater/github_sync_updater.py --apply --config updater/updater_config.json

echo
echo "La actualizacion termino correctamente."
echo "Si aparece CERTIFICATE_VERIFY_FAILED, ejecuta:"
echo 'open "/Applications/Python 3.11/Install Certificates.command"'
echo "o"
echo 'open "/Applications/Python 3.12/Install Certificates.command"'
read -r -p "Presiona Enter para cerrar..."
