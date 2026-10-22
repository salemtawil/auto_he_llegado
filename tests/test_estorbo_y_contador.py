"""Dos regresiones de pantalla: el chat que tapa el boton y el contador mudo.

- El chat del sitio recibe un mensaje, su burbuja crece y tapa el boton
  Continuar. El click normal falla (Playwright comprueba que el elemento
  reciba el puntero) y la escalada a force=True disparaba en esas coordenadas,
  o sea EN EL CHAT: se abria el chat y la corrida se quedaba ahi.
- El aviso de deepfakescore salia sin numero: la cuenta estaba solo en otro
  chip.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
FLUJO = (RAIZ / "automation" / "sitio_de_bloques.py").read_text(encoding="utf-8")
# El ayudante de apartar estorbos vive en la base: lo usan los tres sitios.
BASE = (RAIZ / "automation" / "base_site.py").read_text(encoding="utf-8")


def _cuerpo(nombre: str, fuente: str = FLUJO) -> str:
    nodo = next(
        n
        for n in ast.walk(ast.parse(fuente))
        if isinstance(n, ast.FunctionDef) and n.name == nombre
    )
    return ast.unparse(nodo)


def test_no_se_fuerza_el_click_sin_antes_apartar_lo_que_tape() -> None:
    cuerpo = _cuerpo("_click_locator_resilient")
    pos_apartar = cuerpo.index("_apartar_lo_que_tape")
    pos_force = cuerpo.index("force=True")
    assert pos_apartar < pos_force, (
        "forzar con un estorbo delante no es insistir mas: es pulsar otra cosa"
    )


def test_el_click_final_nunca_fuerza() -> None:
    # Force, Space y Enter tambien activan el boton: escalar ahi convertiria un
    # click no confirmado en varios envios reales.
    cuerpo = _cuerpo("_click_locator_resilient")
    marca = "if phase == 'final_submit'"
    assert marca in cuerpo, "desaparecio la rama especial del click final"
    rama = cuerpo[cuerpo.index(marca) :]
    # hasta el final de esa rama: la siguiente sentencia al nivel del metodo
    fin = rama.index("\n    try:")
    rama = rama[:fin]
    for prohibido in ("force=True", "Space", "Enter"):
        assert prohibido not in rama, f"el click final no puede usar {prohibido}"


def test_apartar_devuelve_que_estorbaba_y_nunca_lanza() -> None:
    cuerpo = _cuerpo("_apartar_lo_que_tape", BASE)
    assert "except Exception" in cuerpo, "apartar es un extra, no puede tumbar la corrida"
    assert "return None" in cuerpo


def test_el_js_oculta_el_contenedor_flotante_no_solo_el_iframe() -> None:
    # Los chats son un iframe dentro de un div position:fixed. Ocultar solo el
    # iframe deja el div capturando los clicks igual.
    js = re.search(r'_JS_APARTAR_ESTORBO = r?"""(.*?)"""', BASE, re.S).group(1)
    assert "position" in js and "fixed" in js
    assert "pointer-events" in js
    # visibility y no display: display recoloca la pagina y mueve el boton.
    assert "visibility" in js
    assert "display" not in js


def test_el_contador_de_deepfake_sale_del_mismo_numero_siempre() -> None:
    # Antes el primer reintento anunciaba "reintentos: 1" escrito a mano y los
    # siguientes usaban el contador: dos fuentes para el mismo numero.
    cuerpo = _cuerpo("_complete_selfie_until_block")
    anuncios = re.findall(r"deepfakescore activado \| reintentos: ([^'\"]+)", cuerpo)
    assert anuncios, "se perdio el anuncio de deepfakescore"
    assert all("{attempt}" in a for a in anuncios), (
        f"algun anuncio no usa el contador real: {anuncios}"
    )


def test_el_aviso_de_deepfake_lleva_la_cuenta() -> None:
    ventana = (RAIZ / "ui" / "main_app" / "window.py").read_text(encoding="utf-8")
    nodo = next(
        n
        for n in ast.walk(ast.parse(ventana))
        if isinstance(n, ast.FunctionDef) and n.name == "_schedule_process_progress"
    )
    cuerpo = ast.unparse(nodo)
    assert "deepfakescore x" in cuerpo, (
        "el agente mira este chip: tiene que decir cuantos reintentos lleva"
    )


@pytest.mark.parametrize(
    "modulo", ["automation/sitio_de_bloques.py", "automation/paripe_site.py"]
)
def test_ningun_sitio_fuerza_el_click_sin_apartar_antes(modulo: str) -> None:
    # Paripe tenia su propia copia de _click_locator_resilient y se quedo sin
    # el arreglo la primera vez.
    fuente = (RAIZ / modulo).read_text(encoding="utf-8")
    cuerpo = _cuerpo("_click_locator_resilient", fuente)
    assert cuerpo.index("_apartar_lo_que_tape") < cuerpo.index("force=True"), modulo
