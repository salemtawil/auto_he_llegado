"""El modo diagnostico: grabar lo que aparece en pantalla, para no adivinar.

Cuando el sitio cambia -un dialogo nuevo, una opcion que antes no estaba- la
unica informacion disponible era una captura de pantalla, y de una captura no
sale un selector. Con el inventario de elementos y el HTML del dialogo si.

Esta apagado salvo que un admin lo marque en su panel: cada captura cuesta un
evaluate sobre la pagina real.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from automation.base_site import BaseSite
from core.models import ProcessExecutionRequest
from services.diagnostic_recorder import (
    MAX_HTML,
    SELECTORES,
    TERMINOS_DE_INTERES,
    DiagnosticRecorder,
)

RAIZ = Path(__file__).resolve().parents[1]
VENTANA = (RAIZ / "ui" / "main_app" / "window.py").read_text(encoding="utf-8")
PANEL = (RAIZ / "ui" / "main_app" / "process_slot_panel.py").read_text(encoding="utf-8")


class _RaizFalsa:
    """Imita lo justo de una Page: `evaluate` y `wait_for_timeout`."""

    def __init__(self, respuestas) -> None:
        self._respuestas = list(respuestas)
        self.llamadas = 0

    def evaluate(self, _js, _opciones=None):
        self.llamadas += 1
        respuesta = self._respuestas[min(self.llamadas - 1, len(self._respuestas) - 1)]
        if isinstance(respuesta, Exception):
            raise respuesta
        return respuesta

    def wait_for_timeout(self, _ms) -> None:
        pass


def _captura(*, url="https://sitio/x", texto=("Hola",), html="<div>hola</div>"):
    return {
        "url": url,
        "titulo": "He llegado",
        "elementos": {nombre: [] for nombre in SELECTORES},
        "coincidencias": {},
        "texto_visible": list(texto),
        "html": html,
        "hay_dialogo": True,
    }


# --- el grabador -----------------------------------------------------------


def test_guarda_lo_que_lee_con_el_momento_y_el_tiempo() -> None:
    grabador = DiagnosticRecorder()
    grabador.capturar(_RaizFalsa([_captura()]), "dialogo_del_propietario", patron="x")

    datos = grabador.exportar()
    assert datos["total_capturas"] == 1
    captura = datos["capturas"][0]
    assert captura["momento"] == "dialogo_del_propietario"
    assert captura["contexto"] == {"patron": "x"}
    assert isinstance(captura["ms_desde_el_inicio"], int)
    assert captura["instante"]


def test_no_guarda_dos_veces_la_misma_pantalla() -> None:
    """Un bucle de espera llamaria a capturar cada 150 ms.

    Guardar cuarenta copias del mismo dialogo no aporta nada y hace el
    archivo imposible de leer.
    """

    raiz = _RaizFalsa([_captura()])
    grabador = DiagnosticRecorder()
    for _ in range(10):
        grabador.capturar(raiz, "mismo_momento")

    datos = grabador.exportar()
    assert datos["total_capturas"] == 1
    assert datos["descartadas_por_repetidas"] == 9


def test_la_misma_pantalla_en_otro_momento_si_se_guarda() -> None:
    raiz = _RaizFalsa([_captura()])
    grabador = DiagnosticRecorder()
    grabador.capturar(raiz, "antes_de_pulsar")
    grabador.capturar(raiz, "despues_de_pulsar")

    assert grabador.exportar()["total_capturas"] == 2


def test_un_fallo_al_leer_no_tumba_la_corrida_y_queda_anotado() -> None:
    grabador = DiagnosticRecorder()
    grabador.capturar(_RaizFalsa([RuntimeError("la pagina se fue")]), "momento")

    datos = grabador.exportar()
    assert datos["total_capturas"] == 0
    assert datos["fallos_de_captura"][0]["momento"] == "momento"
    assert "RuntimeError" in datos["fallos_de_captura"][0]["error"]


def test_hay_un_tope_de_capturas_y_se_conservan_los_extremos() -> None:
    """El principio y el final son los dos trozos que siempre hacen falta.

    Por eso, al pasarse del tope, se tira por el medio y no por delante.
    """

    grabador = DiagnosticRecorder(max_capturas=10)
    for numero in range(40):
        grabador.capturar(_RaizFalsa([_captura(url=f"https://sitio/{numero}")]), "paso")

    capturas = grabador.exportar()["capturas"]
    assert len(capturas) == 10
    assert capturas[0]["url"] == "https://sitio/0", "se perdio el arranque"
    assert capturas[-1]["url"] == "https://sitio/39", "se perdio el final"


def test_los_textos_que_siempre_interesan_cubren_el_dialogo_nuevo() -> None:
    # Es lo que hace que una opcion dibujada como <div> suelto aparezca en el
    # archivo aunque no caiga en ningun selector de control.
    terminos = " | ".join(TERMINOS_DE_INTERES)
    for obligatorio in ("Omitir verificaci", "Cuenta prestada", "Enviar enlace"):
        assert obligatorio in terminos


# --- el enganche con la corrida -------------------------------------------


class _Sitio(BaseSite):
    site_name = "prueba"
    _ENTRY_URL = "https://ejemplo/login"

    def execute(self, *args, **kwargs):  # pragma: no cover - abstracto
        raise NotImplementedError

    def _record_run_stat(self, *_args, **_kwargs) -> None:
        pass


def test_apagado_por_defecto_no_toca_la_pagina() -> None:
    sitio = _Sitio()
    raiz = _RaizFalsa([_captura()])

    sitio._capturar(raiz, "momento")  # noqa: SLF001

    assert raiz.llamadas == 0, "sin diagnostico no se puede pagar un evaluate"
    assert sitio._build_diagnostico_export() == {"activo": False}  # noqa: SLF001


def test_se_enciende_solo_si_la_peticion_lo_pide() -> None:
    sitio = _Sitio()
    sitio._preparar_diagnostico(  # noqa: SLF001
        ProcessExecutionRequest(
            page_name="Compinche",
            action_name="He llegado",
            phone_number="8095551234",
            password="x",
            agent_name="Agente Local",
            debug_enabled=True,
        )
    )
    raiz = _RaizFalsa([_captura()])
    sitio._capturar(raiz, "momento")  # noqa: SLF001

    exportado = sitio._build_diagnostico_export()  # noqa: SLF001
    assert exportado["activo"] is True
    assert exportado["total_capturas"] == 1


def test_una_peticion_normal_lo_deja_apagado() -> None:
    sitio = _Sitio()
    sitio._preparar_diagnostico(  # noqa: SLF001
        ProcessExecutionRequest(
            page_name="Compinche",
            action_name="He llegado",
            phone_number="8095551234",
            password="x",
            agent_name="Agente Local",
        )
    )
    raiz = _RaizFalsa([_captura()])
    sitio._capturar(raiz, "momento")  # noqa: SLF001

    assert raiz.llamadas == 0


def test_los_dos_sitios_lo_encienden_y_lo_exportan() -> None:
    for nombre in ("sitio_de_bloques.py", "paripe_site.py"):
        fuente = (RAIZ / "automation" / nombre).read_text(encoding="utf-8")
        assert "self._preparar_diagnostico(normalized_request)" in fuente, nombre
        assert '"diagnostico": self._build_diagnostico_export(),' in fuente, nombre


# --- la interfaz -----------------------------------------------------------


def test_la_casilla_arranca_oculta_y_apagada() -> None:
    # Un no-admin no debe verla, y dejar de ser admin tiene que apagarla.
    assert "self.debug_checkbox.grid_remove()" in PANEL
    bloque = PANEL[PANEL.index("def mostrar_diagnostico") :][:600]
    assert "self._debug_var.set(False)" in bloque


def test_la_ventana_solo_la_muestra_a_los_admin() -> None:
    bloque = VENTANA[VENTANA.index("def _sync_diagnostico_visible") :][:500]
    assert "self._current_user_is_admin()" in bloque
    assert "mostrar_diagnostico" in bloque


def test_la_peticion_exige_admin_ademas_de_la_casilla() -> None:
    """La casilla sola no basta.

    Si se ocultara mal, o alguien dejara de ser admin con la casilla puesta,
    el estado del widget seguiria diciendo que si.
    """

    bloque = VENTANA[VENTANA.index("def _diagnostico_pedido") :][:1200]
    assert "_current_user_is_admin()" in bloque
    assert "diagnostico_activo" in bloque
    assert "debug_enabled=self._diagnostico_pedido(panel)," in VENTANA


def test_al_terminar_se_pregunta_donde_guardarlo() -> None:
    for metodo in ("_finish_process", "_handle_process_error"):
        inicio = VENTANA.index(f"def {metodo}")
        assert "_ofrecer_guardar_diagnostico" in VENTANA[inicio : inicio + 2500], metodo


def test_si_no_se_grabo_nada_no_se_abre_ningun_dialogo() -> None:
    pytest.importorskip("tkinter", reason="la ventana necesita Tk")
    from ui.main_app.window import MainAppWindow

    vacios = (
        None,
        {},
        {"diagnostico": {"activo": False}},
        {"diagnostico": {"activo": True, "capturas": []}},
    )
    for vacio in vacios:
        assert MainAppWindow._capturas_del_diagnostico(vacio) == []  # noqa: SLF001

    lleno = {"diagnostico": {"activo": True, "capturas": [{"momento": "x"}]}}
    assert len(MainAppWindow._capturas_del_diagnostico(lleno)) == 1  # noqa: SLF001


def test_si_no_hay_donde_preguntar_el_archivo_no_se_pierde() -> None:
    # Perder lo grabado por no poder abrir un dialogo seria el peor final.
    bloque = VENTANA[VENTANA.index("def _ofrecer_guardar_diagnostico") :][:3000]
    assert "if destino is None:" in bloque
    assert "carpeta / nombre" in bloque


def test_el_html_tiene_tope() -> None:
    # Un diagnostico que llena el disco deja de ser una ayuda.
    assert MAX_HTML <= 200_000
    assert "corta(html, opciones.max_html)" in (
        (RAIZ / "services" / "diagnostic_recorder.py").read_text(encoding="utf-8")
    )


def test_ante_la_duda_no_se_graba() -> None:
    """Grabar sin que se haya pedido seria escribir el HTML de la pagina.

    Con lo que lleve dentro, a espaldas de quien esta trabajando. Asi que
    cualquier fallo al preguntarlo tiene que contestar que no.
    """

    pytest.importorskip("tkinter", reason="la ventana necesita Tk")
    from ui.main_app.window import MainAppWindow

    class _VentanaQueFalla:
        _diagnostico_pedido = MainAppWindow._diagnostico_pedido

        def _current_user_is_admin(self):
            raise RuntimeError("la sesion no esta montada todavia")

    class _PanelSinLaOpcion:
        pass

    assert _VentanaQueFalla()._diagnostico_pedido(_PanelSinLaOpcion()) is False  # noqa: SLF001

    class _VentanaAdmin:
        _diagnostico_pedido = MainAppWindow._diagnostico_pedido

        def _current_user_is_admin(self):
            return True

    # Un panel sin la casilla -otro layout, una version vieja- tampoco graba.
    assert _VentanaAdmin()._diagnostico_pedido(_PanelSinLaOpcion()) is False  # noqa: SLF001

    class _PanelConLaOpcion:
        def diagnostico_activo(self):
            return True

    assert _VentanaAdmin()._diagnostico_pedido(_PanelConLaOpcion()) is True  # noqa: SLF001

    class _VentanaNoAdmin:
        _diagnostico_pedido = MainAppWindow._diagnostico_pedido

        def _current_user_is_admin(self):
            return False

    assert _VentanaNoAdmin()._diagnostico_pedido(_PanelConLaOpcion()) is False  # noqa: SLF001
