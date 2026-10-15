"""Cierre de la reserva de fotos en todas las rutas de salida.

Regresiones cubiertas:

- El `raise` desnudo del `except <Site>FlowError` en `_complete_selfie_until_block`
  salia sin liberar nada, y el llamador tampoco podia: su `reserved_photo` solo se
  liga al retorno exitoso. La fila quedaba RESERVED para siempre y el temporal en
  disco. El pool se drenaba con cada corrida fallida.
- `_discard_background_photo` retornaba en seco si el `ready_event` todavia no
  estaba puesto — justo el caso de las salidas rapidas (no_block a ~1,5 s) — y el
  worker reservaba la foto despues, sin que nadie volviera a verla.
- La limpieza podia ejecutarse dos veces sobre la misma foto, y una excepcion en
  ella sustituia al error original sin dejar diagnostico.
"""

from __future__ import annotations

import threading
from types import SimpleNamespace

import pytest

from automation.base_site import BaseSite


class _PhotoService:
    def __init__(self, *, fail: str | None = None) -> None:
        self.consumed: list[str] = []
        self.released: list[str] = []
        self.deleted: list[str] = []
        self._fail = fail

    def consume_photo(self, photo_id):
        if self._fail == "consume":
            raise RuntimeError("supabase caido")
        self.consumed.append(photo_id)

    def release_photo(self, photo_id):
        if self._fail == "release":
            raise RuntimeError("supabase caido")
        self.released.append(photo_id)

    def delete_local_copy(self, local_path):
        if self._fail == "delete":
            raise OSError("fichero bloqueado")
        self.deleted.append(local_path)


class _Site(BaseSite):
    def execute(self, *args, **kwargs):  # pragma: no cover - abstracto
        raise NotImplementedError

    def __init__(self, photo_service) -> None:
        self._photo_service = photo_service
        self.events: list[tuple[str, dict]] = []
        self.progress: list[tuple[str, str]] = []
        self._reset_photo_cleanup_registry()

    def _record_timeline_event(self, event, **fields):
        self.events.append((event, fields))

    def _record_run_stat(self, event, **fields):
        self.events.append((event, fields))

    def emit_progress(self, callback, *, phase, message):
        self.progress.append((phase, message))


def _photo(photo_id="p1"):
    return SimpleNamespace(photo_id=photo_id, local_path=f"/tmp/{photo_id}.jpg")


# ---------------------------------------------------------------------------
# Las tres politicas
# ---------------------------------------------------------------------------


def test_error_antes_de_subir_libera_la_foto_al_pool() -> None:
    service = _PhotoService()
    site = _Site(service)

    site._cleanup_reserved_photo(_photo(), uploaded=False)

    assert service.released == ["p1"], "sin subir: la foto vuelve al pool"
    assert service.consumed == []
    assert service.deleted == ["/tmp/p1.jpg"]


def test_error_despues_de_subir_consume_la_foto() -> None:
    service = _PhotoService()
    site = _Site(service)

    site._cleanup_reserved_photo(_photo(), uploaded=True)

    assert service.consumed == ["p1"], "pudo llegar al sitio: no se reutiliza"
    assert service.released == []
    assert service.deleted == ["/tmp/p1.jpg"]


def test_la_selfie_del_titular_no_pasa_por_el_pool() -> None:
    service = _PhotoService()
    site = _Site(service)

    site._cleanup_reserved_photo(None, uploaded=False)
    site._cleanup_reserved_photo(None, uploaded=True)

    assert service.released == [] and service.consumed == [] and service.deleted == []


# ---------------------------------------------------------------------------
# Exactamente una vez
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("uploaded", [False, True])
def test_la_limpieza_ocurre_una_sola_vez_por_foto(uploaded: bool) -> None:
    service = _PhotoService()
    site = _Site(service)
    photo = _photo()

    site._cleanup_reserved_photo(photo, uploaded=uploaded)
    site._cleanup_reserved_photo(photo, uploaded=uploaded)
    site._cleanup_reserved_photo(photo, uploaded=not uploaded)

    total = len(service.consumed) + len(service.released)
    assert total == 1, f"la foto se cerro {total} veces"
    assert service.deleted == ["/tmp/p1.jpg"]


