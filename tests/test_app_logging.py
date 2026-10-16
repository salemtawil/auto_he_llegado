"""Pruebas del registro a archivo.

Lo que fijan: que lo que antes se perdia ahora queda escrito. En macOS la app
no emitia ni un diagnostico, y los errores de la interfaz iban a un logger sin
manejador, asi que el detalle se tiraba y al agente solo le quedaba el nombre
del tipo de excepcion en pantalla.
"""

from __future__ import annotations

import logging
import sys
import threading
from pathlib import Path

import pytest

import config.app_logging as registro


@pytest.fixture
def entorno_limpio(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Aisla el estado global que toca el modulo y lo restaura al salir."""

    monkeypatch.setenv("AUTO_HE_LLEGADO_LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.setattr(registro, "_configurado", False)
    monkeypatch.setattr(registro, "_ruta_activa", None)
    monkeypatch.setattr(sys, "stdout", sys.stdout)
    monkeypatch.setattr(sys, "stderr", sys.stderr)
    monkeypatch.setattr(sys, "excepthook", sys.excepthook)
    monkeypatch.setattr(threading, "excepthook", threading.excepthook)

    logger = logging.getLogger(registro.LOGGER_NAME)
    previos = list(logger.handlers)
    raiz_previos = list(logging.getLogger().handlers)
    yield tmp_path
    for handler in list(logger.handlers):
        if handler not in previos:
            handler.close()
            logger.removeHandler(handler)
    for handler in list(logging.getLogger().handlers):
        if handler not in raiz_previos:
            logging.getLogger().removeHandler(handler)
    eco = logging.getLogger(f"{registro.LOGGER_NAME}.salida")
    for handler in list(eco.handlers):
        handler.close()
        eco.removeHandler(handler)


def _contenido(ruta: Path) -> str:
    for handler in logging.getLogger(registro.LOGGER_NAME).handlers:
        handler.flush()
    return ruta.read_text(encoding="utf-8", errors="replace")


def test_crea_el_archivo_y_devuelve_su_ruta(entorno_limpio: Path) -> None:
    ruta = registro.configure_logging()

    assert ruta is not None
    assert ruta.is_file()
    assert registro.ruta_del_log() == ruta


def test_es_idempotente(entorno_limpio: Path) -> None:
    primera = registro.configure_logging()
    segunda = registro.configure_logging()

    assert primera == segunda
    logger = logging.getLogger(registro.LOGGER_NAME)
    # Dos llamadas no pueden dejar el mensaje duplicado en el archivo.
    assert len([h for h in logger.handlers if hasattr(h, "baseFilename")]) == 1


def test_el_print_suelto_acaba_en_el_log(entorno_limpio: Path) -> None:
    ruta = registro.configure_logging()
    assert ruta is not None

    print("LAUNCH PROFILE: /ruta/de/perfil")

    assert "LAUNCH PROFILE: /ruta/de/perfil" in _contenido(ruta)


def test_el_print_sigue_saliendo_por_el_flujo_original(entorno_limpio: Path, capsys) -> None:
    registro.configure_logging()

    print("sigo visible en terminal")

    assert "sigo visible en terminal" in capsys.readouterr().out


def test_el_detalle_de_errores_de_la_interfaz_queda_escrito(entorno_limpio: Path) -> None:
    # safe_error_summary escribe en auto_he_llegado.ui, que hasta ahora no
    # tenia manejador: el traceback se perdia y al agente solo le llegaba el
    # nombre del tipo de excepcion.
    ruta = registro.configure_logging()
    assert ruta is not None
    from ui.shared.errors import safe_error_summary

    try:
        raise TimeoutError("se cerro el navegador")
    except TimeoutError as exc:
        etiqueta = safe_error_summary(exc, context="automatizacion")

    texto = _contenido(ruta)
    assert etiqueta == "TimeoutError"
    assert "se cerro el navegador" in texto
    assert "automatizacion" in texto


def test_excepcion_en_hilo_de_trabajo_queda_escrita(entorno_limpio: Path) -> None:
    # La automatizacion corre fuera del hilo de la interfaz. Antes, una
    # excepcion ahi desaparecia sin dejar rastro.
    ruta = registro.configure_logging()
    assert ruta is not None

    def _revienta() -> None:
        raise RuntimeError("fallo dentro del hilo de automatizacion")

    hilo = threading.Thread(target=_revienta, name="automatizacion")
    hilo.start()
    hilo.join()

    texto = _contenido(ruta)
    assert "fallo dentro del hilo de automatizacion" in texto
    assert "automatizacion" in texto


def test_excepcion_no_capturada_del_hilo_principal_queda_escrita(entorno_limpio: Path) -> None:
    ruta = registro.configure_logging()
    assert ruta is not None

    try:
        raise ValueError("murio el principal")
    except ValueError:
        sys.excepthook(*sys.exc_info())

    assert "murio el principal" in _contenido(ruta)


def test_se_instala_el_gancho_de_callbacks_de_tk(entorno_limpio: Path) -> None:
    tkinter = pytest.importorskip("tkinter")
    original = tkinter.Tk.report_callback_exception

    registro.configure_logging()

    assert tkinter.Tk.report_callback_exception is not original
    tkinter.Tk.report_callback_exception = original


def test_el_entorno_queda_registrado_sin_filtrar_el_env(entorno_limpio: Path) -> None:
    ruta = registro.configure_logging()
    assert ruta is not None
    texto = _contenido(ruta)

    # Lo que hace falta para situar un fallo.
    for clave in ("plataforma", "PROJECT_ROOT", "chrome del sistema", "playwright"):
        assert clave in texto
    # Del .env solo si existe y cuanto ocupa: ni una clave, ni un valor.
    assert ".env presente" in texto
    assert "SUPABASE" not in texto
    assert "KEY=" not in texto


def test_si_no_se_puede_crear_el_log_la_app_sigue(
    entorno_limpio: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Un fallo del registro jamas puede costar una sesion de trabajo.
    def _no_se_puede(_directorio):  # noqa: ANN001
        raise PermissionError("Operation not permitted")

    monkeypatch.setattr(registro, "_crear_manejador", _no_se_puede)

    assert registro.configure_logging() is None


def test_los_avisos_de_librerias_de_terceros_tambien_se_guardan(entorno_limpio: Path) -> None:
    # Playwright, supabase o httpx suelen explicar el fallo mejor que nuestro
    # propio codigo. Si no caen al archivo, se pierde la mitad de la historia.
    ruta = registro.configure_logging()
    assert ruta is not None

    logging.getLogger("playwright").warning("Target page closed")

    assert "Target page closed" in _contenido(ruta)
