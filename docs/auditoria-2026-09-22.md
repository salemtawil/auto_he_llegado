# Auditoría integral `auto_he_llegado` — 2026-09-22

Dos fases sobre el mismo árbol de trabajo: la auditoría inicial y una revisión
posterior que encontró regresiones y afirmaciones inexactas en la primera.
Este documento refleja el estado **después** de ambas.

**Estado del árbol:** 36 archivos modificados (+1.946 / −274 líneas) y 12 archivos
nuevos. Sin commits, push, releases ni despliegues.

**Suite:** 394 tests en verde al empezar → **567 en verde** al terminar
(173 tests nuevos).

---

## 0. Empaquetado y `.env` — decisión de despliegue aceptada

Conviene dejarlo explícito porque la primera versión de este informe lo describió mal.

Hay **dos caminos de empaquetado distintos, y ambos son correctos**:

- **`scripts/build_release.py` genera un paquete sin credenciales reales.** Copia
  únicamente `.env.example`, borra cualquier `.env` que hubiera dejado un build
  anterior en el directorio de release y falla si falta la plantilla. Ese paquete
  no debe llevar secretos.
- **Los empaquetadores internos incluyen deliberadamente el `.env` operativo.**
  `packaging/windows/build_portable_windows.ps1`,
  `packaging/windows/build_installer_windows.ps1`,
  `packaging/macos/build_portable_macos.sh`,
  `packaging/macos/build_installer_macos.sh` y la configuración equivalente del
  workflow de macOS validan que exista un `.env` funcional antes de construir y lo
  copian al portable, al instalador, a la aplicación y al PKG. **Es una decisión de
  despliegue interno aceptada por el usuario:** la aplicación se distribuye dentro
  de la organización y debe funcionar inmediatamente después de instalarse; si el
  instalador no llevara la configuración, la app instalada no podría conectarse.

**Consecuencia operativa:** los artefactos producidos por los empaquetadores
internos (portable, instalador, `.app`, PKG) **contienen credenciales y deben
tratarse como confidenciales**: se distribuyen únicamente por canales privados, no
se publican en releases abiertos, repositorios públicos ni enlaces compartibles.

Ninguna ruta de empaquetado o distribución del `.env` fue modificada en este
trabajo. Ningún valor de `.env` fue leído, impreso ni alterado.

---

## 1. Resumen ejecutivo

Tres clases de problema real, todas corregidas:

1. **Robustez de la cadena de actualización.** El actualizador escribía archivos
   desde un ZIP y desde un manifiesto remoto sin validar las rutas, y comparaba las
   rutas protegidas de forma sensible a mayúsculas, de modo que `.ENV` o `CONFIG/`
   no coincidían con `.env` ni `config/` en Windows y macOS, donde son el mismo
   archivo.
2. **Hilos y cierre.** El panel del uploader tocaba Tk desde el hilo trabajador; el
   cierre de la aplicación mataba corridas a mitad de su propia limpieza y destruía
   los navegadores *antes* de esperar a los hilos que los usaban; la interfaz
   llamaba a la API síncrona de Playwright desde el hilo de Tk.
3. **Clasificación de errores de Storage.** Un bucket mal configurado, una
   denegación de RLS o un timeout se interpretaban como "la foto ya no existe" y
   descartaban filas sanas en masa.

---

## 2. Vulnerabilidades demostradas vs endurecimiento preventivo

La primera versión de este informe no distinguía ambas cosas. La distinción importa:

### Demostrado con una prueba que falla sin el arreglo

