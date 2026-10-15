"""Optimizaciones de la revision de fotos (2026-10-14).

Tres problemas medidos en la auditoria, en la pantalla que puede dejar la app en
"No responde" con 180 tarjetas:

1. Buscar la tarjeta de cada miniatura recorria winfo_children() entero, una vez
   por miniatura: 180 x 180 = 32.400 recorridos y otras tantas llamadas a Tcl.
2. Marcar o desmarcar las casillas destruia y recreaba las 180 tarjetas
   (~1.260 widgets) solo para cambiar unos booleanos.
3. _active_bucket() hace un RPC a Supabase y se llamaba DENTRO de los bucles:
   aprobar 180 fotos eran 360 peticiones de mas.
"""

from __future__ import annotations

from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
PANEL = RAIZ / "ui" / "main_app" / "photo_review_panel.py"
SERVICIO = RAIZ / "services" / "photo_review_service.py"


def _cuerpo(texto: str, firma: str) -> str:
    """Cuerpo del metodo SIN comentarios.

    Los comentarios explican los fallos antiguos y mencionan justo lo que estas
    pruebas prohiben; mirar solo codigo evita falsos positivos.
    """

    cuerpo = texto.split(firma)[1].split("\n    def ")[0]
    return "\n".join(
        linea for linea in cuerpo.splitlines() if not linea.strip().startswith("#")
    )


def test_buscar_la_tarjeta_es_o1() -> None:
    cuerpo = _cuerpo(PANEL.read_text(encoding="utf-8"), "def _find_candidate_card(")

    assert "_cards_by_id" in cuerpo
    assert "winfo_children()" not in cuerpo, (
        "volvio el recorrido lineal: con 180 tarjetas son 32.400 iteraciones"
    )


def test_el_indice_se_limpia_en_cada_render() -> None:
    """Si no se limpia, apunta a widgets ya destruidos."""

    cuerpo = _cuerpo(PANEL.read_text(encoding="utf-8"), "def _render_candidates(")

    assert "_cards_by_id.clear()" in cuerpo
    assert "_selection_vars.clear()" in cuerpo
    assert "_cards_by_id[candidate.id]" in cuerpo


def test_marcar_y_desmarcar_no_reconstruye_las_tarjetas() -> None:
    texto = PANEL.read_text(encoding="utf-8")

    for firma in ("def _select_visible_pending(", "def _clear_selection("):
        cuerpo = _cuerpo(texto, firma)
        assert "_render_candidates(" not in cuerpo, (
            f"{firma} vuelve a destruir y recrear las 180 tarjetas solo para "
            "cambiar casillas"
        )
        assert "_apply_selection_to_checkboxes()" in cuerpo


def test_aprobar_no_pide_el_bucket_dentro_del_bucle() -> None:
    cuerpo = _cuerpo(SERVICIO.read_text(encoding="utf-8"), "def approve_candidates(")
    bucle = cuerpo.split("for candidate in pending_candidates:")[1]

    assert "self._active_bucket()" not in bucle, (
        "_active_bucket() hace un RPC: dentro del bucle son 2 peticiones por foto"
    )
    assert "active_bucket" in bucle, "debe usar el valor congelado antes del bucle"


def test_aprobar_una_sola_foto_tampoco_repite_el_rpc() -> None:
    cuerpo = _cuerpo(SERVICIO.read_text(encoding="utf-8"), "def approve_candidate(")

    assert cuerpo.count("self._active_bucket()") == 1, (
        "tres RPC para una foto, y si el pool activo cambia entre llamadas se "
        "descarga de un bucket y se sube a otro"
    )


def test_el_borrado_masivo_no_pide_el_bucket_por_trozo() -> None:
    cuerpo = _cuerpo(SERVICIO.read_text(encoding="utf-8"), "def reject_candidates(")
    bucle = cuerpo.split("for chunk in self._chunks(")[1]

    assert "self._active_bucket()" not in bucle
