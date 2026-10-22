"""La foto se da por subida solo con pruebas del hecho, no del entorno.

`_wait_for_uploaded_photo` aceptaba como confirmacion que existiera un boton
"Continuar". Ese boton ya esta en pantalla ANTES de subir nada, asi que
confirmaba siempre: si `set_input_files` fallaba en silencio, se pulsaba
Continuar sin foto y el fallo aparecia mucho despues, con la foto ya gastada.

Incluye ademas un guardian estructural para el fallo que dejo el pool sin
fotos: dos `except` del mismo tipo en el mismo `try`, donde el segundo -el que
liberaba la foto reservada- era inalcanzable. La prueba que existia cubria el
ayudante de limpieza, no si llegaba a llamarse.
"""

from __future__ import annotations

import ast
from pathlib import Path
from time import sleep

import pytest

RAIZ = Path(__file__).resolve().parents[1]
MODULOS_DE_FLUJO = (
    "automation/compinche_site.py",
    "automation/ready4drive_site.py",
    "automation/paripe_site.py",
    "automation/base_site.py",
)


def _handlers_inalcanzables(ruta: Path) -> list[tuple[int, str]]:
    arbol = ast.parse(ruta.read_text(encoding="utf-8"))
    hallados: list[tuple[int, str]] = []
    for nodo in ast.walk(arbol):
        if not isinstance(nodo, ast.Try):
            continue
        vistos: list[str] = []
        for handler in nodo.handlers:
            tipo = ast.unparse(handler.type) if handler.type else "except desnudo"
            if tipo in vistos or "except desnudo" in vistos:
                hallados.append((handler.lineno, tipo))
            vistos.append(tipo)
    return hallados


@pytest.mark.parametrize("modulo", MODULOS_DE_FLUJO)
def test_ningun_except_queda_tapado_por_otro_anterior(modulo: str) -> None:
    # Python entra siempre en el primer except que casa con el tipo. Un segundo
    # except del mismo tipo no se ejecuta nunca, y aqui eso significo que la
    # foto reservada no se liberaba en ningun fallo de bloque.
    inalcanzables = _handlers_inalcanzables(RAIZ / modulo)
    assert inalcanzables == [], (
        f"{modulo} tiene except inalcanzables (linea, tipo): {inalcanzables}"
    )


class _SitioDePrueba:
    """Lo minimo que toca `_wait_for_uploaded_photo`."""

    _POLL_MS = 1

    def __init__(self, *, input_con_archivo=(), texto_pantalla="") -> None:
        self._respuestas = list(input_con_archivo)
        self._texto = texto_pantalla
        self.vueltas = 0
        self.busco_boton_continuar = False

    def _locator_has_uploaded_file(self, _locator) -> bool:
        if not self._respuestas:
            return False
        return self._respuestas.pop(0)

    def _normalized_root_text(self, _root) -> str:
        return self._texto

    def _find_best_text_candidate(self, _root, _textos):
        # Si la implementacion vuelve a preguntar por el boton Continuar, lo
        # sabremos: esta prueba lo deja en evidencia en vez de pasarlo por alto.
        self.busco_boton_continuar = True
        return object()

    def _wait_interval(self, _root, _ms) -> None:
        # Dormir de verdad: si no, el bucle gira cientos de miles de veces
        # hasta agotar el plazo y la prueba se vuelve un quemador de CPU.
        sleep(0.002)
        self.vueltas += 1

    @staticmethod
    def _normalize_text(texto: str) -> str:
        return texto.strip().lower()


def _esperar(sitio, *, nombre="selfie_123.jpg", timeout_ms=30):
    from automation.compinche_site import CompincheSite

    return CompincheSite._wait_for_uploaded_photo(
        sitio,
        object(),
        object(),
        original_filename=nombre,
        timeout_ms=timeout_ms,
    )


def test_confirma_cuando_el_input_tiene_el_archivo() -> None:
    sitio = _SitioDePrueba(input_con_archivo=[True])
    assert _esperar(sitio) is True


def test_confirma_cuando_el_nombre_del_archivo_aparece_en_pantalla() -> None:
    sitio = _SitioDePrueba(texto_pantalla="archivo seleccionado: selfie_123.jpg")
    assert _esperar(sitio) is True


def test_un_boton_continuar_ya_no_basta_para_dar_la_foto_por_subida() -> None:
    # El boton existe (el doble siempre lo devuelve) pero el input esta vacio y
    # el nombre no aparece: la respuesta correcta es que no se pudo confirmar.
    sitio = _SitioDePrueba(texto_pantalla="pulsa continuar para seguir")

    assert _esperar(sitio) is False
    assert sitio.busco_boton_continuar is False, (
        "no debe preguntarse por el boton Continuar: esta en pantalla antes de subir nada"
    )
    assert sitio.vueltas > 0, "debe haber esperado, no rendirse en seco"
