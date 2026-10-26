"""Los paneles de proceso salen de una lista, no de codigo escrito a mano.

Antes eran dos construcciones duplicadas y treinta y dos referencias literales
a "slot_1" y "slot_2" repartidas por window.py: anadir un tercero significaba
tocar todas. Ahora la lista manda, y estas pruebas fallan si alguien vuelve a
escribir un slot a mano.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
VENTANA = (RAIZ / "ui" / "main_app" / "window.py").read_text(encoding="utf-8")


def _clase_ventana() -> ast.ClassDef:
    return next(
        n
        for n in ast.walk(ast.parse(VENTANA))
        if isinstance(n, ast.ClassDef) and n.name == "MainAppWindow"
    )


def _constante(nombre: str):
    for n in _clase_ventana().body:
        if isinstance(n, ast.Assign):
            for t in n.targets:
                if isinstance(t, ast.Name) and t.id == nombre:
                    return ast.literal_eval(n.value)
    raise AssertionError(f"no existe la constante {nombre}")


def test_hay_cuatro_paneles_en_dos_columnas() -> None:
    slots = _constante("SLOT_IDS")
    columnas = _constante("SLOT_COLUMNS")

    assert len(slots) == 4
    assert columnas == 2
    assert len(slots) % columnas == 0, "una rejilla con un hueco no queda simetrica"


def test_los_identificadores_no_se_repiten() -> None:
    slots = _constante("SLOT_IDS")
    assert len(set(slots)) == len(slots)


def test_no_quedan_slots_escritos_a_mano() -> None:
    """Ningun "slot_N" suelto: solo los de la propia constante."""

    arbol = ast.parse(VENTANA)
    # Las cadenas que forman SLOT_IDS son las unicas legitimas.
    de_la_constante: set[int] = set()
    for n in ast.walk(arbol):
        if isinstance(n, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "SLOT_IDS" for t in n.targets
        ):
            de_la_constante = {
                id(h)
                for h in ast.walk(n.value)
                if isinstance(h, ast.Constant) and isinstance(h.value, str)
            }

    sueltos = [
        (n.lineno, n.value)
        for n in ast.walk(arbol)
        if isinstance(n, ast.Constant)
        and isinstance(n.value, str)
        and re.fullmatch(r"slot_\d+", n.value)
        and id(n) not in de_la_constante
    ]
    assert sueltos == [], f"slots escritos a mano: {sueltos}"


def test_el_titulo_sale_de_la_posicion_en_la_lista() -> None:
    import importlib.util

    ruta = RAIZ / "ui" / "main_app" / "window.py"
    arbol = ast.parse(ruta.read_text(encoding="utf-8"))
    clase = next(n for n in ast.walk(arbol) if isinstance(n, ast.ClassDef) and n.name == "MainAppWindow")
    metodos = {
        n.name: ast.unparse(n).replace("@classmethod\n", "")
        for n in clase.body
        if isinstance(n, ast.FunctionDef) and n.name in {"slot_title", "slot_id_por_titulo"}
    }
    espacio = {}
    exec("\n".join(metodos.values()), espacio)  # noqa: S102

    class _Falsa:
        SLOT_IDS = _constante("SLOT_IDS")
        slot_title = classmethod(espacio["slot_title"])
        slot_id_por_titulo = classmethod(espacio["slot_id_por_titulo"])

    assert _Falsa.slot_title("slot_1") == "Proceso 1"
    assert _Falsa.slot_title("slot_4") == "Proceso 4"
    assert _Falsa.slot_title("desconocido") == "desconocido"
    # Y el camino de vuelta, que usan los diagnosticos.
    for slot_id in _Falsa.SLOT_IDS:
        assert _Falsa.slot_id_por_titulo(_Falsa.slot_title(slot_id)) == slot_id
    assert _Falsa.slot_id_por_titulo("lo que sea") == _Falsa.SLOT_IDS[0]


def test_el_tope_de_procesos_no_pasa_del_numero_de_paneles() -> None:
    cuerpo = next(
        ast.unparse(n)
        for n in _clase_ventana().body
        if isinstance(n, ast.FunctionDef) and n.name == "_max_concurrent_processes"
    )
    assert "len(self.SLOT_IDS)" in cuerpo, (
        "el tope estaba escrito a mano: con cuatro paneles tiene que salir de la lista"
    )


def _cuerpo(nombre: str) -> str:
    return next(
        ast.unparse(n)
        for n in _clase_ventana().body
        if isinstance(n, ast.FunctionDef) and n.name == nombre
    )


def test_tener_un_proceso_corriendo_no_apaga_los_demas_botones() -> None:
    """Los cuatro paneles son independientes.

    Antes habia un 2 escrito a mano aqui: con dos corridas vivas, los botones
    "Iniciar" de los otros dos paneles quedaban en gris sin decir por que. Lo
    unico que puede apagarlos es que el usuario no tenga acceso a la app.
    """

    cuerpo = _cuerpo("_sync_run_button_state")
    assert "active_count" not in cuerpo, "el estado del boton no depende de cuantos corren"
    assert "flow_engine" not in cuerpo
    assert "access_blocked" in cuerpo


def test_arrancar_un_proceso_no_mira_cuantos_hay_ya() -> None:
    """La unica razon para no arrancar un panel es que ese panel ya corra."""

    cuerpo = _cuerpo("start_process")
    assert "_max_concurrent_processes" not in cuerpo
    assert "modo paralelo" not in cuerpo
    assert "slot.thread is not None" in cuerpo


def test_un_aviso_general_no_borra_el_progreso_de_un_panel_que_corre() -> None:
    """El agente tiene que poder seguir SU proceso.

    Antes, cualquier aviso de la app -actualizaciones, pool, guardar
    ajustes- se escribia en los cuatro paneles y borraba la linea de
    progreso del que estaba corriendo.
    """

    cuerpo = _cuerpo("_broadcast_status_message")
    assert "slot.thread is None" in cuerpo, "tiene que mirar cuales estan libres"
    assert "incluso_ocupados" in cuerpo
    # Y si no queda ninguno libre se escribe igual: perder un error por no
    # tener donde ponerlo es peor que pisar una linea que se reescribe sola.
    assert "not libres" in cuerpo


def test_los_avisos_del_cierre_si_llegan_a_todos() -> None:
    # Ahi el panel ocupado es justo el que necesita enterarse.
    for aviso in ("Cerrando Playwright", "no respondieron a tiempo", "liberen sus"):
        posicion = VENTANA.index(aviso)
        assert "incluso_ocupados=True" in VENTANA[posicion : posicion + 400], aviso
