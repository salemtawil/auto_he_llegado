@echo off
setlocal

set "SCRIPT_DIR=%~dp0"
for %%I in ("%SCRIPT_DIR%..\..") do set "APP_ROOT=%%~fI"

cd /d "%APP_ROOT%" || (
    echo No se pudo abrir la carpeta de la app.
    pause
    exit /b 1
)

title Actualizador Auto He Llegado
echo ========================================
echo   Actualizador Auto He Llegado
echo ========================================
echo.
echo Cierra Auto He Llegado antes de continuar.
pause

echo.
echo [Verificando configuracion remota]
python updater\github_sync_updater.py --check --config updater\updater_config.json
if errorlevel 1 goto :error

echo.
echo [Simulando cambios]
python updater\github_sync_updater.py --dry-run --config updater\updater_config.json
if errorlevel 1 goto :error

echo.
echo [Aplicando actualizacion]
python updater\github_sync_updater.py --apply --config updater\updater_config.json
if errorlevel 1 goto :error

echo.
echo La actualizacion termino correctamente.
pause
exit /b 0

:error
echo.
echo La actualizacion se detuvo por un error.
pause
exit /b 1
