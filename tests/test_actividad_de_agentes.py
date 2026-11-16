"""La pantalla de actividad: quien corre ahora y quien trabajo cuanto.

Sin DISPLAY: en Windows las pruebas de interfaz se saltan, asi que lo que
decide que se ve vive en funciones puras y se prueba aqui.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from services.activity_service import (
    ActividadDeAgente,
    ActivityService,
    ResumenDeActividad,
    texto_de_antiguedad,
)
from ui.main_app.activity_panel import linea_de_agente, resumen_en_una_linea

_AHORA = datetime(2026, 11, 16, 12, 0, tzinfo=timezone.utc)


def _agente(**cambios) -> ActividadDeAgente:
    base = {
        "user_id": "u1",
        "email": "ana@ejemplo.com",
        "display_name": "Ana Perez",
        "login_id": "ana",
        "role": "member",
        "disabled": False,
        "corriendo": False,
        "corriendo_desde": None,
        "ultima_corrida": _AHORA - timedelta(hours=3),
        "ultimo_sitio": "paripe.io",
        "ultimo_estado": "ok",
        "nombre_escrito": "Ana Perez",
        "corridas_hoy": 2,
        "corridas_periodo": 9,
    }
    base.update(cambios)
    return ActividadDeAgente(**base)


class _ClienteFalso:
    def __init__(self, actividad, sin_identificar=0, revienta_contador=False):
        self._actividad = actividad
        self._sin_identificar = sin_identificar
        self._revienta_contador = revienta_contador
        self.llamadas: list[tuple[str, dict]] = []

    def rpc(self, nombre, parametros):
        self.llamadas.append((nombre, parametros))
        if nombre == "corridas_sin_identificar":
            if self._revienta_contador:
                raise RuntimeError("esa funcion no existe todavia")
            return [{"corridas_sin_identificar": self._sin_identificar}]
        return self._actividad


class _ProveedorFalso:
    def __init__(self, *args, **kwargs):
        self.client = _ClienteFalso(*args, **kwargs)

    def execute(self, operacion):
        return list(operacion or [])


# --- antiguedad ---------------------------------------------------------


@pytest.mark.parametrize(
    "transcurrido, esperado",
    [
        (timedelta(seconds=30), "hace un momento"),
        (timedelta(minutes=5), "hace 5 min"),
        (timedelta(hours=1), "hace 1 hora"),
        (timedelta(hours=5), "hace 5 horas"),
        (timedelta(days=1), "hace 1 dia"),
        (timedelta(days=9), "hace 9 dias"),
    ],
)
def test_antiguedad_en_palabras(transcurrido, esperado) -> None:
    assert texto_de_antiguedad(_AHORA - transcurrido, _AHORA) == esperado


def test_sin_fecha_no_se_inventa_antiguedad() -> None:
    assert texto_de_antiguedad(None, _AHORA) == ""


def test_una_fecha_futura_no_dice_hace_menos_cinco_minutos() -> None:
    # El reloj del agente puede ir adelantado respecto al servidor.
    assert texto_de_antiguedad(_AHORA + timedelta(minutes=5), _AHORA) == "ahora mismo"


# --- quien es quien -----------------------------------------------------


def test_el_identificador_lleva_nombre_y_correo() -> None:
    assert _agente().identificador == "Ana Perez | ana@ejemplo.com"


def test_sin_nombre_se_cae_al_correo() -> None:
    assert _agente(display_name="").identificador == "ana@ejemplo.com"


def test_sin_nada_queda_el_id() -> None:
    vacio = _agente(display_name="", email="", login_id="")
    assert vacio.identificador == "u1"


@pytest.mark.parametrize("escrito", ["Ana Perez", "ana", "ANA", "ana@ejemplo.com", ""])
def test_firmar_con_lo_suyo_no_se_marca(escrito) -> None:
    assert _agente(nombre_escrito=escrito).firma_distinta is False


def test_firmar_con_otro_nombre_se_marca() -> None:
    # Es lo unico que antes no se podia ni ver: el nombre escrito era el unico
    # dato que habia, asi que no habia contra que compararlo.
    assert _agente(nombre_escrito="Luis").firma_distinta is True


# --- los tres grupos ----------------------------------------------------


def _resumen(agentes, sin_identificar=0) -> ResumenDeActividad:
    return ResumenDeActividad(agentes=agentes, sin_identificar=sin_identificar, dias=7)


def test_los_grupos_no_se_pisan() -> None:
    corriendo = _agente(user_id="u1", corriendo=True, corridas_periodo=3)
    trabajo = _agente(user_id="u2", corridas_periodo=4)
    ausente = _agente(user_id="u3", corridas_hoy=0, corridas_periodo=0)
    resumen = _resumen([corriendo, trabajo, ausente])
    assert [a.user_id for a in resumen.corriendo_ahora] == ["u1"]
    assert [a.user_id for a in resumen.trabajaron] == ["u1", "u2"]
    assert [a.user_id for a in resumen.sin_aparecer] == ["u3"]


def test_un_deshabilitado_no_cuenta_como_ausente() -> None:
    # No apareció porque no puede entrar. Listarlo como ausente seria ruido
    # todas las semanas.
    fuera = _agente(user_id="u9", corridas_hoy=0, corridas_periodo=0, disabled=True)
    assert _resumen([fuera]).sin_aparecer == []


# --- lo que se lee en pantalla ------------------------------------------


def test_la_linea_del_agente_lleva_lo_importante() -> None:
    texto = linea_de_agente(_agente(), _AHORA)
    assert texto == "hoy 2 | periodo 9 | ultima hace 3 horas | paripe.io | ok"


def test_la_linea_aguanta_campos_vacios() -> None:
    texto = linea_de_agente(
        _agente(ultima_corrida=None, ultimo_sitio="", ultimo_estado=""), _AHORA
    )
    assert texto == "hoy 2 | periodo 9"


def test_el_resumen_avisa_de_las_corridas_sin_dueño() -> None:
    assert "Sin identificar 12" in resumen_en_una_linea(_resumen([_agente()], 12))


def test_el_resumen_no_menciona_lo_que_no_hay() -> None:
    assert "Sin identificar" not in resumen_en_una_linea(_resumen([_agente()], 0))


# --- el servicio --------------------------------------------------------


def test_el_servicio_pide_el_periodo_que_se_le_dice() -> None:
    proveedor = _ProveedorFalso([], 0)
    servicio = ActivityService(client_provider=proveedor)
    servicio.resumen(dias=30, minutos_en_curso=45)
    assert ("actividad_de_agentes", {"p_dias": 30, "p_minutos_en_curso": 45}) in proveedor.client.llamadas
    assert ("corridas_sin_identificar", {"p_dias": 30}) in proveedor.client.llamadas


def test_el_servicio_traduce_las_filas() -> None:
    fila = {
        "user_id": "u1",
        "email": "ana@ejemplo.com",
        "display_name": "Ana",
        "login_id": "ana",
        "role": "member",
        "disabled": False,
        "corriendo": True,
        "corriendo_desde": "2026-11-16T11:30:00Z",
        "ultima_corrida": "2026-11-16T11:30:00+00:00",
        "ultimo_sitio": "paripe.io",
        "ultimo_estado": "ok",
        "nombre_escrito": "Ana",
        "corridas_hoy": "3",
        "corridas_periodo": 11,
    }
    resumen = ActivityService(client_provider=_ProveedorFalso([fila], 0)).resumen()
    agente = resumen.agentes[0]
    assert agente.corriendo is True
    assert agente.corridas_hoy == 3
    assert agente.corriendo_desde == datetime(2026, 11, 16, 11, 30, tzinfo=timezone.utc)


def test_si_falta_el_contador_la_pantalla_sigue_en_pie() -> None:
    # Un contador que no existe todavia no puede tumbar la pantalla entera.
    proveedor = _ProveedorFalso([], 0, revienta_contador=True)
    resumen = ActivityService(client_provider=proveedor).resumen()
    assert resumen.sin_identificar == 0