def test_el_registro_se_reinicia_en_cada_corrida() -> None:
    service = _PhotoService()
    site = _Site(service)
    photo = _photo()

    site._cleanup_reserved_photo(photo, uploaded=True)
    site._reset_photo_cleanup_registry()
    site._cleanup_reserved_photo(photo, uploaded=True)

    assert service.consumed == ["p1", "p1"], "cada corrida cierra su propia reserva"


# ---------------------------------------------------------------------------
# Un fallo al limpiar no puede sustituir al error original
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("fallo", ["consume", "release", "delete"])
def test_un_fallo_al_limpiar_no_lanza_y_deja_diagnostico(fallo: str) -> None:
    service = _PhotoService(fail=fallo)
    site = _Site(service)

    site._cleanup_reserved_photo(_photo(), uploaded=(fallo == "consume"))

    nombres = [nombre for nombre, _campos in site.events]
    assert "photo_cleanup_failed" in nombres, "sin diagnostico del fallo de limpieza"
    campos = next(c for n, c in site.events if n == "photo_cleanup_failed")
    assert campos["photo_id"] == "p1"
    assert campos["action"] == fallo if fallo != "delete" else campos["action"] == "delete_local_copy"


def test_un_fallo_al_finalizar_no_impide_borrar_la_copia_local() -> None:
    service = _PhotoService(fail="consume")
    site = _Site(service)

    site._cleanup_reserved_photo(_photo(), uploaded=True)

    assert service.deleted == ["/tmp/p1.jpg"], "el temporal debe borrarse igualmente"


# ---------------------------------------------------------------------------
# Carrera: salida rapida con la reserva aun en vuelo
# ---------------------------------------------------------------------------


def test_salida_rapida_espera_al_worker_y_libera_la_reserva() -> None:
    """EL CASO DE LA CARRERA: el flujo abandona antes de que reserve_photo termine."""

    service = _PhotoService()
    site = _Site(service)
    site.BACKGROUND_PHOTO_SETTLE_TIMEOUT_S = 5.0

    preparation = SimpleNamespace(
        ready_event=threading.Event(), reserved_photo=None, consumed=False
    )

    def worker():
        preparation.reserved_photo = _photo("tarde")
        preparation.ready_event.set()

    hilo = threading.Thread(target=worker)
    hilo.start()

    reservada = site._settle_background_photo(preparation)
    hilo.join(timeout=5)

    assert reservada is not None, "la espera acotada debe ver la reserva tardia"
    assert reservada.photo_id == "tarde"

    site._cleanup_reserved_photo(reservada, uploaded=False)
    assert service.released == ["tarde"], "la reserva tardia vuelve al pool"


def test_el_settle_no_bloquea_para_siempre_si_el_worker_nunca_responde() -> None:
    import time

    service = _PhotoService()
    site = _Site(service)
    site.BACKGROUND_PHOTO_SETTLE_TIMEOUT_S = 0.2

    preparation = SimpleNamespace(
        ready_event=threading.Event(), reserved_photo=None, consumed=False
    )

    inicio = time.monotonic()
    assert site._settle_background_photo(preparation) is None
    assert time.monotonic() - inicio < 3.0


def test_una_preparacion_ya_consumida_no_se_vuelve_a_tocar() -> None:
    service = _PhotoService()
    site = _Site(service)
    preparation = SimpleNamespace(
        ready_event=threading.Event(), reserved_photo=_photo(), consumed=True
    )
    preparation.ready_event.set()

    assert site._settle_background_photo(preparation) is None
    assert service.released == [] and service.consumed == []


def test_finalizacion_normal_consume_una_vez() -> None:
    """Camino feliz: el bucle finaliza la foto y el `finally` no la cierra otra vez."""

    service = _PhotoService()
    site = _Site(service)
    photo = _photo()

    site._cleanup_reserved_photo(photo, uploaded=True)   # bucle
    site._cleanup_reserved_photo(photo, uploaded=True)   # finally del pipeline

    assert service.consumed == ["p1"]
    assert service.deleted == ["/tmp/p1.jpg"]
