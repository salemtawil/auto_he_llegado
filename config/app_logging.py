"""Registro a archivo para la app empaquetada.

Por que existe: hasta ahora el unico diagnostico eran `print()`. En una app
empaquetada sin consola eso no aterriza en ningun sitio, asi que cuando un
agente decia "no me funciona" no habia nada que mirar. En macOS el efecto es
total: lo unico que llega al terminal son los errores que Tcl escribe por su
cuenta, y ni uno solo de los diagnosticos de Python.

Que cubre este modulo, que son las cuatro formas en que esta app puede fallar
sin dejar rastro:

1. `print()` suelto -> se duplica al log (sin perder la salida original).
2. Excepcion no capturada en el hilo principal -> `sys.excepthook`.
3. Excepcion no capturada en un hilo de trabajo -> `threading.excepthook`.
   Esta es la importante: la automatizacion corre fuera del hilo de la interfaz,
   y hasta ahora una excepcion ahi se perdia en silencio.
4. Excepcion dentro de un callback de Tk -> `report_callback_exception`.

Nada aqui puede tumbar la app: si el registro no se puede montar, se sigue sin
el. Un fallo del log jamas debe costar una sesion de trabajo.

NUNCA escribe valores del .env ni ningun secreto: del `.env` solo se registra
si existe y su tamano.
"""

from __future__ import annotations

import logging
import logging.handlers
import os
import platform
import sys
import threading
import traceback
from datetime import datetime
from pathlib import Path

from config.paths import (
    BUNDLE_ROOT,
    DEFAULT_LOGS_DIR,
    ENV_FILE,
    PROJECT_ROOT,
)

LOGGER_NAME = "auto_he_llegado"
_MAX_BYTES = 5 * 1024 * 1024
_COPIAS = 5

_configurado = False
_ruta_activa: Path | None = None


def ruta_del_log() -> Path | None:
    """Donde esta escribiendo ahora mismo, o None si no se pudo montar."""

    return _ruta_activa


class _EcoAlLog:
    """Envoltorio de stdout/stderr que ademas manda cada linea al log.

    Escribe primero en el flujo original (si lo hay) para no robarle la salida
    a quien ejecute desde terminal, y despues al logger de archivo. El logger
    que usa NO tiene manejador de consola, asi que no se puede realimentar.
    """

    def __init__(self, original, logger: logging.Logger, nivel: int) -> None:
        self._original = original
        self._logger = logger
        self._nivel = nivel
        self._pendiente = ""

    def write(self, texto: str) -> int:
        if self._original is not None:
            try:
                self._original.write(texto)
            except Exception:  # noqa: BLE001
                pass
        try:
            self._pendiente += texto
            while "\n" in self._pendiente:
                linea, self._pendiente = self._pendiente.split("\n", 1)
                if linea.strip():
                    self._logger.log(self._nivel, linea.rstrip())
        except Exception:  # noqa: BLE001
            pass
        return len(texto)

    def flush(self) -> None:
        if self._original is not None:
            try:
                self._original.flush()
            except Exception:  # noqa: BLE001
                pass

    def isatty(self) -> bool:
        try:
            return bool(self._original is not None and self._original.isatty())
        except Exception:  # noqa: BLE001
            return False

    def __getattr__(self, nombre: str):
        return getattr(self._original, nombre)


def _crear_manejador(directorio: Path) -> logging.Handler:
    directorio.mkdir(parents=True, exist_ok=True)
    destino = directorio / f"app_{datetime.now():%Y%m%d}.log"
    manejador = logging.handlers.RotatingFileHandler(
        destino, maxBytes=_MAX_BYTES, backupCount=_COPIAS, encoding="utf-8"
    )
    manejador.setFormatter(
        logging.Formatter(
            "%(asctime)s %(levelname)-8s [%(threadName)s] %(name)s: %(message)s"
        )
    )
    manejador.setLevel(logging.DEBUG)
    global _ruta_activa
    _ruta_activa = destino
    return manejador


