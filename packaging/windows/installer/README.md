# Instalador Windows Interno

## Objetivo

Generar un instalador `per-user` para Windows con Inno Setup y un `update zip` compatible con el updater integrado de la app.

Salida esperada:

- `releases/AutoHeLlegado_Setup_<fecha>.exe`
- `releases/AutoHeLlegado_Update_<fecha>.zip`

## Requisitos

- Windows
- Python disponible o `.venv\Scripts\python.exe`
- Dependencias del proyecto instaladas
- PyInstaller instalado en el entorno activo
- Inno Setup 6 instalado con `iscc.exe` en `PATH` o en su ruta por defecto
- Cache local de Playwright en:
  - `%USERPROFILE%\AppData\Local\ms-playwright`
- `.env` real en la raíz del proyecto

Si falta `.env`, el build falla con este mensaje:

`No se encontró .env en la raíz del proyecto. Este instalador interno requiere .env para Supabase. Crea .env antes de construir. No se imprimen secretos.`

El script no imprime el contenido de `.env`.

## Comando de build

```powershell
powershell -ExecutionPolicy Bypass -File packaging\windows\build_installer_windows.ps1
```

## Qué genera

La app se instala en:

`%LOCALAPPDATA%\Programs\AutoHeLlegado`

Incluye:

- `AutoHeLlegado.exe`
- `AutoHeLlegadoUploader.exe`
- `AutoHeLlegadoDebugInspector.exe`
- `AutoHeLlegadoUpdateHelper.exe`
- `_internal/`
- `updater/`
- `browser_extension/`
- `ms-playwright/`
- `.env`
- `.env.example`

## Visibilidad para agentes

- El unico acceso directo visible para el usuario final es `Auto He Llegado`.
- `AutoHeLlegadoUploader.exe`, `AutoHeLlegadoDebugInspector.exe` y `AutoHeLlegadoUpdateHelper.exe` quedan incluidos dentro de la carpeta instalada.
- Los ejecutables auxiliares no crean accesos directos en escritorio ni en menu inicio.
- Los ejecutables auxiliares no se abren automaticamente.
- Para el usuario final, la app que debe abrirse es solo `AutoHeLlegado.exe`.
- Los auxiliares se consideran herramientas internas o de soporte/admin.

## Regla de `.env`

- El instalador inicial incluye `.env` real desde la máquina de build.
- En primera instalación, copia `.env` a la carpeta instalada.
- En reinstalación o actualización por instalador, no sobrescribe un `.env` existente.
- El `update zip` no incluye `.env` real.

## Carpetas persistentes

El instalador crea y preserva:

- `logs/`
- `exports/`
- `updates/`
- `updates/backups/`
- `updates/update_logs/`
- `updates/staging/`
- `local_data/`
- `local_data/config/`
- `local_data/logs/`
- `local_data/debug/`
- `local_data/results/`
- `local_data/results/screenshots/`
- `local_data/failed_uploads/`
- `local_data/temp_photos/`
- `chrome_profiles/`

## Update zip

El `update zip` contiene el build reemplazable:

- `AutoHeLlegado.exe`
- `AutoHeLlegadoUploader.exe`
- `AutoHeLlegadoDebugInspector.exe`
- `AutoHeLlegadoUpdateHelper.exe`
- `_internal/`
- `updater/`
- `browser_extension/`
- `.env.example`

No incluye:

- `.env` real
- `logs/`
- `exports/`
- `local_data/`
- `chrome_profiles/`
- `updates/backups/`
- `updates/update_logs/`

## Actualización integrada

Desde `Configuración > Actualizar app`:

1. La app valida que no existan procesos activos.
2. Lanza `AutoHeLlegadoUpdateHelper.exe`.
3. Muestra `Actualizando, la app se reiniciará.`
4. Cierra la app principal.
5. El helper espera el cierre, aplica el paquete staged y reabre `AutoHeLlegado.exe`.

## Descarga remota

En esta fase el helper está listo para aplicar paquete local o `zip` staged.

Pendiente para una fase posterior:

- descargar `AutoHeLlegado_Update_<fecha>.zip` desde GitHub Releases o desde una URL configurada
- verificar `sha256`
- poblar `updates/staging/latest_build` o un `package_zip` descargado automáticamente
