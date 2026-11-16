"""El piso de version: comparar versiones y decidir si esta app sirve.

Sin DISPLAY a proposito: en Windows, que es donde se corre la suite, las
pruebas de interfaz se saltan y no verificarian nada.
"""

from __future__ import annotations

import pytest

from core.app_version import APP_VERSION, partes_de_version, version_es_suficiente
from services.access_service import AccessService


class _ClienteFalso:
    def __init__(self, filas, revienta=False):
        self._filas = filas
        self._revienta = revienta
        self.llamadas: list[tuple[str, dict]] = []

    def rpc(self, nombre, parametros):
        self.llamadas.append((nombre, parametros))
        if self._revienta:
            raise RuntimeError("la funcion no existe en este proyecto")
        return self._filas


class _ProveedorFalso:
    def __init__(self, filas, revienta=False):
        self.client = _ClienteFalso(filas, revienta)

    def execute(self, operacion):
        return list(operacion or [])


def _servicio(filas, revienta=False) -> AccessService:
    return AccessService(client_provider=_ProveedorFalso(filas, revienta))


# --- comparar versiones -------------------------------------------------


@pytest.mark.parametrize(
    "instalada, minima, esperado",
    [
        ("2026.11.16.1", "2026.11.16.1", True),
        ("2026.11.17", "2026.11.16.9", True),
        ("2027.1.1", "2026.12.31.9", True),
        ("2026.11.16", "2026.11.16.0", True),
        ("2026.11.16", "2026.11.16.1", False),
        ("2026.10.31.9", "2026.11.01", False),
    ],
)
def test_comparacion_de_versiones(instalada, minima, esperado) -> None:
    assert version_es_suficiente(instalada, minima) is esperado


@pytest.mark.parametrize("instalada", [None, "", "   ", "vieja", "2026.11.x", "2026..1"])
def test_una_version_que_no_se_entiende_nunca_alcanza(instalada) -> None:
    # Lo que no se sabe no pasa. Una app vieja no manda version, y eso es
    # justo lo que hay que rechazar.
    assert version_es_suficiente(instalada, "2026.11.16.1") is False


@pytest.mark.parametrize("minima", [None, "", "proxima", "ultima.version"])
def test_un_minimo_ilegible_no_deja_a_nadie_fuera(minima) -> None:
    # Al reves que arriba: un dedazo en la tabla de ajustes no puede cerrarle
    # la puerta a toda la empresa.
    assert version_es_suficiente("2026.11.16.1", minima) is True


def test_partes_distingue_no_se_sabe_de_cero() -> None:
    assert partes_de_version("basura") is None
    assert partes_de_version("0") == (0,)


def test_la_version_de_esta_app_se_entiende() -> None:
    # Si alguien escribe mal la constante, esta app se rechazaria a si misma.
    assert partes_de_version(APP_VERSION) is not None


# --- la consulta al servidor --------------------------------------------


def test_apagado_deja_pasar() -> None:
    resultado = _servicio([{"enabled": False, "version": "9999.01.01", "mensaje": ""}])
    comprobacion = resultado.comprobar_version_de_la_app()
    assert comprobacion.suficiente is True


def test_encendido_y_por_debajo_rechaza_con_mensaje() -> None:
    comprobacion = _servicio(
        [{"enabled": True, "version": "9999.01.01", "mensaje": ""}]
    ).comprobar_version_de_la_app()
    assert comprobacion.suficiente is False
    assert comprobacion.minima == "9999.01.01"
    assert comprobacion.mensaje, "sin mensaje el agente no sabe que hacer"


def test_el_mensaje_del_servidor_gana_al_de_la_app() -> None:
    comprobacion = _servicio(
        [{"enabled": True, "version": "9999.01.01", "mensaje": "Escribe a Salem."}]
    ).comprobar_version_de_la_app()
    assert comprobacion.mensaje == "Escribe a Salem."


def test_encendido_y_al_dia_deja_pasar() -> None:
    comprobacion = _servicio(
        [{"enabled": True, "version": APP_VERSION, "mensaje": ""}]
    ).comprobar_version_de_la_app()
    assert comprobacion.suficiente is True


def test_si_la_funcion_no_existe_todavia_deja_pasar() -> None:
    # El SQL puede no estar aplicado aun. Eso no puede dejar a nadie fuera.
    comprobacion = _servicio([], revienta=True).comprobar_version_de_la_app()
    assert comprobacion.suficiente is True


def test_sin_filas_deja_pasar() -> None:
    comprobacion = _servicio([]).comprobar_version_de_la_app()
    assert comprobacion.suficiente is True


def test_pregunta_por_la_funcion_que_instala_el_sql() -> None:
    servicio = _servicio([{"enabled": False, "version": "", "mensaje": ""}])
    servicio.comprobar_version_de_la_app()
    assert servicio._client_provider.client.llamadas == [("get_min_app_version", {})]


# --- la cabecera que manda la app ---------------------------------------


def _opciones(monkeypatch, sesion):
    import storage.supabase_client as modulo

    monkeypatch.setattr(modulo, "get_current_session", lambda: sesion)
    return modulo.SupabaseClientProvider._client_options_for_current_session()


def test_la_cabecera_de_version_viaja_sin_sesion(monkeypatch) -> None:
    # El cliente sin sesion es el que hace el login, que es donde queremos
    # que la app vieja se estrelle. Si aqui faltara la cabecera, la app NUEVA
    # tambien se quedaria fuera.
    from core.app_version import CABECERA_DE_VERSION

    opciones = _opciones(monkeypatch, None)
    assert opciones is not None
    assert opciones.headers.get(CABECERA_DE_VERSION) == APP_VERSION


def test_la_cabecera_de_version_viaja_con_sesion(monkeypatch) -> None:
    from core.app_version import CABECERA_DE_VERSION

    sesion = type("S", (), {"access_token": "token-de-prueba"})()
    opciones = _opciones(monkeypatch, sesion)
    assert opciones.headers.get(CABECERA_DE_VERSION) == APP_VERSION
    assert opciones.headers.get("Authorization") == "Bearer token-de-prueba"


def test_la_rama_con_sesion_conserva_su_manejo_de_tokens(monkeypatch) -> None:
    # Los tokens los administra la app. Si esto cambiara, el inicio de sesion
    # se comportaria distinto, y añadir una cabecera no viene a tocar eso.
    sesion = type("S", (), {"access_token": "token-de-prueba"})()
    opciones = _opciones(monkeypatch, sesion)
    assert opciones.auto_refresh_token is False
    assert opciones.persist_session is False
