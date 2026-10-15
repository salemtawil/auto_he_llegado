# Project Agent Instructions

## Project context

This is the `auto_he_llegado` desktop automation app.

The project includes:
- automation flows for Paripe, Compinche, and Ready4Drive
- Playwright browser automation
- photo pool/uploader logic
- Supabase storage/database integration
- admin/debug/export tools
- UI panels for process status, uploader, cleanup, and diagnostics

## Installed agent capabilities

Codex:
- plugin: `superpowers`

Claude:
- skill: `code-reviewer-senior`
- skill: `vibesec`
- skill: `ui-ux-pro-max`
- skill: `task-observer`
- skill: `project-memory`
- skill: `token-saver` (always on — see below)

`ui-ux-pro-max` is available to both. Use these when relevant; do not
invoke them as a reason to broaden scope.

## Always on: token-saver

`token-saver` is not optional in this repo and does not wait to be
invoked. Load it at the start of every session and apply it to every
task, alongside whatever other skill the work calls for.

This is the default working mode here:

- search before reading — `grep -n` with the exact symbol, never a full
  file to locate something
- read line ranges (`sed -n '120,180p'`), not whole modules; full files
  only when rewriting them
- never re-read a file to confirm an edit that did not fail
- trim every command's output: `| head -50`, `-q`, `--oneline`, `| tail -20`
- never dump a data file — script the calculation and print the result
- delegate wide searches ("where is this used?", "how is this module
  organized?") to a subagent so the files stay out of the main context
- edit the fragment that changes, not the whole file
- answer without preamble, without repeating code just written, without
  re-narrating steps already seen

Hard limit: this optimizes the path, never the result. If saving context
would mean guessing instead of checking, skipping a test run, or
delivering something half-verified, read whatever is needed. A cheap
wrong answer costs more than an expensive correct one.

## When to use each

| Situation | Use |
|---|---|
| Reviewing a diff, PR, or file before merging | `code-reviewer-senior` |
| Before a release, or on code written fast / by an agent | `vibesec` |
| Creating or changing anything under `ui/` | `ui-ux-pro-max` |
| Multi-step work: refactors, new flows, migrations | `task-observer` (Claude), `superpowers` (Codex) |
| Starting a session, or closing one with something worth keeping | `project-memory` |
| Every task, always | `token-saver` |

## superpowers usage (Codex)

Use `superpowers` for:
- systematic debugging
- writing implementation plans
- verification before completion
- test-driven changes
- code review style reasoning
- finishing development branches
- breaking complex changes into safe steps

Before making risky changes, prefer a short plan:
1. identify current behavior
2. identify desired behavior
3. isolate the smallest safe change
4. add or update tests
5. run validation

Do not use superpowers as an excuse to broaden scope.

## task-observer usage

Use `task-observer` for any change spanning more than one file or one
step. It plays the same role for Claude that `superpowers` plays for
Codex: explicit plan, recorded decisions, and a verification step that
must run before anything is called done.

Mandatory stop-and-ask in this repo before:
- touching any item under "Critical automation rules" below
- changing the Supabase schema or storage policies
- deleting or overwriting files in `local_data/`, `storage/`, or `releases/`
- pushing to a shared branch

## code-reviewer-senior usage

Run it on the diff before merging anything into a release branch.

Priorities specific to this project:
- Playwright: awaits, timeouts, selectors that depend on volatile DOM
- threading: background work touching customtkinter widgets from a
  non-UI thread
- multiprocessing isolation: shared state crossing process boundaries
- Supabase: error paths that swallow failures and report success
- fallbacks: a "fast path" added without keeping the traditional route

## vibesec usage

Run before a release, and after any change that touches credentials,
uploads, or the browser extension.

Checks that matter most here:
- no secrets in code, logs, `.env.example`, or packaged builds
  (`build/`, `dist/`, `releases/`, `browser_extension.crx`)
- the Supabase `service_role` key never reaches client-side code
- Row Level Security enabled, with policies that are not `true`
- storage buckets private unless they must be public
- browser extension manifest permissions scoped to the needed domains,
  not `<all_urls>`
- no unvalidated input reaching SQL, `subprocess(shell=True)`, file
  paths, or `page.evaluate`
- debug/inspector entry points (`app_debug_inspector.py`, `debug_tools/`)
  not reachable in a production build

## ui-ux-pro-max usage

Use `ui-ux-pro-max` when modifying or reviewing UI/UX, especially:
- `ui/`
- admin panel
- uploader panel
- cleanup photos panel
- diagnostics/export screens
- process status cards
- error/status messages
- progress bars
- layout, spacing, readability, color, and interaction states

When working on UI:
- preserve the current dark visual style unless explicitly asked otherwise
- keep the app practical and compact
- avoid unnecessary animations
- prioritize clarity, readable status, and visible progress
- make errors actionable
- do not mix UI refactors with automation-flow logic changes unless requested

## project-memory usage

At the start of a session: read this file, `README.md`, and
`git log --oneline -15` before acting.

At the end: record only what saves someone time tomorrow — a decision
and its discarded alternatives, a non-obvious convention, a trap that
cost time, the exact command for something, or the real state of
unfinished work. Durable project knowledge belongs in this file;
architectural decisions in `docs/`. Never record credentials, branch
names, PR numbers, or session narration.

## Critical automation rules

Do not casually change:
- login behavior
- selfie/photo upload flow
- final click logic
- Flow State Detector rules
- BrowserManager behavior
- Supabase schema
- uploader bulk logic
- photo cleanup logic
- multiprocessing isolation

For automation changes:
- keep changes site-scoped when requested
- preserve fallbacks
- add tests for regressions
- run targeted tests and full tests when possible

## Paripe current optimization rules

Paripe has a fast final-click path using Flow State Detector.

Expected behavior:
- after `final_click_done`, do not run old block-reading routes
- no `block_read_ready` after final click
- no `block_details_read` after final click
- no double final click
- `final_result_started` should happen immediately after `final_click_done`
- `final_result_done` and `process_finished` should be close together
- fallback traditional route must remain available before final click

## Validation

For automation changes, run relevant checks such as:

```powershell
python -m py_compile automation\paripe_site.py
python -m py_compile automation\compinche_site.py
python -m py_compile automation\ready4drive_site.py
python -m py_compile services\process_service.py
python -m pytest tests\test_paripe_site.py
python -m pytest tests\test_process_service.py
python -m pytest tests -q
```

## Trampas conocidas (auditoría 2026-09-22 — ver `docs/auditoria-2026-09-22.md`)

- La suite se ejecuta con el entorno del repositorio: `.venv\Scripts\python.exe -m pytest tests -q`.
  Fuera de Windows hace falta un Python **con tkinter**: `customtkinter` se importa en
  tiempo de import y sin `tkinter` la recolección de tests falla entera.
- `cancel_event` (`services/process_run_context.py:148`) se consulta en ~18 puntos de
  `automation/` pero **nadie lo activa nunca**, y no hay botón de cancelar en la UI. Una
  corrida solo termina completándose o lanzando.
- `normalize_relpath` existe dos veces, con semánticas distintas:
  `updater/apply_update_helper.py` (endurecido: rechaza `..`, unidades, UNC y rutas
  absolutas, y conserva la barra final que necesitan los patrones tipo `config/`) y
  `updater/github_sync_updater.py` (solo `lstrip("./")`, que además se come el punto
  inicial de los dotfiles — por eso `resolve_inside` **no** pasa por él). La comparación
  contra rutas protegidas es *case-insensitive* en ambos: Windows y macOS tratan `.ENV`
  y `.env` como el mismo archivo.
- `_is_storage_missing_error` (`services/process_photo_service.py`, `photo_cleanup_service.py`)
  casa con los tokens sueltos `"not found"` / `"does not exist"`. Supabase Storage devuelve
  esos mismos textos para *Bucket not found* y para denegaciones de RLS: un bucket mal
  configurado se interpreta como "la foto ya no existe".
- `ADMIN_ACCESS_PASSWORD` ya no tiene valor por defecto. Sin esa variable en `.env`, el
  panel Admin queda bloqueado a propósito (fail-closed).
- Empaquetado y `.env`: `scripts/build_release.py` produce un paquete **sin credenciales
  reales** (copia solo `.env.example`). Los empaquetadores internos —
  `packaging/windows/build_portable_windows.ps1`,
  `packaging/windows/build_installer_windows.ps1`,
  `packaging/macos/build_portable_macos.sh`,
  `packaging/macos/build_installer_macos.sh` y el workflow de macOS — **sí incluyen el
  `.env` operativo a propósito**, y validan que exista antes de construir: la app es de
  distribución interna y debe funcionar inmediatamente tras instalarse. No eliminar,
  vaciar, renombrar ni sustituir ese `.env` por `.env.example`. Los artefactos que salen
  de esos empaquetadores son **confidenciales** y solo se distribuyen por canales privados.

## Ciclo de vida del navegador (corrección 2026-10-13)

La API **sync** de Playwright está atada al hilo que arrancó el driver. Cuando el
hilo de una corrida termina, `page`, `context`, `browser` y `playwright` quedan
inservibles: cualquier llamada lanza
`cannot switch to a different thread (which happens to have exited)`.
Comprobado con Chromium real en Playwright 1.63.

Consecuencias para quien toque `automation/browser_manager.py`:

- **Nunca** asumas que `session.close()` puede cerrar algo desde otro hilo.
  Comprueba `is_owned_by_current_thread()`; si es falso, la única vía es
  `kill_driver()` (mata el driver por PID, y con él el navegador).
- `_close_internal` solo marca `_closed = True` cuando cierra de verdad. Marcarlo
  antes de comprobar `keep_open` deja la sesión inalcanzable para siempre: fue la
  causa de que cada corrida abandonara un Chrome y un driver vivos.
- `_register_session` desregistra **solo** si la sesión se cerró. Desregistrar en
  un `finally` incondicional deja a `shutdown_all()` sin nada que cerrar.
- El vigilante (`reap_orphan_sessions`, hilo `browser-session-reaper`) mata los
  drivers cuyo navegador ya cerró el operador. Si no puede determinar el estado
  (`browser_still_open()` devuelve `None`, p. ej. sin `psutil`) **no mata nada**,
  para no cerrarle el navegador al operador por error.

### API privada de Playwright

`capture_driver_pid()` lee `playwright._impl_obj._connection._transport._proc.pid`.
Es **API privada**. El proyecto fija `playwright>=1.52,<2.0`; si una versión mueve
esa ruta, la función devuelve `None`, la app sigue funcionando y solo se pierde la
capacidad de matar drivers huérfanos. Al subir de versión de Playwright, ejecuta:

```
AHL_BROWSER_E2E=1 python -m pytest tests/test_browser_session_leak_real.py -v
```

Esa prueba lanza navegadores reales y está desactivada por defecto.

### psutil

`psutil` solo se usa para **saber** si a un driver todavía le cuelga un navegador.
Matar no lo necesita (`taskkill /F /T` en Windows, `os.kill` en POSIX). Si falta,
la limpieza al cerrar la app sigue completa y solo se pierde detectar que el
operador cerró la ventana a mitad de sesión. Está en `requirements.txt` y en
`packages_to_collect` de ambos `.spec`.

### Dos procesos simultáneos

La app puede tener **dos corridas abiertas a la vez** (dos slots). Cada corrida
arranca su propio `sync_playwright().start()`, así que tiene **su propio proceso
driver y su propio árbol de procesos**; los árboles son disjuntos. Verificado con
navegadores reales en `tests/test_browser_session_leak_real.py`.

Reglas que hay que mantener al tocar el ciclo de vida:

- Toda limpieza es **por sesión**: se mata el PID de *esa* sesión, nunca "todos
  los drivers". Cerrar o limpiar el slot 1 no debe tocar el slot 2.
- `shutdown_all()` se llama **solo** al cerrar la app (`ProcessService.shutdown()`
  ← `window.py`), y después de unir los hilos de las corridas. No lo llames al
  terminar una corrida: cerraría el navegador del otro slot.
- El vigilante evalúa cada sesión por separado y salta las que no pueda
  determinar. Nunca introduzcas una limpieza "global" dentro de él.
- Estado de CLASE que sí se comparte entre slots: `get_latest_session()`,
  `get_latest_extension_debug()` y `_current_run_id`. Hoy solo alimentan paneles
  de diagnóstico de la extensión y **no cierran nada**, así que no cruzan
  lifecycle entre slots. Si alguna vez se usan para decidir un cierre, hay que
  pasarlos antes a búsqueda por `process_id`/`run_id` (ver el TODO en
  `get_latest_session`).
