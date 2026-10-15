"""Boton de detener proceso (2026-10-14).

Antes, si una corrida se colgaba, la unica salida era cerrar la app entera, lo
que ademas mataba la otra corrida. La infraestructura de cancelacion ya existia
(ProcessRunContext.cancel_event y 6 puntos de control por sitio en base_site),
pero solo se usaba al cerrar la app.

Lo que estas pruebas blindan:
  * detener un panel NO toca al otro (la app permite 2 corridas a la vez);
  * solo se SENALIZA: el cierre del navegador lo hace la propia corrida en su
    hilo, que es lo que la API sync de Playwright exige;
  * el boton principal pasa a "Detener" mientras corre, en vez de quedar gris.
"""

from __future__ import annotations

import threading
from types import SimpleNamespace

import pytest

from services.process_service import ProcessService


def _service_con_corridas(*contextos) -> ProcessService:
    service = ProcessService.__new__(ProcessService)
    service._active_runs = {}  # noqa: SLF001
    service._active_runs_lock = threading.Lock()  # noqa: SLF001
    for indice, contexto in enumerate(contextos):
        service._active_runs[indice] = contexto  # noqa: SLF001
    return service


def _contexto(slot_id: str):
    return SimpleNamespace(slot_id=slot_id, cancel_event=threading.Event())


def test_detener_un_panel_no_toca_al_otro() -> None:
    uno, dos = _contexto("slot_1"), _contexto("slot_2")
    service = _service_con_corridas(uno, dos)

    assert service.request_cancel("slot_1") == 1

    assert uno.cancel_event.is_set() is True
    assert dos.cancel_event.is_set() is False, "la otra corrida debe seguir viva"


def test_detener_sin_corrida_activa_no_hace_nada() -> None:
    service = _service_con_corridas(_contexto("slot_2"))

    assert service.request_cancel("slot_1") == 0


def test_un_slot_vacio_o_invalido_se_ignora() -> None:
    service = _service_con_corridas(_contexto("slot_1"))

    assert service.request_cancel("") == 0
    assert service.request_cancel(None) == 0


def test_is_cancel_requested_refleja_la_peticion() -> None:
    uno, dos = _contexto("slot_1"), _contexto("slot_2")
    service = _service_con_corridas(uno, dos)

    assert service.is_cancel_requested("slot_1") is False
    service.request_cancel("slot_1")
    assert service.is_cancel_requested("slot_1") is True
    assert service.is_cancel_requested("slot_2") is False


def test_detener_solo_senaliza_y_no_cierra_nada_por_su_cuenta() -> None:
    """El cierre lo hace la corrida en SU hilo: Playwright no admite otra cosa."""

    from pathlib import Path

    texto = (
        Path(__file__).resolve().parents[1] / "services" / "process_service.py"
    ).read_text(encoding="utf-8")
    cuerpo = texto.split("def request_cancel(")[1].split("\n    def ")[0]

    assert "cancel_event.set()" in cuerpo
    for prohibido in ("shutdown_all", "kill_driver", "session.close", "BrowserManager"):
        assert prohibido not in cuerpo, (
            f"request_cancel no debe tocar el navegador ({prohibido}): "
            "cerrarlo desde otro hilo falla y dejaria procesos huerfanos"
        )


# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------


def test_el_boton_principal_pasa_a_detener_mientras_corre() -> None:
    from pathlib import Path

    ventana = (
        Path(__file__).resolve().parents[1] / "ui" / "main_app" / "window.py"
    ).read_text(encoding="utf-8")
    cuerpo = ventana.split("def _sync_run_button_state(")[1].split("\n    def ")[0]

    assert 'set_run_button_mode("stop")' in cuerpo
    assert 'set_run_button_mode("start")' in cuerpo
    # Y sobre todo: con corrida activa el boton ya NO queda siempre gris.
    assert 'slot.panel.run_button.configure(state="disabled")' not in cuerpo


def test_detener_pide_confirmacion_y_avisa_del_bloque() -> None:
    """Detener tras el clic final puede dejar el bloque tomado: hay que decirlo."""

    from pathlib import Path

    ventana = (
        Path(__file__).resolve().parents[1] / "ui" / "main_app" / "window.py"
    ).read_text(encoding="utf-8")
    cuerpo = ventana.split("def stop_process(")[1].split("\n    def ")[0]

    assert "confirm_destructive_action" in cuerpo
    assert "bloque" in cuerpo.lower(), "debe advertir del bloque ya tomado"
    assert "request_cancel" in cuerpo


@pytest.mark.parametrize("modo,esperado", [("stop", "stop"), ("start", "start"), ("STOP", "stop")])
def test_el_panel_alterna_de_modo(modo: str, esperado: str) -> None:
    from ui.main_app.process_slot_panel import ProcessSlotPanel

    panel = ProcessSlotPanel.__new__(ProcessSlotPanel)
    panel._run_button_mode = "start" if esperado == "stop" else "stop"  # noqa: SLF001
    registrado: dict = {}
    panel.run_button = SimpleNamespace(configure=lambda **kw: registrado.update(kw))

    panel.set_run_button_mode(modo)

    assert panel.run_button_mode() == esperado
    assert "Detener" in registrado["text"] if esperado == "stop" else "Iniciar" in registrado["text"]