| Hallazgo | Evidencia |
|---|---|
| **Path traversal en `github_sync_updater`** | `is_path_allowed("ui/../../../evil.py", ["ui/"])` devolvía `True`, y el destino se construía como `install_dir / decision.path`. Reproducible en una línea; `tests/test_updater_path_safety.py::test_sync_path_rules_fail_closed_on_traversal` lo fija. |
| **`is_protected_path` mutilaba las rutas de traversal** | `"../../.env".lstrip("./")` daba `"env"`, que no casaba con ningún patrón protegido. Reproducible. |
| **Comparación sensible a mayúsculas de rutas protegidas** | `.ENV`, `CONFIG/settings.json`, `LOCAL_DATA/x` pasaban el filtro y eran sobrescritas por una actualización. Reproducible en Windows y macOS, donde el sistema de archivos no distingue mayúsculas. |
| **`normalize_relpath` se comía el punto de los dotfiles** | `lstrip("./")` elimina un *conjunto* de caracteres: `.env` → `env`, `.github/ci.yml` → `github/ci.yml`. Esto anulaba a la vez la lista de rutas protegidas y `BUILTIN_EXCLUDED_PREFIXES` (`.git/`, `.venv/` nunca se excluían) y reubicaba los dotfiles en disco. |
| **Carrera del drenaje de logs** | Un update bloqueado dejaba la corrida colgada indefinidamente en `queue.join()`. Reproducido: revertir el arreglo deja el test colgado 60 s y luego en rojo. |
| **Playwright desde el hilo de Tk** | El test preexistente `tests/test_window_export.py` ya simulaba el error real `"Cannot switch to a different thread"` que devolvía la llamada cruzada. |
| **Clasificador de Storage demasiado laxo** | `"Bucket not found"` contiene `"not found"`, así que casaba y disparaba `_discard_missing_storage_photo` sobre hasta 500 filas por llamada. Reproducible con el texto exacto que devuelve Supabase. |
| **`reset_photo_pool.py` ignoraba `--bucket`/`--prefix` en la fase de base de datos** | El filtro estaba fijo en `.like("file_path", "available/%")` sin filtro de bucket. `--prefix candidates` borraba sólo los objetos de candidatos pero marcaba como descartadas **todas** las filas `available/*`. |

### Endurecimiento preventivo (defensa adicional, sin explotación demostrada)

- **Validación de miembros del ZIP antes de `extractall`.** No se reprodujo un
  paquete malicioso que escribiera fuera del destino: el paquete lo produce el
  propio proyecto y se descarga por HTTPS. La validación se añade como **defensa
  adicional**, no porque exista un Zip Slip demostrado en este repositorio. Lo que
  sí es cierto y comprobable es que `zipfile.extractall()` no valida los nombres de
  los miembros, de modo que la protección dependía enteramente del origen del
  paquete.
- **`hmac.compare_digest` para la contraseña admin.** No hay un ataque de
  temporización practicable contra un diálogo local; es higiene.
- **`textContent` en lugar de `innerHTML` en el overlay de la extensión.** Los
  valores actuales vienen de un enum fijo del detector, así que hoy no es
  explotable; se cambia para que no lo sea si un detector cambia mañana.
- **`*.pem` / `*.key` en `.gitignore`.** No impide nada retroactivamente (ver §6).

---

## 3. Correcciones implementadas

### 3.1 Rutas protegidas del actualizador

`updater/apply_update_helper.py`
- `normalize_relpath` rechaza `..`, rutas absolutas, letras de unidad y UNC
  (`UnsafeUpdatePathError`), y conserva la barra final que los patrones de
  directorio (`config/`) necesitan para casar un subárbol y no un nombre suelto.
  La validación de ruta absoluta se ejecuta **antes** del retorno temprano de ruta
  vacía, para que `"/"` también se rechace.
- Nuevo `fold_relpath`: `casefold()` usado **sólo para comparar**, nunca para
  construir una ruta. `is_protected_path` compara en esa forma, con
  `fnmatch.fnmatchcase` sobre el texto ya plegado.
- `is_protected_path` trata una ruta de traversal como protegida en lugar de
  mutilarla.
- `extract_package_zip` valida cada miembro con `resolve()` contra el destino antes
  de extraer.

`updater/github_sync_updater.py`
- `normalize_relpath` pasa de `lstrip("./")` a una expresión regular que elimina
  sólo el prefijo `./` repetido, conservando el punto de los dotfiles. Eso arregla
  de paso `is_builtin_ignored` (`.git/`, `.venv/`) y `build_raw_url`.
- Nuevos `is_path_traversal` (rechaza `..`, absolutas, unidades, UNC y `~`) y
  `resolve_inside` (resuelve y confina bajo una raíz).
- `is_path_allowed` devuelve `False` y `is_path_protected` devuelve `True` ante
  traversal; ambos comparan plegados.
