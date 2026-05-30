# Portable Windows Build

## Objetivo

Generar un kit portable `onedir` para Windows sin instalador.

Salida esperada:

- `dist/AutoHeLlegado/`
- `releases/AutoHeLlegado_Windows_Portable_<fecha>.zip`

## Ejecutables incluidos

- `AutoHeLlegado.exe`
- `AutoHeLlegadoUploader.exe`
- `AutoHeLlegadoDebugInspector.exe`

`AutoHeLlegado.exe` es el ejecutable principal. Los auxiliares quedan incluidos, pero no se abren automaticamente.

## Prerequisitos para construir

- Windows
- Python disponible o `.venv\Scripts\python.exe`
- Dependencias del proyecto instaladas
- PyInstaller instalado en el entorno activo
- Cache local de Playwright en:
  - `%USERPROFILE%\AppData\Local\ms-playwright`

Si falta la cache de Playwright, instala al menos Chromium antes del build:

```powershell
.\.venv\Scripts\python.exe -m playwright install chromium
```

## Comando de build

```powershell
powershell -ExecutionPolicy Bypass -File packaging\windows\build_portable_windows.ps1
```

## Validaciones que ejecuta el script

Antes del build:

- `python -m pytest tests -q`
- `python -m py_compile app_main.py`
- `python -m py_compile app_uploader.py`
- `python -m py_compile app_debug_inspector.py`
- `python -m py_compile updater\github_sync_updater.py`
- `python -m py_compile ui\main_app\window.py`

Despues del build valida:

- `dist/AutoHeLlegado/AutoHeLlegado.exe`
- `dist/AutoHeLlegado/AutoHeLlegadoUploader.exe`
- `dist/AutoHeLlegado/AutoHeLlegadoDebugInspector.exe`
- `dist/AutoHeLlegado/updater/github_sync_updater.py`
- `dist/AutoHeLlegado/updater/launchers/ActualizarApp.bat`
- `dist/AutoHeLlegado/browser_extension/`
- `dist/AutoHeLlegado/logs/`
- `dist/AutoHeLlegado/updates/`
- zip final en `releases/`

## Que incluye el portable

- ejecutables PyInstaller `onedir`
- `browser_extension/`
- `updater/`
- `updater/launchers/`
- `updater/github_sync_updater.py`
- `updater/updater_config.example.json`
- `updater/updater_config.json` solo si el config fuente es publico y no usa placeholders
- `updater/README.md`
- `sql/`
- `.env.example`
- `ms-playwright/`
- carpetas vacias:
  - `logs/`
  - `exports/`
  - `updates/`
  - `local_data/`
  - `local_data/config/`
  - `local_data/logs/`
  - `local_data/debug/`
  - `local_data/results/`
  - `local_data/results/screenshots/`
  - `local_data/failed_uploads/`
  - `local_data/temp_photos/`

## Que NO incluye

- `.env` real
- `.venv/`
- `tests/`
- `__pycache__/`
- `.pytest_cache/`
- `chrome_profiles/`
- `local_data/` real
- `logs/` reales
- `exports/` reales
- `updates/` reales
- `backups/` reales
- `.git/`

## Entrega al usuario final

1. Entregar el `.zip` generado en `releases/`.
2. El usuario descomprime la carpeta completa.
3. El usuario ejecuta `AutoHeLlegado.exe`.
4. Si necesita credenciales, debe crear `.env` a partir de `.env.example`.

## Smoke test manual recomendado

1. Descomprimir el `.zip` en una carpeta temporal.
2. Ejecutar `AutoHeLlegado.exe`.
3. Abrir Configuracion.
4. Verificar que existe el boton `Actualizar app`.
5. Verificar que la app crea `logs/`, `updates/` y `local_data/` dentro de la carpeta portable.
6. Verificar que no aparezcan rutas hardcodeadas `D:\Tawil\...`.
7. Cerrar la app normalmente.
8. Probar manualmente:

```powershell
cd updater
python github_sync_updater.py --check --config updater_config.json
```

## Nota sobre el updater

El updater queda incluido y listo para lanzarse desde la app o manualmente.

Limitacion importante:
- el updater actual sincroniza archivos del repo fuente de GitHub
- el portable principal corre como ejecutable PyInstaller
- por eso, el updater puede servir para recursos incluidos en carpeta, pero no garantiza actualizar la logica ya congelada dentro de `AutoHeLlegado.exe`

La forma segura de actualizar el portable completo sigue siendo distribuir un nuevo `.zip`.
