"""Pruebas del buscador del panel de usuarios.

Corren sin DISPLAY a proposito: las pruebas de interfaz se saltan en Windows,
que es donde el usuario corre la suite, asi que la logica del filtro vive
fuera de la clase para poder probarla aqui.
"""

from __future__ import annotations

import pytest

from services.user_access_admin_service import UserAccessRecord, WeeklyVideoRecord
from ui.main_app.user_access_panel import filtrar_usuarios, texto_buscable


def _usuario(**cambios) -> UserAccessRecord:
    base = {
        "id": "u1",
        "email": "ana@ejemplo.com",
        "login_id": "ana",
        "display_name": "Ana Perez",
        "role": "agent",
        "approved": True,
        "disabled": False,
        "video_exempt": False,
        "weekly_video": None,
    }
    base.update(cambios)
    return UserAccessRecord(**base)


def _video(status: str) -> WeeklyVideoRecord:
    return WeeklyVideoRecord(
        id="v1",
        week_start="2026-11-10",
        original_video_name="clip.mp4",
        frames_extracted=10,
        candidates_uploaded=2,
        approved_count=1,
        rejected_count=0,
        status=status,
    )


def test_sin_filtro_devuelve_todos() -> None:
    usuarios = [_usuario(id="u1"), _usuario(id="u2")]
    assert filtrar_usuarios(usuarios, "") == usuarios
    assert filtrar_usuarios(usuarios, "   ") == usuarios


def test_no_devuelve_la_misma_lista() -> None:
    # Si devolviera la lista original, pintar podria reordenar la de verdad.
    usuarios = [_usuario()]
    assert filtrar_usuarios(usuarios, "") is not usuarios


@pytest.mark.parametrize("consulta", ["ana", "ANA", "Ana Perez", "ejemplo.com"])
def test_encuentra_por_cualquier_campo(consulta: str) -> None:
    ana = _usuario()
    otro = _usuario(id="u2", email="luis@otro.com", login_id="luis", display_name="Luis Diaz")
    assert filtrar_usuarios([ana, otro], consulta) == [ana]


@pytest.mark.parametrize("consulta", ["agent", "aprobado"])
def test_rol_y_estado_devuelven_a_todos_los_que_coinciden(consulta: str) -> None:
    # Buscar por rol o estado es filtrar un grupo, no encontrar a uno.
    ana = _usuario()
    otro = _usuario(id="u2", email="luis@otro.com", login_id="luis", display_name="Luis Diaz")
    assert filtrar_usuarios([ana, otro], consulta) == [ana, otro]


def test_varias_palabras_son_un_y_no_un_o() -> None:
    ana = _usuario(display_name="Ana Perez", role="admin")
    luis = _usuario(id="u2", email="luis@ejemplo.com", login_id="luis", display_name="Luis Perez")
    assert filtrar_usuarios([ana, luis], "perez admin") == [ana]


def test_distingue_estados() -> None:
    aprobado = _usuario(id="u1", approved=True, disabled=False)
    pendiente = _usuario(id="u2", login_id="pepe", display_name="Pepe", approved=False, disabled=False)
    inhabilitado = _usuario(id="u3", login_id="zoe", display_name="Zoe", approved=True, disabled=True)
    todos = [aprobado, pendiente, inhabilitado]
    assert filtrar_usuarios(todos, "pendiente") == [pendiente]
    assert filtrar_usuarios(todos, "deshabilitado") == [inhabilitado]


def test_busca_por_estado_del_video() -> None:
    con_video = _usuario(id="u1", weekly_video=_video("rejected"))
    sin_video = _usuario(id="u2", login_id="bea", display_name="Bea")
    assert filtrar_usuarios([con_video, sin_video], "rejected") == [con_video]
    assert filtrar_usuarios([con_video, sin_video], "sin video") == [sin_video]


def test_exento_es_buscable() -> None:
    exento = _usuario(id="u1", video_exempt=True)
    normal = _usuario(id="u2", login_id="bea", display_name="Bea")
    assert filtrar_usuarios([exento, normal], "exento") == [exento]


def test_sin_coincidencias_no_revienta() -> None:
    assert filtrar_usuarios([_usuario()], "zzzz") == []
    assert filtrar_usuarios([], "ana") == []


def test_el_texto_buscable_no_pierde_campos_vacios_por_el_camino() -> None:
    # Un usuario sin nombre ni login no puede quedar ilocalizable por correo.
    anonimo = _usuario(display_name="", login_id="")
    assert "ana@ejemplo.com" in texto_buscable(anonimo)
    assert filtrar_usuarios([anonimo], "ana@ejemplo.com") == [anonimo]
