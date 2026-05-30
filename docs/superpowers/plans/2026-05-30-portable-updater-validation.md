# Portable Updater Validation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Aceptar instalaciones source/dev y portable PyInstaller onedir en el updater, y resolver `updater/` en raíz con fallback a `_internal/updater/`.

**Architecture:** La validación del updater distinguirá layouts explícitos con diagnóstico legible. La UI solo resolverá rutas del updater/config y mantendrá prioridad por la raíz del portable. El build seguirá reflejando `updater/` y `.env.example` en la raíz final.

**Tech Stack:** Python, pytest, PowerShell, PyInstaller onedir.

---

### Task 1: Tests rojos del updater

**Files:**
- Modify: `tests/test_github_sync_updater.py`

- [ ] Escribir tests para source/dev, portable, BOM y mensajes.
- [ ] Ejecutar `python -m pytest tests\test_github_sync_updater.py -q` y confirmar fallo correcto.
- [ ] Implementar lo mínimo en updater.
- [ ] Reejecutar el test y confirmar PASS.

### Task 2: Tests rojos de resolución en window

**Files:**
- Modify: `tests/test_window_updater.py`
- Modify: `ui/main_app/window.py`

- [ ] Escribir tests para prioridad `PROJECT_ROOT/updater` y fallback `_internal/updater`.
- [ ] Ejecutar `python -m pytest tests\test_window_updater.py -q` y confirmar fallo correcto.
- [ ] Implementar resolución mínima en `window.py`.
- [ ] Reejecutar el test y confirmar PASS.

### Task 3: Verificación de build portable

**Files:**
- Review/Modify if needed: `packaging/windows/build_portable_windows.ps1`

- [ ] Confirmar que ya copia `updater/` y `.env.example` a raíz o ajustar lo mínimo.
- [ ] Ejecutar el build de validación solicitado.

### Task 4: Validación final

**Files:**
- Verify: `updater/github_sync_updater.py`
- Verify: `ui/main_app/window.py`

- [ ] Ejecutar `python -m py_compile updater\github_sync_updater.py`.
- [ ] Ejecutar `python -m py_compile ui\main_app\window.py`.
- [ ] Ejecutar `python -m pytest tests\test_github_sync_updater.py`.
- [ ] Ejecutar `python -m pytest tests\test_window_updater.py`.
- [ ] Ejecutar `python -m pytest tests -q`.
- [ ] Ejecutar `powershell -ExecutionPolicy Bypass -File packaging\windows\build_portable_windows.ps1`.
