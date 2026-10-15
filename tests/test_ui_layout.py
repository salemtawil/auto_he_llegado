"""Pruebas de distribución de la UI.

Regresión: en una ventana estrecha los botones "Iniciar proceso", "Limpiar" y
"Exportar debug" quedaban recortados dentro de las tarjetas de Proceso 1 y 2, y
el resumen de la cabecera se cortaba por los dos lados.

Dos causas, ambas cubiertas aquí:

1. Vertical — ``ProcessSlotPanel`` hacía ``grid_propagate(False)`` con una altura
   fija (``_MIN_CARD_HEIGHT``). La tarjeta declaraba siempre esa altura como
   requerida, sin importar lo que midiese su contenido; con fuentes mayores
   (Windows al 125 %) o una ventana baja recibía menos de lo necesario y Tk
   recortaba la última fila, la de los botones.
2. Horizontal — el cuerpo de la tarjeta usaba dos columnas con
   ``uniform="slot_body"``, así que el formulario recibía la mitad del ancho
   aunque necesitase más, y los botones se cortaban por la derecha.

Las pruebas de geometría necesitan un servidor X; se omiten si no lo hay.
"""

from __future__ import annotations

import os

import pytest

from ui.main_app.process_slot_panel import ProcessSlotPanel
from ui.main_app.window import MainAppWindow

needs_display = pytest.mark.skipif(
    not os.environ.get("DISPLAY"), reason="requiere un servidor X para medir geometría"
)


# ---------------------------------------------------------------------------
# Resumen de cabecera (función pura, siempre se ejecuta)
# ---------------------------------------------------------------------------

PARTS = ["Motor: Tradicional", "Activos: 0/2", "Principal: Proceso 1", "Página: Compinche"]


def test_header_summary_completo_en_ventana_ancha() -> None:
    assert MainAppWindow.build_header_summary(PARTS, 1280) == " | ".join(PARTS)


@pytest.mark.parametrize(
    ("width", "esperado"),
    [
        (1280, 4),
        (1100, 3),
        (900, 2),
        (637, 2),
        (400, 2),
    ],
)
def test_header_summary_se_acorta_al_estrechar(width: int, esperado: int) -> None:
    resumen = MainAppWindow.build_header_summary(PARTS, width)
    assert resumen.count(" | ") + 1 == esperado
    # Nunca se pierde lo primero: el motor y los procesos activos.
    assert resumen.startswith("Motor: Tradicional")


def test_header_summary_nunca_queda_vacio() -> None:
    assert MainAppWindow.build_header_summary(PARTS, 1) != ""
    assert MainAppWindow.build_header_summary([], 800) == ""
    assert MainAppWindow.build_header_summary(["Solo uno"], 300) == "Solo uno"


# ---------------------------------------------------------------------------
# Geometría real
# ---------------------------------------------------------------------------


@pytest.fixture()
def tk_root():
    import customtkinter as ctk

    from ui.theme import setup_theme

    setup_theme("dark")
    root = ctk.CTk()
    root.geometry("900x700")
    root.grid_columnconfigure(0, weight=1)
    root.grid_rowconfigure(0, weight=1)
    yield root
    try:
        ctk.set_widget_scaling(1.0)
        root.destroy()
    except Exception:  # noqa: BLE001
        pass


def _build_panel(root, **grid):
    panel = ProcessSlotPanel(
        root,
        title="Proceso 1",
        on_start=lambda: None,
        on_clear=lambda: None,
        on_export_state=lambda: None,
    )
    panel.grid(row=0, column=0, sticky=grid.pop("sticky", "ew"), **grid)
    for _ in range(4):
        root.update_idletasks()
        root.update()
    return panel


def _boton_dentro_de_la_tarjeta(panel) -> tuple[bool, int]:
    """(cabe, margen en px por debajo del botón)."""

    boton = panel.run_button
    fondo = (boton.winfo_rooty() - panel.winfo_rooty()) + boton.winfo_height()
    margen = panel.winfo_height() - fondo
    return margen >= 0, margen


@needs_display
def test_la_tarjeta_propaga_la_geometria_de_su_contenido(tk_root) -> None:
    """La causa raíz del recorte vertical.

    Con ``grid_propagate(False)`` + ``height=_MIN_CARD_HEIGHT`` la tarjeta declaraba
    la constante como altura requerida en vez de medir su contenido, así que la
    última fila (los botones) se recortaba en cuanto el contenido crecía.
    """

    panel = _build_panel(tk_root)

    assert bool(panel.grid_propagate()) is True, (
        "la tarjeta volvió a desactivar la propagación de geometría"
    )
    # La altura requerida es la del contenido, no la constante.
    assert panel.winfo_reqheight() != ProcessSlotPanel._MIN_CARD_HEIGHT
    assert panel.natural_height() >= ProcessSlotPanel._MIN_CARD_HEIGHT


