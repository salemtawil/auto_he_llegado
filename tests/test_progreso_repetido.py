"""Un mensaje identico al anterior no informa de nada, y se paga tres veces.

Reescribe la linea de estado del panel, ocupa una entrada en la linea de
tiempo, y puede acabar en un update del log remoto.

Medido en una corrida real del 28/10: durante los 17 s finales se escribio 67
veces, letra por letra, el mismo diagnostico de final_result. Eran 70 de los
207 eventos de la corrida -un tercio del registro era la misma frase- y el
panel parpadeaba sin decir nada nuevo mientras el sitio validaba la selfie.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
SERVICIO = (RAIZ / "services" / "process_service.py").read_text(encoding="utf-8")


def _fuente_de(nombre: str) -> str:
    """El codigo de una funcion anidada dentro de _execute_run."""

    arbol = ast.parse(SERVICIO)
    for nodo in ast.walk(arbol):
        if isinstance(nodo, ast.FunctionDef) and nodo.name == nombre:
            return ast.unparse(nodo)
    raise AssertionError(f"no existe {nombre}")


def test_un_mensaje_repetido_no_se_vuelve_a_registrar() -> None:
    cuerpo = _fuente_de("emit")
    # La guarda: mismo phase y mismo message que la vez anterior.
    assert "phase == ultimo['phase'] and message == ultimo['message']" in cuerpo.replace('"', "'")
    # Y en ese caso NO se toca la linea de tiempo ni el log.
    repetido = cuerpo[cuerpo.index("ultimo['repeticiones'] = int") if "ultimo['repeticiones'] = int" in cuerpo else cuerpo.index('ultimo["repeticiones"] = int') :]
    repetido = repetido[: repetido.index("cerrar_racha()")]
    assert "run_stats.record" not in repetido, "un repetido no puede ocupar una entrada"
    assert "queue_log_update" not in repetido, "ni acabar en el log remoto"


def test_pero_sigue_dando_senal_de_vida() -> None:
    """Silencio total durante 17 s pareceria que se colgo."""

    cuerpo = _fuente_de("emit")
    assert "_LATIDO_SEGUNDOS" in cuerpo
    assert "sin cambios" in cuerpo
    assert "emit_progress" in cuerpo


def test_el_latido_es_de_segundos_no_de_milisegundos() -> None:
    valor = re.search(r"_LATIDO_SEGUNDOS = ([\d.]+)", SERVICIO)
    assert valor, "no existe la constante"
    segundos = float(valor.group(1))
    assert 2.0 <= segundos <= 15.0, segundos


def test_cuantas_veces_se_repitio_queda_anotado() -> None:
    """El dato no se pierde: deja de gritarse, pero sigue estando.

    Sin esto, leer un diagnostico despues no diria si un paso estuvo diez
    segundos quieto o diecisiete.
    """

    cuerpo = _fuente_de("cerrar_racha")
    assert "progreso_repetido" in cuerpo
    assert "'veces'" in cuerpo.replace('"', "'")
    assert "'segundos'" in cuerpo.replace('"', "'")


def test_la_racha_se_cierra_al_terminar_la_corrida() -> None:
    # Si no, el ultimo tramo repetido -que es justo el de final_result- se
    # quedaria sin contar.
    for ancla in ("cerrar_racha()\n            self._store_process_debug_export", "cerrar_racha()\n        self._store_process_debug_export"):
        assert ancla in SERVICIO, ancla
