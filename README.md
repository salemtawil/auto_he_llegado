# Auto He Llegado

App de escritorio interna (Python + customtkinter) que automatiza el flujo
"he llegado" en Paripe, Compinche y Ready4Drive, con Playwright sobre el Google
Chrome instalado y Supabase como almacén de fotos, logs y accesos.

---

## Instalación

Requisitos: **Python 3.12 o superior** y **Google Chrome instalado**.

No hace falta `playwright install`: la app usa el Chrome del sistema
(`channel="chrome"`), no un navegador descargado por Playwright.

```powershell
cd "C:\ruta\al\repo\auto_he_llegado"
py -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Si ya tenías el entorno creado, basta con reinstalar dependencias:

```powershell
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

### Configuración

La app necesita un `.env` con las credenciales de Supabase. Pídeselo al
responsable del proyecto: **no está en el repositorio y no se comparte por
chat ni por correo**. `.env.example` lista las claves que hacen falta.

---

## Abrir la app

```powershell
.venv\Scripts\python.exe app_main.py
```

Otros puntos de entrada:

| Comando | Para qué |
|---|---|
| `.venv\Scripts\python.exe app_uploader.py` | Carga masiva de JPG al pool |
| `.venv\Scripts\python.exe app_debug_inspector.py` | Inspector de depuración |

---

## Pruebas

```powershell
.venv\Scripts\python.exe -m pytest tests -q
```

Fuera de Windows hace falta un Python **con tkinter**: `customtkinter` se
importa al cargar los módulos y sin `tkinter` falla la recolección entera.

Hay pruebas que lanzan navegadores reales y están desactivadas por defecto
porque son lentas:

```powershell
$env:AHL_BROWSER_E2E=1
.venv\Scripts\python.exe -m pytest tests/test_browser_session_leak_real.py -v
```

---

## Migraciones de Supabase

Los archivos de `sql/` se aplican **a mano**, en orden numérico, desde el SQL
Editor de Supabase. No hay un runner automático.

Cada migración con efectos sobre políticas trae su `_rollback.sql` al lado.

> Si la app avisa de que falta aplicar una migración, hazlo antes de seguir: el
> aviso bloquea la operación a propósito, para no trabajar sobre un esquema
> que no es el que el código espera.

Tras aplicar una migración, si PostgREST no se entera:

```sql
notify pgrst, 'reload schema';
```

---

## Cómo funciona, en corto

**Pool de fotos.** Las corridas consumen fotos del *pool activo*
(`app_settings['photo_pool']`). Se alimenta de dos formas: la carga masiva de
JPG, y los vídeos que suben los agentes, cuyos fotogramas pasan por
"Revisión fotos" para aprobarse.

**Exigir vídeo.** Con la política activada, un agente no puede iniciar procesos
hasta subir un vídeo. El desbloqueo ocurre **al subirlo**, sin esperar a que
nadie lo apruebe. Solo un rechazo explícito vuelve a cerrar el acceso.

**Dos procesos a la vez.** La app admite dos corridas simultáneas, cada una con
su propio navegador y su propio proceso driver. Detener una no afecta a la otra.

**Detener una corrida.** Lo normal es **cerrar la ventana del navegador**: la
corrida aborta en unos segundos (Playwright lanza `TargetClosedError` al instante,
sin esperar los timeouts largos del flujo) y un vigilante en segundo plano se
lleva el proceso driver que queda suelto. También existe el botón
"Detener proceso", que es el mismo botón de iniciar mientras hay una corrida
activa; sirve sobre todo cuando aún no hay navegador que cerrar.

> En ambos casos, ojo: si la corrida ya pulsó el botón final en la página, el
> bloque puede haber quedado tomado aunque la detengas. Compruébalo en la página
> antes de reintentar.

**Interruptores.** `config/features.py` tiene las funciones que se pueden
apagar sin tocar código. Cada una documenta por qué está como está.

---

## Para quien vaya a tocar el código

Lee **`AGENTS.md`** antes. Tiene las áreas críticas que no se tocan sin
autorización, las trampas conocidas (afinidad de hilo de Playwright, API
privada de la que depende la limpieza de procesos) y los comandos de validación.