@needs_display
def test_la_altura_requerida_crece_con_el_contenido(tk_root) -> None:
    import customtkinter as ctk

    panel = _build_panel(tk_root)
    base = panel.winfo_reqheight()

    ctk.set_widget_scaling(1.5)
    grande = ProcessSlotPanel(
        tk_root,
        title="Proceso 2",
        on_start=lambda: None,
        on_clear=lambda: None,
        on_export_state=lambda: None,
    )
    grande.grid(row=1, column=0, sticky="ew")
    for _ in range(4):
        tk_root.update_idletasks()
        tk_root.update()

    assert grande.winfo_reqheight() > base


@needs_display
@pytest.mark.parametrize("escala", [1.0, 1.25, 1.5])
def test_los_botones_caben_con_cualquier_escalado(tk_root, escala: float) -> None:
    """1.25 es el escalado típico de Windows y es el que producía el recorte."""

    import customtkinter as ctk

    if escala != 1.0:
        ctk.set_widget_scaling(escala)
    panel = _build_panel(tk_root)

    cabe, margen = _boton_dentro_de_la_tarjeta(panel)
    assert cabe, f"los botones se salen {abs(margen)} px de la tarjeta con escalado {escala}"
    assert margen >= 8, f"hace falta margen visible antes del borde inferior (hay {margen} px)"


@needs_display
@pytest.mark.parametrize("alto", [900, 700, 560, 460])
def test_los_botones_caben_con_cualquier_alto_de_ventana(tk_root, alto: int) -> None:
    tk_root.geometry(f"900x{alto}")
    panel = _build_panel(tk_root)

    cabe, margen = _boton_dentro_de_la_tarjeta(panel)
    assert cabe, f"recorte de {abs(margen)} px con la ventana a {alto} px de alto"


@needs_display
def test_el_formulario_conserva_su_ancho_minimo(tk_root) -> None:
    """El cuerpo ya no reparte el ancho a partes iguales."""

    tk_root.geometry("900x700")
    panel = _build_panel(tk_root)

    columnas = panel.body.grid_columnconfigure(0)
    assert columnas.get("uniform") in (None, ""), "uniform volvería a igualar las columnas"
    assert int(columnas.get("minsize") or 0) >= ProcessSlotPanel._FORM_MIN_WIDTH


@needs_display
def test_el_panel_de_seguimiento_se_apila_en_una_tarjeta_estrecha(tk_root) -> None:
    panel = _build_panel(tk_root)

    panel.apply_width_layout(1200)
    assert panel.status_panel.grid_info()["row"] == 0, "ancha: al lado del formulario"
    assert panel.status_panel.grid_info()["column"] == 1

    panel.apply_width_layout(600)
    assert panel.status_panel.grid_info()["row"] == 1, "estrecha: debajo del formulario"
    assert panel.status_panel.grid_info()["column"] == 0
    assert panel.form_panel.grid_info()["columnspan"] == 2


@needs_display
def test_apply_width_layout_es_idempotente(tk_root) -> None:
    panel = _build_panel(tk_root)

    panel.apply_width_layout(600)
    primera = dict(panel.status_panel.grid_info())
    panel.apply_width_layout(600)
    panel.apply_width_layout(600)
    assert dict(panel.status_panel.grid_info()) == primera


@needs_display
def test_los_botones_caben_tambien_en_la_tarjeta_estrecha(tk_root) -> None:
    """Ancho por debajo del punto de corte: el formulario ocupa toda la tarjeta."""

    tk_root.geometry("640x760")
    panel = _build_panel(tk_root)
    panel.apply_width_layout(600)
    for _ in range(3):
        tk_root.update_idletasks()
        tk_root.update()

    boton = panel.run_button
    derecha = (boton.winfo_rootx() - panel.winfo_rootx()) + boton.winfo_width()
    assert derecha <= panel.winfo_width(), (
        f"el botón se sale {derecha - panel.winfo_width()} px por la derecha"
    )
    assert boton.winfo_width() >= 80, "el botón quedó demasiado estrecho para su texto"
