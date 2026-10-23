"""Con cuatro tarjetas en 2x2 tienen que caber sin barra de desplazamiento.

Dos cosas lo impedian:

- `_apply_visual_layout` ignoraba `self._compact`: la tarjeta se pintaba igual
  con dos paneles que con cuatro.
- A media anchura (unos 620 px) la tarjeta quedaba por DEBAJO del umbral que
  decide si el seguimiento va al lado o debajo del formulario, asi que
  ponerlas en dos columnas las hacia mas ALTAS.
"""

from __future__ import annotations

import ast
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
TARJETA = (RAIZ / "ui" / "main_app" / "process_slot_panel.py").read_text(encoding="utf-8")


def _clase() -> ast.ClassDef:
    return next(
        n for n in ast.walk(ast.parse(TARJETA)) if isinstance(n, ast.ClassDef)
    )


def _constante(nombre: str):
    for n in _clase().body:
        if isinstance(n, ast.Assign):
            for t in n.targets:
                if isinstance(t, ast.Name) and t.id == nombre:
                    return ast.literal_eval(n.value)
    raise AssertionError(f"falta la constante {nombre}")


def _metodo(nombre: str) -> str:
    return next(
        ast.unparse(n)
        for n in _clase().body
        if isinstance(n, ast.FunctionDef) and n.name == nombre
    )


def test_media_ventana_no_obliga_a_apilar_la_tarjeta() -> None:
    # En una ventana de 1280 cada tarjeta mide ~620. Si el umbral queda por
    # encima, al pasar a dos columnas la tarjeta se reorganiza y CRECE.
    ancho_por_tarjeta = (1280 - 60) // 2
    assert _constante("_STACK_BREAKPOINT") < ancho_por_tarjeta, (
        "con este umbral, poner las tarjetas en dos columnas las hace mas altas"
    )


def test_el_umbral_deja_sitio_al_formulario() -> None:
    # Pero tampoco puede bajar tanto que el formulario no quepa a lo ancho.
    assert _constante("_STACK_BREAKPOINT") > _constante("_FORM_MIN_WIDTH")


def test_dos_filas_apretadas_caben_en_la_ventana() -> None:
    # Ventana 1280x760 menos cabecera, insignia del pool y margenes: queda
    # sitio para unos 600 px de tarjetas.
    alto_disponible = 600
    suelo = _constante("_MIN_CARD_HEIGHT_DENSE")
    assert suelo * 2 + 14 <= alto_disponible, (
        f"dos filas de {suelo} px no caben en {alto_disponible}"
    )


def test_el_modo_apretado_se_usa_de_verdad() -> None:
    # Antes `_apply_visual_layout` no miraba `self._compact` y la tarjeta se
    # pintaba igual de grande con cuatro paneles que con dos.
    cuerpo = _metodo("_apply_visual_layout")
    assert "self._compact" in cuerpo, "el modo apretado no se estaba mirando"
    for ajuste in ("corner_radius", "height=alto_boton", "alto_mensaje"):
        assert ajuste in cuerpo, f"el modo apretado no toca {ajuste}"


def test_el_suelo_de_altura_sigue_al_modo() -> None:
    cuerpo = _metodo("natural_height")
    assert "_MIN_CARD_HEIGHT_DENSE" in cuerpo


def test_la_ventana_aprieta_las_tarjetas_cuando_hay_mas_de_dos() -> None:
    ventana = (RAIZ / "ui" / "main_app" / "window.py").read_text(encoding="utf-8")
    cuerpo = next(
        ast.unparse(n)
        for n in ast.walk(ast.parse(ventana))
        if isinstance(n, ast.FunctionDef) and n.name == "_layout_slots"
    )
    assert "len(self.SLOT_IDS) > 2" in cuerpo
    assert "set_compact_layout(apretadas)" in cuerpo
