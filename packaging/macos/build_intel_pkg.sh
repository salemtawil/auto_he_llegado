#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

if [ "$(uname -s)" != "Darwin" ] || [ "$(uname -m)" != "x86_64" ]; then
  echo "Este builder debe ejecutarse en una Mac Intel (x86_64)." >&2
  exit 1
fi

if [ ! -f "$PROJECT_ROOT/requirements-dev.txt" ]; then
  echo "Falta requirements-dev.txt: no se puede validar el codigo actual antes del build." >&2
  exit 1
fi

export MACOS_TARGET_ARCH=x86_64
exec bash "$SCRIPT_DIR/build_installer_macos.sh"
