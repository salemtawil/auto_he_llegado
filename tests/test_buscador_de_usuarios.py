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


# --- cuanto le queda al video ------------------------------------------

from datetime import datetime, timedelta, timezone  # noqa: E402

from services.access_service import VideoRequirementPolicy  # noqa: E402
from ui.main_app.user_access_panel import (  # noqa: E402
    COLOR_AL_DIA,
    COLOR_NEUTRO,
    COLOR_POR_VENCER,
    COLOR_VENCIDO,
    texto_de_vencimiento,
)

_AHORA = datetime(2026, 11, 16, 12, 0, tzinfo=timezone.utc)


def _video_hace(dias: float, *, status: str = "pending_review", duracion=None):
    creado = _AHORA - timedelta(days=dias)
    return WeeklyVideoRecord(
        id="v1",
        week_start="2026-11-10",
        original_video_name="clip.mp4",
        frames_extracted=10,
        candidates_uploaded=2,
        approved_count=1,
        rejected_count=0,
        status=status,
        created_at=creado.isoformat(),
        video_duration_seconds=duracion,
    )


_POLITICA = VideoRequirementPolicy(enabled=True, days=7)


def test_video_recien_subido_son_siete_dias() -> None:
    texto, color = texto_de_vencimiento(_usuario(weekly_video=_video_hace(0)), _POLITICA, _AHORA)
    assert texto == "le quedan 7 dias"
    assert color == COLOR_AL_DIA


def test_a_punto_de_vencer_avisa_en_ambar() -> None:
    texto, color = texto_de_vencimiento(_usuario(weekly_video=_video_hace(5)), _POLITICA, _AHORA)
    assert texto == "le quedan 2 dias"
    assert color == COLOR_POR_VENCER


def test_ultimas_horas_no_se_redondean_a_cero() -> None:
    # Decir "0 dias" a quien todavia puede trabajar es peor que decir "pocas
    # horas": el agente deja de intentarlo creyendo que ya no puede.
    texto, color = texto_de_vencimiento(_usuario(weekly_video=_video_hace(6.8)), _POLITICA, _AHORA)
    assert texto == "le quedan 4 horas"
    assert color == COLOR_POR_VENCER


def test_ya_vencido() -> None:
    texto, color = texto_de_vencimiento(_usuario(weekly_video=_video_hace(9)), _POLITICA, _AHORA)
    assert texto == "vencido hace 2 dias"
    assert color == COLOR_VENCIDO


def test_sin_video() -> None:
    texto, color = texto_de_vencimiento(_usuario(), _POLITICA, _AHORA)
    assert color == COLOR_VENCIDO
    assert "sin video" in texto


def test_video_rechazado() -> None:
    usuario = _usuario(weekly_video=_video_hace(1, status="rejected"))
    texto, color = texto_de_vencimiento(usuario, _POLITICA, _AHORA)
    assert color == COLOR_VENCIDO
    assert "rechazado" in texto


def test_un_video_largo_vale_mas_dias() -> None:
    politica = VideoRequirementPolicy(
        enabled=True, days=7, duration_based=True, long_video_days=14,
        long_video_min_duration_seconds=25.0,
    )
    corto, _ = texto_de_vencimiento(_usuario(weekly_video=_video_hace(1, duracion=10.0)), politica, _AHORA)
    largo, _ = texto_de_vencimiento(_usuario(weekly_video=_video_hace(1, duracion=40.0)), politica, _AHORA)
    assert corto == "le quedan 6 dias"
    assert largo == "le quedan 13 dias"


@pytest.mark.parametrize(
    "cambios",
    [
        {"disabled": True},
        {"video_exempt": True},
        {"role": "admin"},
    ],
)
def test_a_quien_no_se_le_exige_video_no_se_le_pone_cuenta_atras(cambios) -> None:
    usuario = _usuario(weekly_video=_video_hace(90), **cambios)
    texto, color = texto_de_vencimiento(usuario, _POLITICA, _AHORA)
    assert color == COLOR_NEUTRO
    assert texto.startswith("sin vencimiento")


def test_con_la_politica_apagada_no_hay_cuenta_atras() -> None:
    apagada = VideoRequirementPolicy(enabled=False, days=7)
    _, color = texto_de_vencimiento(_usuario(weekly_video=_video_hace(90)), apagada, _AHORA)
    assert color == COLOR_NEUTRO


def test_sin_fecha_del_video_no_se_inventa_un_vencimiento() -> None:
    sin_fecha = _video_hace(1)
    sin_fecha = WeeklyVideoRecord(**{**sin_fecha.__dict__, "created_at": None})
    _, color = texto_de_vencimiento(_usuario(weekly_video=sin_fecha), _POLITICA, _AHORA)
    assert color == COLOR_NEUTRO


def test_el_buscador_encuentra_a_los_vencidos() -> None:
    vencido = _usuario(id="u1")
    al_dia = _usuario(id="u2", login_id="bea", display_name="Bea")
    extra = {"u1": "vencido hace 2 dias", "u2": "le quedan 6 dias"}
    assert filtrar_usuarios([vencido, al_dia], "vencido", extra) == [vencido]


def test_el_texto_extra_no_estorba_cuando_no_hay() -> None:
    usuario = _usuario()
    assert filtrar_usuarios([usuario], "ana", {}) == [usuario]
    assert filtrar_usuarios([usuario], "ana", None) == [usuario]


def test_el_dia_que_lo_sube_le_quedan_los_dias_enteros() -> None:
    # Con suelo, un video subido hace un segundo decia "6 dias" de 7. Parece
    # una cuenta rota y es el caso que mas se mira.
    recien = _video_hace(0.0001)
    texto, color = texto_de_vencimiento(_usuario(weekly_video=recien), _POLITICA, _AHORA)
    assert texto == "le quedan 7 dias"
    assert color == COLOR_AL_DIA


def test_un_dia_justo_se_dice_en_dias() -> None:
    texto, _ = texto_de_vencimiento(
        _usuario(weekly_video=_video_hace(6.0)), _POLITICA, _AHORA
    )
    assert texto == "le quedan 1 dia"


def test_por_debajo_de_un_dia_se_cuenta_en_horas() -> None:
    texto, _ = texto_de_vencimiento(
        _usuario(weekly_video=_video_hace(6.2)), _POLITICA, _AHORA
    )
    assert texto == "le quedan 19 horas"
