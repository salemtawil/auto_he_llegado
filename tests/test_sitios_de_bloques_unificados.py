"""Compinche y Ready4Drive comparten una sola implementacion.

Antes eran dos archivos de ~3.400 lineas con 151 funciones comunes IDENTICAS
salvo por el nombre del sitio. Cada arreglo habia que copiarlo a mano al otro,
y de ahi salieron las derivas que encontro la auditoria: una version cacheaba
la URL de la pagina y la otra la leia en vivo, y ninguna lo hacia bien.

Estas pruebas fallan si alguien vuelve a bifurcarlos.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]


def test_los_dos_sitios_solo_declaran_sus_constantes() -> None:
    from automation.compinche_site import CompincheSite
    from automation.ready4drive_site import Ready4DriveSite

    for clase in (CompincheSite, Ready4DriveSite):
        propios = {
            nombre
            for nombre, valor in vars(clase).items()
            if not nombre.startswith("__") and callable(valor)
        }
        assert propios == set(), (
            f"{clase.__name__} define metodos propios ({sorted(propios)}): "
            "si hacen falta de verdad, que sean un override explicito y comentado"
        )


def test_cada_sitio_fija_su_nombre_y_su_url() -> None:
    from automation.compinche_site import CompincheSite
    from automation.ready4drive_site import Ready4DriveSite

    assert CompincheSite.site_name == "compinche.io"
    assert CompincheSite._ENTRY_URL == "https://compinche.io/login"  # noqa: SLF001
    assert Ready4DriveSite.site_name == "ready4drive.com"
    assert Ready4DriveSite._ENTRY_URL == "https://ready4drive.com/login"  # noqa: SLF001


def test_la_clase_base_sola_no_se_puede_usar() -> None:
    from automation.sitio_de_bloques import SitioDeBloques

    with pytest.raises(TypeError, match="site_name"):
        SitioDeBloques()


def test_clonar_devuelve_la_clase_real_no_una_fija() -> None:
    # Cada sitio codificaba su clase a mano en clone_for_run, y por eso la v2
    # tenia que sobrescribirlo: una v2 clonada devolvia una v1 y la corrida
    # usaba la automatizacion equivocada en silencio.
    from automation.compinche_site import CompincheSite
    from automation.ready4drive_site import Ready4DriveSite

    for clase in (CompincheSite, Ready4DriveSite):
        assert type(clase().clone_for_run()) is clase


def test_los_modulos_de_sitio_no_vuelven_a_llevar_el_flujo() -> None:
    # Un archivo de sitio que crezca es la senal de que alguien esta copiando
    # codigo del otro otra vez.
    for modulo in ("compinche_site.py", "ready4drive_site.py"):
        ruta = RAIZ / "automation" / modulo
        arbol = ast.parse(ruta.read_text(encoding="utf-8"))
        funciones = [
            n for n in ast.walk(arbol)
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
        ]
        assert funciones == [], f"{modulo} volvio a tener funciones propias"
        assert len(ruta.read_text(encoding="utf-8").splitlines()) < 60, (
            f"{modulo} deberia ser solo constantes y reexportes"
        )


def test_la_clase_compartida_no_nombra_ningun_sitio_en_sus_cadenas() -> None:
    # Los comentarios si pueden nombrarlos (explican de donde viene esto); lo
    # que no puede es que un mensaje lleve el dominio escrito a mano, porque
    # entonces uno de los dos sitios reportaria el nombre del otro.
    arbol = ast.parse((RAIZ / "automation" / "sitio_de_bloques.py").read_text(encoding="utf-8"))
    docstrings = {
        id(n.body[0].value)
        for n in ast.walk(arbol)
        if isinstance(n, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
        and n.body
        and isinstance(n.body[0], ast.Expr)
        and isinstance(n.body[0].value, ast.Constant)
        and isinstance(n.body[0].value.value, str)
    }
    culpables = []
    for nodo in ast.walk(arbol):
        if not isinstance(nodo, ast.Constant) or not isinstance(nodo.value, str):
            continue
        if id(nodo) in docstrings:
            continue
        texto = nodo.value.lower()
        if "compinche.io" in texto or "ready4drive.com" in texto:
            culpables.append((nodo.lineno, nodo.value[:60]))
    assert culpables == [], f"cadenas con el dominio escrito a mano: {culpables}"
