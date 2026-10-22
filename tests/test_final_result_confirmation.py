"""success=True exige una confirmacion positiva y actual del sitio.

Regresion: un boton que desaparece o se deshabilita, un cambio generico del DOM o
el simple paso de 1,5 s son senales de PROGRESO, no de aceptacion.

- Paripe: tras el click `button_missing` era siempre True (se leia el flag, no el
  DOM), asi que la condicion se reducia a "la firma del DOM cambio durante 1,5 s",
  y esa firma son los primeros 400 caracteres del dialogo y del body.
- Compinche / Ready4Drive: `button_missing` / `button_disabled` / `block_replaced`
  sostenidos 1,5 s devolvian success=True, con los datos del bloque previos al click.

Un bloque que se perdio (lo tomo otro, fallo de red) quedaba registrado como
completado. Ahora, si la respuesta es ambigua hasta el deadline, el resultado es
"no confirmado", nunca exito, y nunca se vuelve a pulsar el boton.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

import automation.paripe_site as paripe_mod
import automation.sitio_de_bloques as bloques_mod

# Compinche y Ready4Drive comparten una sola implementacion desde la
# unificacion, asi que basta con revisarla una vez.
SITIOS = [
    ("paripe", paripe_mod),
    ("bloques", bloques_mod),
]


def _fuente(modulo) -> str:
    return Path(modulo.__file__).read_text(encoding="utf-8")


def _detect_final_result_src(modulo) -> str:
    """Cuerpo de _detect_final_result SIN comentarios.

    Los comentarios explican justamente lo que ya no se hace ("antes devolvia
    success=True..."), asi que deben quedar fuera de las comprobaciones.
    """

    fuente = _fuente(modulo)
    inicio = fuente.index("    def _detect_final_result(")
    resto = fuente[inicio + 10 :]
    fin = resto.index("\n    def ") + inicio + 10
    cuerpo = fuente[inicio:fin]
    return "\n".join(
        linea for linea in cuerpo.splitlines() if not linea.lstrip().startswith("#")
    )


# ---------------------------------------------------------------------------
# Ninguna inferencia devuelve exito
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("nombre", "modulo"), SITIOS)
def test_la_señal_de_progreso_no_construye_un_resultado_exitoso(nombre, modulo) -> None:
    src = _detect_final_result_src(modulo)

    # Localiza la rama que reacciona a boton ausente/deshabilitado/DOM cambiado.
    if nombre == "paripe":
        marcador = "if (button_missing or button_disabled) and signature_changed:"
    else:
        marcador = 'if reaction["signal"] in {"button_missing", "button_disabled", "block_replaced"}:'
    assert marcador in src, f"{nombre}: no se encontro la rama de inferencia"

    inicio = src.index(marcador)
    fin = src.index("\n            else:", inicio)
    rama = src[inicio:fin]

    assert "success=True" not in rama, (
        f"{nombre}: la rama de progreso vuelve a devolver exito"
    )
    assert "_build_final_success_result" not in rama, (
        f"{nombre}: la rama de progreso vuelve a construir un resultado exitoso"
    )
    assert ">= 1.5" not in rama, (
        f"{nombre}: el paso de 1,5 s vuelve a decidir el resultado"
    )


@pytest.mark.parametrize(("nombre", "modulo"), SITIOS)
def test_solo_la_confirmacion_positiva_del_sitio_produce_exito(nombre, modulo) -> None:
    """Cada `success=True` del detector final debe colgar de una senal positiva."""

    src = _detect_final_result_src(modulo)
    señales_positivas = (
        "success_text",            # texto de exito en el iframe
        "_count_success_messages", # marcadores de exito de Paripe
        "extension_final_hint",    # pista de la extension (fuera de alcance)
    )
    for bloque in src.split("success=True")[:-1]:
        contexto = bloque[-1400:]
        assert any(s in contexto for s in señales_positivas), (
            f"{nombre}: hay un success=True sin confirmacion positiva cerca"
        )


# ---------------------------------------------------------------------------
# El error explicito del sitio se evalua primero
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("nombre", "modulo"), [s for s in SITIOS if s[0] != "paripe"])
def test_el_error_del_sitio_se_evalua_antes_que_cualquier_inferencia(nombre, modulo) -> None:
    src = _detect_final_result_src(modulo)
    pos_error = src.index("final_failure_texts")
    pos_exito = src.index('reaction["signal"] == "success_text"')
    pos_inferencia = src.index('reaction["signal"] in {"button_missing"')

    assert pos_error < pos_exito < pos_inferencia, (
        f"{nombre}: el fallo declarado del sitio debe comprobarse primero"
    )


# ---------------------------------------------------------------------------
# Ambiguo hasta el deadline -> "no confirmado"
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("nombre", "modulo"), SITIOS)
def test_el_deadline_devuelve_no_confirmado_y_no_exito(nombre, modulo) -> None:
    src = _detect_final_result_src(modulo)
    cola = src[src.rindex("raise ") :]

    assert 'final_status="unconfirmed"' in cola, (
        f"{nombre}: el deadline debe marcar el resultado como no confirmado"
    )
    assert "Resultado no confirmado" in cola
    assert "PUEDE haberse tomado" in cola, (
        f"{nombre}: el mensaje debe advertir de que el bloque pudo tomarse"
    )
    assert "success=True" not in cola


@pytest.mark.parametrize(("nombre", "modulo"), SITIOS)
def test_el_detector_final_nunca_vuelve_a_pulsar_el_boton(nombre, modulo) -> None:
    src = _detect_final_result_src(modulo)
    for patron in (r"\.click\(", r"_click_locator_resilient\(", r"_dispatch_final_click_once\("):
        assert not re.search(patron, src), (
            f"{nombre}: la deteccion de resultado no puede activar el boton ({patron})"
        )


# ---------------------------------------------------------------------------
# Los datos del bloque se conservan
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("nombre", "modulo"), SITIOS)
def test_se_conservan_los_marcadores_de_exito_reales(nombre, modulo) -> None:
    """No se inventaron senales nuevas: se siguen usando las que ya existian."""

    fuente = _fuente(modulo)
    if nombre == "paripe":
        assert "success_markers" in fuente
        assert '"proceso exitoso"' in fuente
    else:
        assert "final_success_texts" in fuente
        assert '"he llegado enviado"' in fuente
        assert '"bloque tomado"' in fuente
