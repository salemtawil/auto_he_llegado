"""Lo que el agente ve sobre su propio plazo de video.

Hasta ahora solo se enteraba cuando ya estaba bloqueado, y para entonces el
aviso ya no sirve de aviso.

Sin DISPLAY: la logica vive en funciones estaticas para poder probarla en
Windows, donde las pruebas de interfaz se saltan.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from services.access_service import AccessService, AccessSnapshot
from ui.shared.plazos import texto_de_plazo

_HOY = date(2026, 11, 17)


def _snapshot(**cambios) -> AccessSnapshot:
    base = {
        "can_use_app": True,
        "needs_weekly_video": False,
        "reason": "Acceso aprobado.",
        "week_start": _HOY,
        "profile": {},
        "latest_batch": None,
        "tiempo_restante": timedelta(days=3),
    }
    base.update(cambios)
    return AccessSnapshot(**base)


# --- el formateador compartido -----------------------------------------


@pytest.mark.parametrize(
    "plazo, esperado",
    [
        (timedelta(days=7), "7 dias"),
        (timedelta(days=1), "1 dia"),
        (timedelta(days=6, hours=23), "7 dias"),
        (timedelta(hours=5), "5 horas"),
        (timedelta(hours=1), "1 hora"),
        (timedelta(minutes=20), "menos de 1 hora"),
        (timedelta(0), "menos de 1 hora"),
    ],
)
def test_el_plazo_en_palabras(plazo, esperado) -> None:
    assert texto_de_plazo(plazo) == esperado


def test_nunca_dice_cero_mientras_quede_algo() -> None:
    # Decirle a alguien que le quedan cero cuando todavia puede trabajar es
    # el error mas caro de los dos.
    assert texto_de_plazo(timedelta(minutes=1)) != "0 horas"
    assert "0 " not in texto_de_plazo(timedelta(minutes=1))


# --- la cabecera de la app ---------------------------------------------


def _aviso(snapshot) -> str:
    from ui.main_app.window import MainAppWindow

    return MainAppWindow._texto_del_aviso_de_video(snapshot)


def test_la_cabecera_cuenta_los_dias() -> None:
    assert _aviso(_snapshot(tiempo_restante=timedelta(days=3))) == "Video: te quedan 3 dias"


def test_la_cabecera_avisa_de_las_ultimas_horas() -> None:
    assert _aviso(_snapshot(tiempo_restante=timedelta(hours=4))) == "Video: te quedan 4 horas"


def test_la_cabecera_dice_vencido() -> None:
    vencido = _snapshot(
        tiempo_restante=timedelta(days=-2), can_use_app=False, needs_weekly_video=True
    )
    assert _aviso(vencido) == "Video: VENCIDO"


def test_sin_video_se_pide_sin_contar_nada() -> None:
    sin_video = _snapshot(
        tiempo_restante=None, can_use_app=False, needs_weekly_video=True
    )
    assert _aviso(sin_video) == "Video: tienes que subir uno"


def test_a_quien_no_se_le_exige_video_no_se_le_pone_nada_en_la_cabecera() -> None:
    # Un admin o un exento no tienen por que ver un contador que no les toca.
    assert _aviso(_snapshot(tiempo_restante=None, needs_weekly_video=False)) == ""


# --- el mismo numero en los dos sitios ---------------------------------


def test_el_plazo_sale_del_snapshot_y_no_de_una_cuenta_aparte() -> None:
    """Es lo que impide que el agente y el admin lean numeros distintos.

    El mismo video tiene que dar el mismo plazo en la cabecera del agente y
    en el panel del administrador. Por eso el calculo vive en AccessService y
    viaja en el snapshot, en vez de repetirse en cada pantalla.
    """

    creado = datetime(2026, 11, 15, 12, 0, tzinfo=timezone.utc)
    ahora = datetime(2026, 11, 17, 12, 0, tzinfo=timezone.utc)
    restante = AccessService.tiempo_restante_del_video(creado.isoformat(), 7, now=ahora)
    assert restante == timedelta(days=5)
    assert _aviso(_snapshot(tiempo_restante=restante)) == "Video: te quedan 5 dias"


def test_una_fecha_ilegible_no_inventa_un_plazo() -> None:
    assert AccessService.tiempo_restante_del_video("manana", 7) is None
    assert AccessService.tiempo_restante_del_video(None, 7) is None