- Staging, backup e instalación resuelven su destino con `resolve_inside`.

### 3.2 Drenaje seguro de logs — `services/process_service.py`

- `finish_log_updates()` deja de esperar sobre `queue.Queue.unfinished_tasks` (un
  atributo interno) y hace `worker.join(timeout=_LOG_DRAIN_TIMEOUT_SECONDS)` sobre
  el hilo real.
- Nuevo `log_updates_closed` (`threading.Event`): una vez cerrado, el worker
  descarta cualquier update pendiente. Se comprueba dos veces, la segunda **dentro**
  del lock, para cerrar la ventana entre la comprobación y la escritura.
- Nuevo `log_service_lock`: todas las llamadas al servicio de logs —las del worker y
  las del hilo de la corrida— pasan por él, así que el mismo cliente nunca se usa
  concurrentemente, y un update en vuelo no puede aterrizar *después* de
  `finish_process()`.
- `_finish_process_log` toma el lock con timeout; si el cliente sigue ocupado se
  renuncia a la fila remota en lugar de bloquear la corrida.
- El resultado local se persiste siempre, y un fallo al persistirlo se registra como
  warning. Los warnings de logging nunca cambian el estado final de la corrida.

### 3.3 Cierre cooperativo — `ui/main_app/window.py`, `services/process_service.py`

Nuevo en `ProcessService`: `begin_shutdown()` (deja de aceptar corridas y activa el
`cancel_event` de cada corrida viva), `active_run_count()`, `is_closing()` y un
registro `_active_runs` por hilo. `execute()` pasa a ser un envoltorio de
`_execute_run` con `finally` que desregistra.

`_handle_app_close` ahora: pide confirmación nombrando cuántas corridas hay y qué se
va a esperar → solicita cancelación → deshabilita los botones → informa que está
cerrando → un hilo de cierre **espera** hasta `SHUTDOWN_GRACE_SECONDS` (30 s) a que
cada worker termine su propio `finally` (liberar la foto, borrar temporales,
persistir el resultado, cerrar Playwright) → **sólo entonces**
`process_service.shutdown()` → destruye la UI.

