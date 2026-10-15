"""Contrato del candado de video: exigir video debe bloquear hasta que suban uno.

Lo que el responsable del proyecto necesita que no falle nunca:
  * con "exigir video" activado, un agente NO puede usar la app;
  * en cuanto sube un video, puede, SIN que nadie lo apruebe.

Ese segundo punto importa porque la revision de fotos esta deshabilitada: si el
desbloqueo dependiera de aprobar, los agentes quedarian bloqueados para siempre.

El enlace fragil que estas pruebas vigilan: el estado con el que NACE un lote de
video (video_contribution_service) tiene que estar en la lista de estados que
dan acceso (AccessService.ACTIVE_BATCH_STATUSES). Hoy ambos lados se prueban por
separado con el mismo literal, asi que cambiar UNO solo dejaria las dos suites en
verde y el candado roto en silencio.
"""

from __future__ import annotations

import ast
from pathlib import Path

from services.access_service import AccessService

RAIZ = Path(__file__).resolve().parents[1]


def _estado_inicial_del_lote() -> str:
    """Lee el literal con el que video_contribution_service crea el lote."""

    ruta = RAIZ / "services" / "video_contribution_service.py"
    arbol = ast.parse(ruta.read_text(encoding="utf-8"))
    for nodo in ast.walk(arbol):
        if not isinstance(nodo, ast.Call):
            continue
        for kw in nodo.keywords:
            if kw.arg == "status" and isinstance(kw.value, ast.Constant):
                if isinstance(kw.value.value, str):
                    return kw.value.value
    raise AssertionError("no se encontro el status con el que nace el lote de video")


def test_un_video_recien_subido_da_acceso_sin_aprobarlo() -> None:
    """El enlace entre los dos modulos. Es la prueba clave de este archivo."""

    estado_inicial = _estado_inicial_del_lote()

    assert estado_inicial in AccessService.ACTIVE_BATCH_STATUSES, (
        f"Un video recien subido nace como '{estado_inicial}', que NO esta en "
        f"ACTIVE_BATCH_STATUSES ({sorted(AccessService.ACTIVE_BATCH_STATUSES)}). "
        "Con 'exigir video' activado, los agentes quedarian bloqueados aunque "
        "suban el video."
    )


def test_el_acceso_no_depende_de_aprobar() -> None:
    """Ningun estado de 'aprobado' puede ser necesario para desbloquear.

    La revision de fotos esta deshabilitada: si el acceso exigiera aprobacion,
    nadie podria trabajar.
    """

    activos = AccessService.ACTIVE_BATCH_STATUSES

    # Hay al menos un estado "sin revisar" que ya da acceso.
    sin_revisar = {"processing", "pending_review"} & activos
    assert sin_revisar, (
        "ningun estado previo a la revision da acceso: el candado dependeria "
        "de que un administrador apruebe, y la revision esta deshabilitada"
    )


def test_un_video_rechazado_no_da_acceso() -> None:
    """Lo unico que debe quitar el acceso tras subir es un rechazo explicito."""

    assert "rejected" not in AccessService.ACTIVE_BATCH_STATUSES


def test_la_politica_falla_cerrada_si_supabase_no_responde() -> None:
    """Sin poder consultar la politica se asume que el video SI es obligatorio.

    Es la opcion segura, pero conviene tenerlo documentado: un problema de red
    con Supabase bloquea a los agentes en vez de dejarlos pasar.
    """

    texto = (RAIZ / "services" / "access_service.py").read_text(encoding="utf-8")
    cuerpo = texto.split("def get_video_requirement_policy(")[1].split("\n    def ")[0]
    respaldo = cuerpo.split("except Exception:")[1]
    assert "enabled=True" in respaldo, (
        "el respaldo debe exigir video; si pasa a False, una caida de Supabase "
        "abriria la app a todos los agentes"
    )
