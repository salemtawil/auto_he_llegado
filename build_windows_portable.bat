@echo off
setlocal
cd /d "%~dp0"

if exist ".\.venv\Scripts\python.exe" (
    set "PYTHON_EXE=.\.venv\Scripts\python.exe"
) else (
    set "PYTHON_EXE=python"
)

"%PYTHON_EXE%" scripts\build_release.py
exit /b %errorlevel%
