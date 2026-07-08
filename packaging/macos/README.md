# macOS Build

## Objetivo recomendado

Generar un instalador `.pkg` para macOS:

- Instala `AutoHeLlegado.app` en `/Applications`.
- Guarda configuracion, logs, updater, extension y Playwright en `~/Library/Application Support/AutoHeLlegado`.
- Conserva `.env` existente cuando se instala una version nueva.

Comando:

```bash
chmod +x packaging/macos/build_installer_macos.sh
packaging/macos/build_installer_macos.sh
```

Por defecto genera `x86_64`, que cubre Mac Intel de forma nativa y Apple Silicon con Rosetta.

Para intentar un binario universal nativo Intel + Apple Silicon, usa:

```bash
MACOS_TARGET_ARCH=universal2 packaging/macos/build_installer_macos.sh
```

Si falla con una dependencia tipo `_cffi_backend...so is not a fat binary`, vuelve al build `x86_64`.

El resultado queda en:

- `releases/AutoHeLlegado_Mac_<arquitectura>_Installer_<version>_<fecha>.pkg`

## Portable de respaldo

Tambien se puede generar un paquete portable con esta estructura:

- `dist/AutoHeLlegadoMac/`
- `dist/AutoHeLlegadoMac/AutoHeLlegado.app`
- `releases/AutoHeLlegado_Mac_Portable_<fecha>.zip`

La carpeta completa es el producto final. No se debe mover solo el `.app`, porque la app espera encontrar `.env`, `local_data`, `browser_extension`, `updater` y `ms-playwright` al lado de `AutoHeLlegado.app`.

## Requisitos en la Mac que construye

- macOS.
- Python 3.11 o 3.12. No uses Python 3.13/3.14 para empaquetar, porque puede generar conflictos binarios con `cryptography`/OpenSSL.
- Para un paquete compatible con Intel y Apple Silicon en un solo zip, usa Python universal2 de python.org.
- El script crea `.venv` e instala dependencias automaticamente, salvo que uses `SKIP_DEP_INSTALL=1`.

Si usas virtualenv:

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt -c packaging/macos/constraints-macos.txt pyinstaller
python -m playwright install chromium
```

## Comando de build portable

Desde la raiz del repo:

```bash
chmod +x packaging/macos/build_portable_macos.sh
packaging/macos/build_portable_macos.sh
```

Por defecto genera arquitectura `x86_64`, pensada para Intel y Apple Silicon con Rosetta.

Si alguna dependencia binaria no permite universal2, genera un paquete Intel compatible con Intel y Apple Silicon via Rosetta:

```bash
MACOS_TARGET_ARCH=x86_64 packaging/macos/build_portable_macos.sh
```

Para Apple Silicon nativo solamente:

```bash
MACOS_TARGET_ARCH=arm64 packaging/macos/build_portable_macos.sh
```

Para saltar tests durante una prueba rapida:

```bash
SKIP_TESTS=1 packaging/macos/build_portable_macos.sh
```

## Que valida el script

- Compila archivos Python clave.
- Ejecuta `pytest` salvo que uses `SKIP_TESTS=1`.
- Verifica PyInstaller.
- Instala Chromium de Playwright si hace falta.
- Copia `ms-playwright` desde `~/Library/Caches/ms-playwright`.
- Genera `AutoHeLlegado.app`.
- Copia recursos externos al lado del `.app`.
- Firma localmente el `.app` con ad-hoc `codesign`.
- Genera el zip final usando `ditto`.

## Que incluye el paquete

- `AutoHeLlegado.app`
- `.env.example`
- `.env` si existe en la raiz del proyecto; si no existe, se crea desde `.env.example`
- `browser_extension/`
- `sql/`
- `updater/`
- `ms-playwright/`
- `logs/`
- `exports/`
- `updates/`
- `local_data/`

## Que no incluye

- `.venv/`.
- `tests/`.
- `chrome_profiles/`.
- datos reales de `local_data/`, `logs/`, `exports/` o `updates/`.

## Entrega

Entrega el archivo generado en `releases/AutoHeLlegado_Mac_Portable_<fecha>.zip`.

La guia para el usuario final esta en:

- `packaging/macos/INSTALL.md`