El orden anterior estaba invertido: destruía los navegadores primero, lo que
garantizaba que toda limpieza en vuelo fallara. Si un worker no responde dentro del
plazo, la UI lo dice explícitamente ("puede quedar una foto reservada y un Chrome
abierto") en lugar de fingir que la limpieza terminó. `daemon=True` se mantiene sólo
como último recurso para que el ejecutable congelado pueda salir.

### 3.4 Thread-safety del uploader — `ui/uploader/panel.py`

El worker ya no llama a **ningún** método de Tk, `after()` incluido (`Misc.after` es
en sí una llamada al intérprete Tcl, así que delegar con `after` desde el worker era
el mismo defecto). El worker sólo llena buffers bajo `_progress_lock` y publica un
`_terminal_event`; un poller en el hilo de UI (`_UI_POLL_INTERVAL_MS = 80`) los drena
y aplica el resultado. Se conservan el coalescing por ventana de tiempo, el orden de
los resultados (los `dict` mantienen el orden de inserción) y la restauración de
controles en éxito y error. `destroy()` detiene el poller, de modo que cerrar el
panel durante una carga no deja callbacks contra widgets destruidos.

### 3.5 Fotos y reset del pool

Nuevo `core/storage_errors.is_storage_object_missing`, usado por
`ProcessPhotoService._is_storage_missing_error` y
`PhotoCleanupService._is_storage_missing_error`. Sólo devuelve `True` ante evidencia
inequívoca a nivel de objeto. Devuelve `False` —y por tanto no destruye nada— ante
bucket inexistente, RLS, 401/403, JWT, timeout, error de red, 5xx, 429 y cuota, y
ante los tipos `TimeoutError` / `ConnectionError` / `socket.*` / `OSError`. Un
`"not found"` sin calificar tampoco basta.

`scripts/reset_photo_pool.py`: la fase de base de datos aplica los mismos
`--bucket` y `--prefix` que la fase de Storage, filtra por `storage_bucket` cuando el
usuario nombró buckets, no toca candidatos `pending` fuera del prefijo, rechaza un
prefijo vacío (que habría recorrido el bucket entero) y **imprime el alcance en DB —
filas de `photos` y candidatos pendientes— antes de modificar nada, también en
dry-run**. El dry-run existente se conserva.

### 3.6 UI/UX

- `ON_ACCENT` aplicado a los botones "Entrar"/"Registrar" del login, que usaban
  blanco fijo. Ratios reales medidos y ahora documentados en `ui/theme.py`:
  claro `#2A1B08` sobre `#D97A2B` = **5,38:1**, sobre `WARNING #C7832A` = **5,33:1**;
  oscuro `#1a1205` sobre `#ff8800` = **7,75:1**, sobre `WARNING #e6a451` = **8,65:1**.
  Los valores que sustituye no llegaban a AA: blanco sobre `ACCENT` es 3,10:1 en
  claro y 2,39:1 en oscuro.
- `confirm_destructive_action` acepta `reversible=True` y `undo_hint`: deshabilitar
  un usuario, rechazar un video y descartar filas rotas ya no dicen "no se puede
  deshacer", porque se pueden deshacer, y explican cómo.
- El mensaje del uploader ya no afirma que todos los fallos van a
  `local_data/failed_uploads`: sólo los fallos no reintentables y los de base de
  datos se mueven allí; los errores temporales de Storage dejan el archivo donde
  está.
- Tildes restauradas en los mensajes de progreso de los tres sitios
  ("Extensión reporta…", "Extensión detectó…", "de forma rígida").
- Nuevo `ui/shared/errors.safe_error_summary`: registra la excepción completa en el
  log y muestra al usuario sólo el tipo. El texto de una excepción de Supabase,
  Storage, Playwright o pydantic lleva rutas de almacenamiento, contenidos de fila,
  URLs con claves y lo que el usuario acaba de escribir. 15 mensajes convertidos.

### 3.7 Diagnósticos y Playwright

`BrowserSession` registra el hilo que creó la sesión y expone
`is_owned_by_current_thread()`. `export_extension_state` y
`_build_slot_diagnostic_snapshot` lo consultan antes de tocar nada: desde el hilo de
Tk —que nunca es el dueño, porque las sesiones se crean en el worker de la corrida—
no se hace ninguna llamada en vivo, se usa el snapshot capturado durante la corrida y
el payload lo dice (`live_capture: False` más una nota). No se refactorizó
`BrowserManager` más allá de añadir ese registro y el predicado.

---

## 4. Archivos

**Modificados (36):** `.env.example`, `.gitignore`, `AGENTS.md`,
`automation/browser_manager.py`, `automation/compinche_site.py`,
`automation/paripe_site.py`, `automation/ready4drive_site.py`,
`browser_extension/ui/overlay.js`, `config/settings.py`, `requirements.txt`,
`scripts/build_release.py`, `scripts/reset_photo_pool.py`,
`services/photo_cleanup_service.py`, `services/process_photo_service.py`,
`services/process_service.py`, `ui/access/login_window.py`, `ui/admin_auth.py`,
`ui/main_app/admin_dialogs.py`, `ui/main_app/agent_name_dialog.py`,
`ui/main_app/form_panel.py`, `ui/main_app/photo_review_panel.py`,
`ui/main_app/process_slot_panel.py`, `ui/main_app/settings_dialog.py`,
`ui/main_app/user_access_panel.py`, `ui/main_app/window.py`, `ui/shared/dialogs.py`,
`ui/theme.py`, `ui/uploader/panel.py`, `updater/apply_update_helper.py`,
`updater/github_sync_updater.py`, y 6 archivos de tests preexistentes adaptados.

**Nuevos (12):** `core/storage_errors.py`, `ui/shared/errors.py`,
`requirements-dev.txt`, `scripts/__init__.py`, `docs/auditoria-2026-09-22.md`, y 7
archivos de tests.

**Sin tocar, verificado:** `packaging/` completo y `.env`
(`git status --porcelain packaging/ .env` no devuelve nada).

---

## 5. Pruebas ejecutadas

Entorno: la suite se ejecuta en Windows con `.venv\Scripts\python.exe`. Aquí se
ejecutó sobre una copia exacta del árbol con Python 3.12 + tkinter, porque
`customtkinter` se importa en tiempo de import y sin `tkinter` la recolección falla
entera.

```
python -m py_compile automation\paripe_site.py          OK
python -m py_compile automation\compinche_site.py       OK
python -m py_compile automation\ready4drive_site.py     OK
python -m py_compile services\process_service.py        OK
python -m pytest tests\test_paripe_site.py               42 passed
python -m pytest tests\test_process_service.py           30 passed
python -m pytest tests -q                               567 passed en 32s
git diff --check                                        sin hallazgos
```

Suites nuevas y las que tocan cada área, ejecutadas por separado:

```
updater   (path_safety + apply_update_helper + github_sync_updater)   100 passed
uploader  (test_uploader_panel.py)                                      7 passed
cierre    (test_window_shutdown.py)                                     6 passed
fotos     (storage_error_classification + process_photo + cleanup)      71 passed
reset     (test_reset_photo_pool_scope.py)                              21 passed
diag+ui   (diagnostics_thread_safety + ui_confirmations + admin_pwd)    20 passed
```

Detalle de las suites nuevas:

| Suite | Tests | Cubre |
|---|---|---|
| `tests/test_updater_path_safety.py` | 80 | mayúsculas, separadores Windows y POSIX, dotfiles, traversal, UNC, rutas permitidas, directorios protegidos, confinamiento en staging/backup/instalación |
| `tests/test_storage_error_classification.py` | 42 | objeto ausente, bucket ausente, 401/403, RLS, JWT, timeout, red, 5xx, 429, cuota, tipos de excepción |
| `tests/test_reset_photo_pool_scope.py` | 21 | bucket personalizado, prefijo personalizado, prefijo vacío rechazado, candidatos fuera de alcance, conteo previo sin escribir |
| `tests/test_uploader_panel.py` | 7 | hilo real; ningún método Tk desde el worker; error por buffer; orden de resultados; coalescing; cierre del panel a mitad de carga |
| `tests/test_window_shutdown.py` | 6 | cerrar sin corridas, rechazar el cierre, cierre confirmado con orden limpieza→teardown, worker que no responde, cierre reentrante |
| `tests/test_window_diagnostics_thread_safety.py` | 9 | sesión ajena nunca tocada, sesión propia sí, fallback de frames |
| `tests/test_ui_confirmations.py` | 11 | irreversible vs reversible, contraste AA por modo, barra determinada/indeterminada, ningún `{exc}` crudo en `ui/` |
| `tests/test_admin_password_policy.py` | 3 | fail-closed sin `ADMIN_ACCESS_PASSWORD` |

**Verificación de que los tests nuevos detectan el fallo** (revertir el arreglo y
comprobar que el test se pone en rojo):

| Arreglo revertido | Resultado |
|---|---|
| `join` acotado en `finish_log_updates` | el test queda colgado 60 s y luego falla |
| validación de miembros del ZIP | `test_extract_package_zip_refuses_zip_slip` en rojo |
| códigos de estado con límites de dígito | 5 fallos en `test_storage_error_classification.py` |
| validación del `--prefix` | 6 fallos en `test_reset_photo_pool_scope.py` |
| guarda de reentrada del cierre | `test_a_second_close_while_the_dialog_is_open_does_not_stack_another` en rojo |

**Revisión visual**: se renderizaron bajo Xvfb las pantallas modificadas (segmento
Entrar/Registrar y botones de limpieza del panel admin) y **se conservó la captura**
como evidencia: `revision-visual-ui-2026-09-22.png`. Estilo oscuro y compacto
intacto, texto oscuro legible sobre naranja. La primera versión de este informe
presentó como verificada una revisión visual de la que no se había guardado
evidencia; esa afirmación queda corregida.

---

## 6. Matices de la primera versión de este informe

| Ref. | Lo que decía | Corrección |
|---|---|---|
| **C2** | "Zip Slip" con explotación implícita | No se reprodujo un paquete malicioso. `extractall()` efectivamente no valida los miembros, pero el paquete lo produce el propio proyecto: la validación añadida es **defensa adicional**, no el cierre de una explotación demostrada. |
| **C3** | Path traversal en `github_sync_updater` | Correcto y reproducible; se mantiene. Se añade que el mismo `normalize_relpath` rompía los dotfiles, lo que anulaba también `BUILTIN_EXCLUDED_PREFIXES`. |
| **C4** | `browser_extension.pem` versionado | Sigue siendo cierto. La rotación y la purga del historial **no** se han hecho: quedan fuera del alcance de esta fase. Añadir `*.pem` a `.gitignore` no elimina nada del historial. |
| **C5** | RLS condicional con `sql/001-003` vacíos | Se mantiene como hallazgo, pero es **hipótesis sobre una provisión limpia**: no se verificó contra el proyecto Supabase real, y no se tocó el esquema. |
| **A17** | `photo_review_service` traga excepciones con `pass` | Se mantiene como hallazgo verificado, **sin corregir**: toca la lógica de revisión de fotos, fuera del alcance autorizado de esta fase. |
| **`.env` en releases** | Se presentó como vulnerabilidad crítica | Incorrecto para los empaquetadores internos: ver §0. El cambio en `scripts/build_release.py` es correcto y se mantiene, porque ese script produce el paquete **sin** credenciales. |
| **`.venv`** | "inutilizable desde Windows" | Falso. La suite se ejecuta con `.venv\Scripts\python.exe`. Lo cierto es que un `.venv` de Windows no se ejecuta desde un shell Linux, que es otra cosa. |

---

## 6b. Regresiones encontradas en la revisión posterior del propio diff

La revisión con criterio senior del diff encontró seis defectos **introducidos por la
primera tanda de arreglos**. Todos corregidos, todos con test:

| Sev. | Dónde | Qué pasaba |
|---|---|---|
| Alta | `core/storage_errors.py` | Los códigos de estado se buscaban como subcadenas sueltas contra el texto completo. Un objeto real cuyo nombre contuviera `500`, `429`… (`available/1758500123_foto.jpg`) hacía que un 404 legítimo se clasificara como ambiguo, y la fila huérfana no se limpiaba nunca. Ahora se buscan con límites de dígito. |
| Alta | `core/storage_errors.py` | `"rls"` es subcadena de `"urls"`: un error 404 cuyo texto incluyera un campo `urls` quedaba reclasificado como desconocido. Ahora `\b(rls|dns)\b`. |
| Media | `ui/uploader/panel.py` | Si `_apply_progress_update` lanzaba (widget hijo destruido, error de CTk), la excepción salía del callback de `after`, el poller no se reprogramaba y el evento terminal nunca se consumía: los controles quedaban deshabilitados para siempre. Ahora el repintado va en `try/except` con log. |
| Baja | `scripts/reset_photo_pool.py` | `--prefix` se interpolaba directo en un `like()` de PostgREST ejecutado con la service-role key; un prefijo con `,`, `%` o `)` podía ampliar el UPDATE. Ahora sólo se aceptan `[A-Za-z0-9._-/]`. |
| Baja | `ui/main_app/window.py` | `askyesno` bombea el bucle de Tk, así que un segundo WM_DELETE durante el diálogo reentraba en `_handle_app_close` y apilaba otra confirmación. Ahora hay `_close_prompt_open` (atributo de clase, porque el `__getattr__` de Tk recursa en un widget sin `__init__`). |
| Baja | `services/process_service.py` | `log_worker_started` se marcaba antes de `Thread.start()`: si la creación del hilo fallaba, `finish_log_updates()` hacía join a un hilo que nunca arrancó y descartaba todos los updates **sin aviso**. Ahora se marca después. |

La misma revisión confirmó como correctos: la interacción lock/join del drenaje de
logs, el registro `_active_runs` por hilo, la ausencia de llamadas a Tk en el worker
del uploader, el presupuesto compartido del cierre, el plegado de mayúsculas del
actualizador, el cambio de `normalize_relpath`, `scope_bucket=False` y el registro de
hilo propietario de `BrowserSession`.

---

## 7. Riesgos nuevos detectados durante la revisión

1. **Comparación plegada de rutas protegidas.** Un archivo del repositorio que se
   llamara `Config/…` o `Local_Data/…` con otra capitalización pasaría ahora a
   considerarse protegido y no se actualizaría. Es el comportamiento correcto en
   Windows y macOS, pero en Linux serían archivos distintos. Trade-off aceptado: el
   objetivo del actualizador son Windows y macOS.
2. **`_finish_process_log` con timeout de lock.** Si el cliente de logs queda
   colgado, la fila remota no se cierra y `process_log_id` queda en `None`. Es
   intencional —la corrida no se bloquea y el resultado local sí se persiste— pero
   deja filas de `process_logs` abiertas que alguien debería barrer.
3. **`daemon=True` sigue siendo la salida de emergencia.** Si un worker no responde
   en 30 s, el intérprete lo mata y su `finally` no corre. La UI lo informa, pero
   puede quedar una foto reservada y un Chrome huérfano. Mitigable sólo si la
   automatización comprueba `cancel_event` con más frecuencia.
4. **Sin captura en vivo de diagnósticos desde la UI.** Correcto por seguridad de
   hilos, pero el export ya no refleja el estado del navegador en ese instante sino
   el último capturado durante la corrida. Está marcado en el payload.
5. **`scripts/__init__.py` nuevo.** Hacía falta para poder testear
   `reset_photo_pool.py`. Convierte `scripts/` en paquete; no afecta al empaquetado
   (los specs no incluyen `scripts/`), pero conviene saberlo.

---

## 8. Pendiente — fuera del alcance de esta fase

No implementado, documentado a petición:

1. **Supabase**: esquema, funciones, grants, RLS y políticas. Incluye `sql/001`,
   `002` y `003` vacíos, el `enable row level security` condicional de `sql/006`,
   `sql/014` (`SECURITY DEFINER` sin comprobación de admin y con bucket controlado
   por el llamante) y las RPC de `sql/011` y `sql/013` otorgadas a `authenticated`.
2. **Clic final de Paripe**: el reintento ciego de `automation/base_site.py:282` y
   `paripe_site.py:3565` rompe la invariante "no doble clic final";
   `final_result_done` no se emite en las rutas de fallo (invariante 6).
3. **Flow State Detector**: `_FINAL_BUTTON_TEXTS` con `"confirmar"`/`"enviar"` como
   subcadenas, `_ERROR_TEXTS` con el token suelto `"error"`, y `_safe_buttons_text`
   consultando `document` en vez del contexto recibido.
4. **`browser_extension.pem`**: no rotado ni eliminado; sigue en el historial.
5. **Permisos `<all_urls>` de la extensión**: sin cambios. Acotarlos a los tres
   dominios podría romper los iframes de verificación de terceros.
6. **Rotación de contraseñas, tokens o claves**: no realizada.
7. **`services/photo_review_service.py`**: `_remove_candidate_storage` traga toda
   excepción con `pass` y el llamante marca el candidato como procesado igualmente.
8. **`automation/paripe_site.py:2747`**: la comprobación de `failure_markers` en el
   bucle de espera de bloque sigue siendo inalcanzable (`continue` incondicional
   delante). Activarla tal cual haría abortar corridas por texto incidental de la
   página, porque `failure_markers` incluye el token suelto `"error"`.
9. **Sin cancelación manual desde la UI**: `begin_shutdown()` ya activa el
   `cancel_event`, así que el mecanismo existe; falta el botón "Detener proceso" por
   slot. Es la mejora de producto de mayor impacto pendiente.
10. **Sin commits, push, releases, PKG, instaladores ni despliegues.** Nada de
    `build/`, `dist/`, `releases/`, `local_data/` ni `storage/` fue eliminado.

---

## 9. Recomendaciones posteriores, por prioridad

1. Botón de cancelar por slot (punto 9 de arriba).
2. Cobertura de los scripts de `scripts/`: `migrate_photos_bucket_to_photo_pool.py`
   sigue con un bucle infinito en `--reconcile-db-source --apply` y un
   `object_exists` que descarga el objeto entero y trata cualquier excepción como
   ausencia.
3. Timeouts HTTP en `ClientOptions` (`storage/supabase_client.py`): hoy no hay
   ninguno configurado.
4. Paginación: `photo_review_service.py:581` y `maintenance_service.py:112` se
   apoyan en el límite por defecto de PostgREST.
5. Barrido de filas de `process_logs` que quedaron abiertas (riesgo 2 de §7).
6. Lockfile con hashes para builds reproducibles.