def _instalar_ganchos(logger: logging.Logger) -> None:
    anterior_sys = sys.excepthook

    def _sys_excepthook(tipo, valor, rastro) -> None:
        try:
            logger.critical(
                "Excepcion no capturada en el hilo principal:\n%s",
                "".join(traceback.format_exception(tipo, valor, rastro)).rstrip(),
            )
        except Exception:  # noqa: BLE001
            pass
        anterior_sys(tipo, valor, rastro)

    sys.excepthook = _sys_excepthook

    def _hilo_excepthook(args) -> None:
        if args.exc_type is SystemExit:
            return
        try:
            logger.critical(
                "Excepcion no capturada en el hilo %s:\n%s",
                getattr(args.thread, "name", "?"),
                "".join(
                    traceback.format_exception(
                        args.exc_type, args.exc_value, args.exc_traceback
                    )
                ).rstrip(),
            )
        except Exception:  # noqa: BLE001
            pass

    threading.excepthook = _hilo_excepthook

    # Tk se traga las excepciones de sus callbacks y solo imprime un aviso
    # suelto por el canal de Tcl. Aqui se registra el traceback entero.
    try:
        import tkinter

        def _tk_excepthook(self, tipo, valor, rastro) -> None:  # noqa: ANN001
            try:
                logger.critical(
                    "Excepcion en un callback de Tk:\n%s",
                    "".join(traceback.format_exception(tipo, valor, rastro)).rstrip(),
                )
            except Exception:  # noqa: BLE001
                pass

        tkinter.Tk.report_callback_exception = _tk_excepthook
    except Exception:  # noqa: BLE001
        pass


def _chrome_del_sistema() -> str:
    candidatos = [
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    ]
    encontrados = [ruta for ruta in candidatos if Path(ruta).exists()]
    return encontrados[0] if encontrados else "no encontrado"


def _se_puede_escribir(directorio: Path) -> str:
    try:
        directorio.mkdir(parents=True, exist_ok=True)
        testigo = directorio / ".escritura_test"
        testigo.write_text("ok", encoding="utf-8")
        try:
            testigo.unlink()
        except Exception:  # noqa: BLE001
            pass
        return "si"
    except Exception as exc:  # noqa: BLE001
        return f"no ({exc.__class__.__name__})"


def _perfil_del_equipo() -> str:
    """RAM, nucleos y perfil con el que arranco la app. Nunca lanza."""

    try:
        from config.machine_profile import describir_equipo

        return describir_equipo()
    except Exception as exc:  # noqa: BLE001 - el encabezado nunca debe fallar
        return f"no se pudo medir ({type(exc).__name__})"


def registrar_entorno(logger: logging.Logger | None = None) -> None:
    """Deja en el log todo lo que hace falta para situar un fallo.

    Del .env solo se anota si existe y cuanto ocupa. Nunca su contenido.
    """

    registro = logger or logging.getLogger(LOGGER_NAME)
    try:
        import playwright

        version_playwright = getattr(playwright, "__version__", "desconocida")
    except Exception:  # noqa: BLE001
        version_playwright = "no importable"

    datos = [
        ("plataforma", f"{platform.system()} {platform.release()} ({platform.machine()})"),
        ("python", sys.version.split()[0]),
        ("empaquetada", str(bool(getattr(sys, "frozen", False)))),
        ("ejecutable", sys.executable),
        ("PROJECT_ROOT", str(PROJECT_ROOT)),
        ("BUNDLE_ROOT", str(BUNDLE_ROOT)),
        ("logs", str(DEFAULT_LOGS_DIR)),
        ("PROJECT_ROOT escribible", _se_puede_escribir(PROJECT_ROOT)),
        (".env presente", str(ENV_FILE.is_file())),
        (
            ".env tamano",
            str(ENV_FILE.stat().st_size) if ENV_FILE.is_file() else "-",
        ),
        ("playwright", version_playwright),
        ("chrome del sistema", _chrome_del_sistema()),
        ("usuario", os.environ.get("USER") or os.environ.get("USERNAME") or "?"),
        ("equipo", _perfil_del_equipo()),
    ]
    registro.info("--- entorno ---")
    for clave, valor in datos:
        registro.info("%-24s %s", clave, valor)
    registro.info("--- fin entorno ---")


