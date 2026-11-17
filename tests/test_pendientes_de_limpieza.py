"""El aviso de limpieza pendiente en la cabecera.

La limpieza de fotos consumidas es manual por decision del dueño. Lo que no
puede ser manual es acordarse: sin el numero a la vista, el almacenamiento
crece mientras nadie mira.

Sin DISPLAY, como el resto: en Windows las pruebas de interfaz se saltan.
"""

from __future__ import annotations

import pytest

from core.enums import PhotoStatus
from services.photo_cleanup_service import PhotoCleanupService


class _RespuestaFalsa:
    def __init__(self, count):
        self.count = count
        self.data = []


class _ConsultaFalsa:
    def __init__(self, registro):
        self._registro = registro

    def select(self, *args, **kwargs):
        self._registro["select"] = (args, kwargs)
        return self

    def eq(self, columna, valor):
        self._registro.setdefault("eq", []).append((columna, valor))
        return self

    def is_(self, columna, valor):
        self._registro.setdefault("is", []).append((columna, valor))
        return self

    @property
    def not_(self):
        self._registro["not_"] = True
        return _NegadaFalsa(self._registro, self)


class _NegadaFalsa:
    def __init__(self, registro, consulta):
        self._registro = registro
        self._consulta = consulta

    def is_(self, columna, valor):
        self._registro.setdefault("not_is", []).append((columna, valor))
        return self._consulta


class _ClienteFalso:
    def __init__(self, registro):
        self._registro = registro

    def table(self, nombre):
        self._registro["table"] = nombre
        return _ConsultaFalsa(self._registro)


class _ProveedorFalso:
    def __init__(self, count):
        self.registro: dict = {}
        self.client = _ClienteFalso(self.registro)
        self._count = count

    def execute_response(self, consulta):
        return _RespuestaFalsa(self._count)

    def execute(self, consulta):
        return []


def _repositorio(count):
    from storage.photos_repository import PhotosRepository

    proveedor = _ProveedorFalso(count)
    return PhotosRepository(client_provider=proveedor), proveedor


def test_cuenta_las_consumidas_que_siguen_ocupando() -> None:
    repo, proveedor = _repositorio(12_400)
    assert repo.contar_consumidas_pendientes_de_limpieza() == 12_400
    # Los mismos filtros que la lista que luego se limpia: consumida, con
    # archivo, y sin borrar del almacenamiento.
    assert (("status", PhotoStatus.CONSUMED.value)) in proveedor.registro["eq"]
    assert ("file_path", "null") in proveedor.registro["not_is"]
    assert ("storage_deleted_at", "null") in proveedor.registro["is"]


@pytest.mark.parametrize("devuelto, esperado", [(None, 0), (0, 0), (7, 7)])
def test_una_cuenta_vacia_es_cero_y_no_revienta(devuelto, esperado) -> None:
    repo, _ = _repositorio(devuelto)
    assert repo.contar_consumidas_pendientes_de_limpieza() == esperado


def test_el_servicio_expone_la_cuenta() -> None:
    repo, _ = _repositorio(99)
    servicio = PhotoCleanupService(photos_repository=repo)
    assert servicio.contar_pendientes_de_limpieza() == 99


# --- lo que acaba en la cabecera ---------------------------------------


def _texto(pendientes):
    from ui.main_app.window import MainAppWindow

    return MainAppWindow._texto_de_limpieza_pendiente(pendientes)


def test_con_cero_no_se_pone_nada() -> None:
    # Un aviso que esta siempre puesto deja de leerse.
    assert _texto(0) == ""


def test_un_numero_negativo_tampoco_pone_nada() -> None:
    assert _texto(-5) == ""


def test_una_cuenta_rota_no_ensucia_la_cabecera() -> None:
    assert _texto(None) == ""
    assert _texto("muchas") == ""


def test_el_numero_se_escribe_con_puntos_de_millar() -> None:
    assert _texto(12_400) == "Limpieza: 12.400 fotos"
    assert _texto(7) == "Limpieza: 7 fotos"
