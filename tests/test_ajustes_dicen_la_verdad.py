"""Las etiquetas de Ajustes tienen que decir lo que el control hace.

Una etiqueta que miente es peor que no tener el control: el agente sube
"el timeout de la foto" para darle mas margen a una subida lenta y lo que
alarga es el flujo entero, incluida la espera de bloque.
"""

from __future__ import annotations

from pathlib import Path

import re

RAIZ = Path(__file__).resolve().parents[1]
DIALOGO = (RAIZ / "ui" / "main_app" / "settings_dialog.py").read_text(encoding="utf-8")
VENTANA = (RAIZ / "ui" / "main_app" / "window.py").read_text(encoding="utf-8")

# Solo las etiquetas de verdad: los comentarios citan los textos viejos para
# explicar por que cambiaron, y eso no puede hacer fallar la prueba.
ETIQUETAS = tuple(re.findall(r'^\s*label="([^"]+)",', DIALOGO, re.M))


def test_hay_etiquetas_que_leer() -> None:
    # Si el regex deja de encajar, las tres pruebas de abajo pasarian solas.
    assert len(ETIQUETAS) >= 8, ETIQUETAS


def test_el_timeout_de_pagina_no_se_llama_de_la_foto() -> None:
    # `page_timeout_seconds` se usa como timeout general y como suelo de la
    # espera de bloque (sitio_de_bloques.py), no solo para la foto.
    assert "timeout de procesamiento de foto" not in ETIQUETAS
    assert any("timeout general de pagina" in e for e in ETIQUETAS)


def test_el_timeout_de_accion_no_se_llama_de_la_respuesta_final() -> None:
    assert "timeout de respuesta final" not in ETIQUETAS
    assert any("timeout general de acciones" in e for e in ETIQUETAS)


def test_el_overlay_dice_que_es_solo_del_navegador_manual() -> None:
    """En una corrida real la extension nunca se carga, asi que no hace nada.

    Solo tiene efecto en los navegadores que abre el admin a mano.
    """

    assert "overlay visual de extension" not in ETIQUETAS
    assert any("navegador manual" in e for e in ETIQUETAS)


def test_los_paneles_visibles_se_guardan_de_verdad() -> None:
    """Ha pasado antes: un campo que el dialogo recoge y el guardado pierde."""

    assert '"visible_process_slots": self.visible_slots_menu.get()' in DIALOGO
    assert "visible_process_slots=self._parse_visible_slots(" in VENTANA