def iniciar_rastreo_de_memoria() -> bool:
    """Enciende tracemalloc si AUTO_HE_LLEGADO_TRACEMALLOC=1. Nunca lanza.

    Apagado por defecto: rastrear cada reserva de memoria ralentiza el
    interprete. Se enciende solo para una sesion de diagnostico, cuando hace
    falta saber QUE lineas retienen la memoria en vez de suponerlo.
    """

    if os.getenv("AUTO_HE_LLEGADO_TRACEMALLOC", "").strip() not in {"1", "true", "si"}:
        return False
    try:
        import tracemalloc

        if not tracemalloc.is_tracing():
            tracemalloc.start(15)
        logging.getLogger(LOGGER_NAME).info(
            "Rastreo de memoria ACTIVADO. La app ira mas lenta; es para diagnosticar."
        )
        return True
    except Exception:  # noqa: BLE001
        return False


def registrar_top_de_memoria(limite: int = 12) -> None:
    """Deja en el log las lineas que mas memoria retienen. Nunca lanza."""

    logger = logging.getLogger(LOGGER_NAME)
    try:
        import tracemalloc

        if not tracemalloc.is_tracing():
            return
        instantanea = tracemalloc.take_snapshot().filter_traces(
            (
                tracemalloc.Filter(False, tracemalloc.__file__),
                tracemalloc.Filter(False, __file__),
            )
        )
        estadisticas = instantanea.statistics("lineno")[:limite]
        total_mb = sum(item.size for item in instantanea.statistics("filename")) / (1024 * 1024)
        logger.info("--- memoria rastreada: %.1f MB en total ---", total_mb)
        for puesto, item in enumerate(estadisticas, start=1):
            marco = item.traceback[0]
            logger.info(
                "  %2d. %7.1f MB en %s objetos  %s:%s",
                puesto,
                item.size / (1024 * 1024),
                item.count,
                marco.filename,
                marco.lineno,
            )
        logger.info("--- fin memoria rastreada ---")
    except Exception:  # noqa: BLE001
        pass


def configure_logging(*, capturar_print: bool = True) -> Path | None:
    """Monta el registro a archivo. Idempotente. Nunca lanza.

    Devuelve la ruta del log, o None si no se pudo montar.
    """

    global _configurado
    if _configurado:
        return _ruta_activa

    logger = logging.getLogger(LOGGER_NAME)
    try:
        destino = os.getenv("AUTO_HE_LLEGADO_LOG_DIR", "").strip()
        directorio = Path(destino).expanduser() if destino else DEFAULT_LOGS_DIR
        manejador = _crear_manejador(directorio)
    except Exception:  # noqa: BLE001
        # Sin log se puede trabajar; sin app no.
        _configurado = True
        return None

    logger.setLevel(logging.DEBUG)
    logger.addHandler(manejador)
    logger.propagate = False

    # El manejador tambien en la raiz: asi caen al archivo los avisos de
    # librerias de terceros (playwright, supabase, httpx), que muchas veces
    # explican un fallo mejor que nuestro propio codigo. A INFO para no llenar
    # el archivo con el DEBUG de urllib3.
    raiz = logging.getLogger()
    raiz.setLevel(logging.INFO)
    raiz.addHandler(manejador)

    _instalar_ganchos(logger)

    if capturar_print:
        eco = logging.getLogger(f"{LOGGER_NAME}.salida")
        eco.setLevel(logging.DEBUG)
        eco.propagate = False
        eco.addHandler(manejador)
        sys.stdout = _EcoAlLog(sys.stdout, eco, logging.INFO)
        sys.stderr = _EcoAlLog(sys.stderr, eco, logging.ERROR)

    _configurado = True
    logger.info("=" * 70)
    logger.info("Arranque de Auto He Llegado")
    registrar_entorno(logger)
    iniciar_rastreo_de_memoria()
    return _ruta_activa
