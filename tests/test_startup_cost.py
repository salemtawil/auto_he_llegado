"""Coste de arranque: que no vuelva a colarse peso antes de la pantalla de login.

Contexto (optimizacion 2026-10-13, app para equipos modestos):

* `app_main.py` importaba `MainAppWindow` en la primera linea, asi que todo su
  arbol de imports se pagaba antes de mostrar el login, aunque la ventana no se
  instancia hasta despues de autenticarse.
* `storage/supabase_client.py` importaba `supabase` a nivel de modulo (~330 ms),
  y lo arrastraban diez servicios distintos.
* Cada `ProcessSlotPanel` construia un `ExtensionStatusPanel` de 126 widgets que
  nunca se colocaba en pantalla con grid/pack y que nadie leia.

Medido en el contenedor: la ruta del login paso de ~456 ms a ~228 ms de imports,
y cada slot de 293 a 167 widgets.
"""

from __future__ import annotations

import ast
import os
import subprocess
import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]


def _nombres_importados_en_el_nivel_superior(ruta: Path) -> set[str]:
    arbol = ast.parse(ruta.read_text(encoding="utf-8"))
    nombres: set[str] = set()
    for nodo in arbol.body:  # solo nivel superior: los de dentro de funciones no cuentan
        if isinstance(nodo, ast.Import):
            nombres.update(alias.name.split(".")[0] for alias in nodo.names)
        elif isinstance(nodo, ast.ImportFrom) and nodo.module:
            nombres.add(nodo.module.split(".")[0])
    return nombres


def test_app_main_no_importa_la_ventana_principal_antes_del_login() -> None:
    nombres = _nombres_importados_en_el_nivel_superior(RAIZ / "app_main.py")

    assert "ui" in nombres, "el login y el tema si deben importarse arriba"
    texto = (RAIZ / "app_main.py").read_text(encoding="utf-8")
    cabecera = texto.split("def main(")[0]
    assert "main_app.window" not in cabecera, (
        "MainAppWindow debe importarse dentro de main(), despues del login"
    )
    assert "main_app.window" in texto.split("def main(")[1], (
        "y seguir importandose cuando de verdad hace falta"
    )


def test_supabase_no_se_importa_al_cargar_el_cliente() -> None:
    """El import debe vivir dentro de las funciones que lo usan."""

    ruta = RAIZ / "storage" / "supabase_client.py"
    arbol = ast.parse(ruta.read_text(encoding="utf-8"))
    for nodo in arbol.body:
        if isinstance(nodo, ast.ImportFrom) and (nodo.module or "").startswith("supabase"):
            pytest.fail("supabase no debe importarse en el nivel superior del modulo")
        # El bloque TYPE_CHECKING si puede tenerlo: no se evalua en ejecucion.


def test_importar_el_cliente_no_arrastra_supabase() -> None:
    """Prueba de verdad: importar el modulo no debe cargar supabase en sys.modules."""

    codigo = (
        "import sys;"
        "import storage.supabase_client;"
        "print('supabase' in sys.modules)"
    )
    resultado = subprocess.run(
        [sys.executable, "-c", codigo],
        capture_output=True,
        text=True,
        cwd=str(RAIZ),
        env={**os.environ, "PYTHONPATH": str(RAIZ)},
    )
    assert resultado.returncode == 0, resultado.stderr
    assert resultado.stdout.strip() == "False", (
        "importar SupabaseClientProvider volvio a arrastrar supabase (~330 ms)"
    )


def test_la_ruta_del_login_no_arrastra_la_ventana_principal() -> None:
    codigo = (
        "import sys;"
        "import ui.theme, ui.access.login_window;"
        "print('ui.main_app.window' in sys.modules)"
    )
    resultado = subprocess.run(
        [sys.executable, "-c", codigo],
        capture_output=True,
        text=True,
        cwd=str(RAIZ),
        env={**os.environ, "PYTHONPATH": str(RAIZ)},
    )
    assert resultado.returncode == 0, resultado.stderr
    assert resultado.stdout.strip() == "False"


def test_el_panel_de_diagnostico_muerto_no_vuelve_a_los_slots() -> None:
    """El diagnostico que se ve es el de admin_dialogs, no uno por slot."""

    slot = (RAIZ / "ui" / "main_app" / "process_slot_panel.py").read_text(encoding="utf-8")
    assert "ExtensionStatusPanel(" not in slot, (
        "volvio a construirse un panel de 126 widgets que nunca se muestra"
    )

    admin = (RAIZ / "ui" / "main_app" / "admin_dialogs.py").read_text(encoding="utf-8")
    assert "ExtensionStatusPanel(" in admin and "extension_panel.grid(" in admin, (
        "el panel de admin si debe existir y mostrarse"
    )


def test_no_hay_bucle_de_refresco_de_extension_de_1hz() -> None:
    """refresh_extension_status se reprogramaba sola cada segundo, para siempre."""

    ventana = (RAIZ / "ui" / "main_app" / "window.py").read_text(encoding="utf-8")
    cuerpo = ventana.split("def refresh_extension_status(")[1].split("\n    def ")[0]
    assert "_schedule_extension_status_refresh" not in ventana
    assert "_safe_after" not in cuerpo, (
        "refresh_extension_status no debe reprogramarse a si misma"
    )
