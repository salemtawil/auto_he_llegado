"""Fuga de navegadores y drivers entre corridas.

Sintoma reportado: tras varias corridas la app consume cada vez mas RAM y
quedan procesos colgados; hay que cerrar y reabrir la app.

Causa, en tres piezas que se refuerzan:

1. ``_close_internal`` marcaba ``_closed = True`` ANTES de comprobar
   ``keep_open``, asi que salia sin cerrar nada y ademas dejaba la sesion en un
   estado en el que un ``shutdown(force=True)`` posterior era un no-op.
2. ``_register_session`` desregistraba la sesion en un ``finally``, cerrada o
   no, de modo que ``shutdown_all()`` ya no la encontraba al salir de la app.
3. La API sync de Playwright esta atada al hilo que la arranco. Cuando el hilo
   de la corrida muere, ``page/context/browser/playwright`` lanzan
   "cannot switch to a different thread" y la sesion es irrecuperable por esa
   via: solo queda matar el driver por PID.

Estas pruebas usan dobles y no lanzan ningun navegador.
"""

from __future__ import annotations

import threading

import pytest

from automation import browser_manager as bm
from automation.browser_manager import BrowserManager, BrowserSession

# El fixture autouse sustituye bm.kill_process_tree por un doble para no matar
# procesos de verdad. Las pruebas de la rama de Windows necesitan la real.
_KILL_REAL = bm.kill_process_tree


class FakeResource:
    def __init__(self) -> None:
        self.closed = False
        self.stopped = False

    def close(self) -> None:
        self.closed = True

    def stop(self) -> None:
        self.stopped = True


class ForeignThreadResource(FakeResource):
    """Reproduce el error real de Playwright al cruzar de hilo."""

    def close(self) -> None:
        raise RuntimeError("cannot switch to a different thread (which happens to have exited)")

    def stop(self) -> None:
        raise RuntimeError("cannot switch to a different thread (which happens to have exited)")


def build_session(*, keep_open: bool, driver_pid: int | None = 4242, resource=FakeResource):
    playwright, browser, context, page = (resource() for _ in range(4))
    session = BrowserSession(
        playwright=playwright,
        browser=browser,
        context=context,
        page=page,
        keep_open=keep_open,
        _driver_pid=driver_pid,
    )
    return session, playwright, browser, context, page


@pytest.fixture(autouse=True)
def _clean_registry(monkeypatch):
    """Cada prueba parte de un registro limpio y sin matar procesos de verdad."""

    monkeypatch.setattr(BrowserManager, "_sessions", [])
    killed: list[int | None] = []
    monkeypatch.setattr(bm, "kill_process_tree", lambda pid: (killed.append(pid), True)[1])
    # El vigilante no debe arrancar hilos durante las pruebas.
    monkeypatch.setattr(BrowserManager, "_ensure_reaper_started", classmethod(lambda cls: None))
    yield killed
    BrowserManager._sessions = []


# ---------------------------------------------------------------------------
# Regresion principal
# ---------------------------------------------------------------------------


def test_keep_open_no_marca_la_sesion_como_cerrada() -> None:
    """Antes se marcaba cerrada sin cerrar nada, y el forzado quedaba muerto."""

    session, playwright, browser, context, page = build_session(keep_open=True)

    session.close()

    assert session.is_closed is False
    assert (page.closed, context.closed, browser.closed, playwright.stopped) == (
        False,
        False,
        False,
        False,
    )


def test_shutdown_forzado_funciona_despues_de_un_close_con_keep_open() -> None:
    session, playwright, browser, context, page = build_session(keep_open=True)

    session.close()
    session.shutdown()

    assert session.is_closed is True
    assert (page.closed, context.closed, browser.closed, playwright.stopped) == (
        True,
        True,
        True,
        True,
    )


def test_la_sesion_sigue_registrada_mientras_no_se_cierre() -> None:
    session, *_ = build_session(keep_open=True)
    BrowserManager._register_session(session)

    session.close()

    assert any(item is session for item in BrowserManager._sessions)


def test_se_desregistra_solo_cuando_se_cierra_de_verdad() -> None:
    session, *_ = build_session(keep_open=False)
    BrowserManager._register_session(session)

    session.close()

    assert session.is_closed is True
    assert BrowserManager._sessions == []


def test_shutdown_all_alcanza_las_sesiones_mantenidas_abiertas() -> None:
    sesiones = []
    for _ in range(3):
        session, *_ = build_session(keep_open=True)
        BrowserManager._register_session(session)
        session.close()          # fin de corrida, como el finally del runner
        sesiones.append(session)

    assert len(BrowserManager._sessions) == 3   # antes quedaban 0

    BrowserManager.shutdown_all()

    assert BrowserManager._sessions == []
    assert all(item.is_closed for item in sesiones)


# ---------------------------------------------------------------------------
# Afinidad de hilo
# ---------------------------------------------------------------------------


def test_cierre_desde_otro_hilo_mata_el_driver_por_pid(_clean_registry) -> None:
    """Playwright es inalcanzable desde otro hilo: solo queda el PID."""

    killed = _clean_registry
    session, playwright, *_ = build_session(
        keep_open=True, driver_pid=777, resource=ForeignThreadResource
    )

    error: list[BaseException] = []

    def cerrar_desde_otro_hilo() -> None:
        try:
            session.shutdown()
        except BaseException as exc:  # noqa: BLE001
            error.append(exc)

    hilo = threading.Thread(target=cerrar_desde_otro_hilo)
    hilo.start()
    hilo.join()

    assert error == [], f"el cierre no debe propagar: {error}"
    assert killed == [777]
    assert session.is_closed is True


def test_shutdown_all_cierra_por_pid_una_sesion_de_hilo_ajeno(_clean_registry) -> None:
    """Al salir de la app, una sesion cuyo hilo murio se cierra matando el driver."""

    killed = _clean_registry
    session, *_ = build_session(keep_open=True, driver_pid=555, resource=ForeignThreadResource)
    BrowserManager._register_session(session)
    session.close()

    # El hilo propietario es este, asi que se simula que no lo es.
    session._owner_thread_ident = -1
    BrowserManager.shutdown_all()

    assert 555 in killed
    assert session.is_closed is True
    assert BrowserManager._sessions == []


# ---------------------------------------------------------------------------
# Vigilante
# ---------------------------------------------------------------------------


def test_el_vigilante_mata_el_driver_cuando_el_operador_cerro_el_navegador(
    _clean_registry, monkeypatch
) -> None:
    killed = _clean_registry
    session, *_ = build_session(keep_open=True, driver_pid=321)
    BrowserManager._register_session(session)
    session.close()
    monkeypatch.setattr(type(session), "browser_still_open", lambda self: False)

    assert BrowserManager.reap_orphan_sessions() == 1
    assert killed == [321]
    assert BrowserManager._sessions == []


def test_el_vigilante_respeta_un_navegador_que_sigue_abierto(
    _clean_registry, monkeypatch
) -> None:
    killed = _clean_registry
    session, *_ = build_session(keep_open=True, driver_pid=321)
    BrowserManager._register_session(session)
    session.close()
    monkeypatch.setattr(type(session), "browser_still_open", lambda self: True)

    assert BrowserManager.reap_orphan_sessions() == 0
    assert killed == []
    assert any(item is session for item in BrowserManager._sessions)


def test_el_vigilante_no_toca_nada_si_no_puede_saberlo(_clean_registry, monkeypatch) -> None:
    """Sin psutil, browser_still_open() devuelve None: no se mata por si acaso."""

    killed = _clean_registry
    session, *_ = build_session(keep_open=True, driver_pid=321)
    BrowserManager._register_session(session)
    session.close()
    monkeypatch.setattr(type(session), "browser_still_open", lambda self: None)

    assert BrowserManager.reap_orphan_sessions() == 0
    assert killed == []


def test_el_vigilante_no_toca_el_chrome_del_operador_en_modo_cdp(
    _clean_registry, monkeypatch
) -> None:
    killed = _clean_registry
    session, *_ = build_session(keep_open=True, driver_pid=321)
    session.disconnect_only = True
    BrowserManager._register_session(session)
    session.close()
    monkeypatch.setattr(type(session), "browser_still_open", lambda self: False)

    assert BrowserManager.reap_orphan_sessions() == 0
    assert killed == []


# ---------------------------------------------------------------------------
# Helpers de proceso
# ---------------------------------------------------------------------------


def test_browser_still_attached_sin_psutil_devuelve_none(monkeypatch) -> None:
    monkeypatch.setattr(bm, "psutil", None)
    assert bm.browser_still_attached(123) is None


def test_sin_pid_el_estado_es_desconocido_no_cerrado() -> None:
    """Regresion: devolver False aqui hacia que el vigilante matase sesiones vivas."""

    assert bm.browser_still_attached(None) is None


def test_el_vigilante_no_toca_una_sesion_viva_sin_pid_capturado(
    _clean_registry, tmp_path
) -> None:
    """Si Playwright mueve el atributo privado, el PID es None.

    Antes eso se leia como "huerfano": el vigilante marcaba cerrada una sesion
    VIVA, le borraba el perfil por debajo y la desregistraba, dejando el
    navegador fuera del alcance de shutdown_all. Justo la fuga que este cambio
    venia a corregir, provocada activamente.
    """

    killed = _clean_registry
    perfil = tmp_path / "perfil_en_uso"
    perfil.mkdir()
    session, playwright, browser, context, page = build_session(
        keep_open=True, driver_pid=None
    )
    session.profile_dir = str(perfil)
    session.cleanup_profile_dir = True
    BrowserManager._register_session(session)
    session.close()

    assert BrowserManager.reap_orphan_sessions() == 0
    assert killed == []
    assert session.is_closed is False
    assert perfil.exists(), "no se puede borrar el perfil de un navegador vivo"
    assert any(item is session for item in BrowserManager._sessions)

    # Y el cierre al salir de la app sigue funcionando.
    BrowserManager.shutdown_all()
    assert (page.closed, context.closed, browser.closed, playwright.stopped) == (
        True,
        True,
        True,
        True,
    )


def test_kill_driver_sin_pid_no_marca_cerrada_ni_borra_el_perfil(tmp_path) -> None:
    perfil = tmp_path / "perfil"
    perfil.mkdir()
    session, *_ = build_session(keep_open=True, driver_pid=None)
    session.profile_dir = str(perfil)
    session.cleanup_profile_dir = True

    assert session.kill_driver() is False
    assert session.is_closed is False
    assert perfil.exists()


def test_kill_driver_no_marca_cerrada_si_no_pudo_matar(monkeypatch) -> None:
    monkeypatch.setattr(bm, "kill_process_tree", lambda pid: False)
    session, *_ = build_session(keep_open=True, driver_pid=404)

    assert session.kill_driver() is False
    assert session.is_closed is False


def test_access_denied_es_desconocido_no_cerrado(monkeypatch) -> None:
    """AccessDenied en Windows es "no lo se", nunca "no hay navegador"."""

    access_denied = bm.psutil.AccessDenied

    class FakePsutil:
        STATUS_ZOMBIE = "zombie"
        Error = bm.psutil.Error
        NoSuchProcess = bm.psutil.NoSuchProcess

        class Process:
            def __init__(self, pid):
                pass

            def status(self):
                return "running"

            def children(self, recursive=False):
                raise access_denied(1)

    monkeypatch.setattr(bm, "psutil", FakePsutil)
    assert bm.browser_still_attached(123) is None


# ---------------------------------------------------------------------------
# Reutilizacion de PID
# ---------------------------------------------------------------------------


def test_no_se_remata_un_pid_que_stop_ya_libero(monkeypatch) -> None:
    """playwright.stop() reapea el driver; matar ese PID luego es un kill ciego."""

    killed: list[int] = []
    monkeypatch.setattr(bm, "kill_process_tree", lambda pid: killed.append(pid) or True)
    # El driver ya no existe tras stop(): no es un hijo vivo nuestro.
    monkeypatch.setattr(bm, "driver_process_alive", lambda pid: False)
    session, playwright, *_ = build_session(keep_open=False, driver_pid=2920)

    session.close()

    assert playwright.stopped is True
    assert killed == [], "no debe matarse un PID que ya fue liberado"


def test_se_remata_solo_si_el_driver_sobrevive_a_stop(monkeypatch) -> None:
    killed: list[int] = []
    monkeypatch.setattr(bm, "kill_process_tree", lambda pid: killed.append(pid) or True)
    monkeypatch.setattr(bm, "driver_process_alive", lambda pid: pid == 2920)
    session, *_ = build_session(keep_open=False, driver_pid=2920)

    session.close()

    assert killed == [2920]


def test_driver_process_alive_rechaza_un_pid_que_no_es_hijo_nuestro() -> None:
    import os

    # El propio proceso existe pero no es hijo de si mismo: no se debe matar.
    assert bm.driver_process_alive(os.getpid()) is False
    assert bm.driver_process_alive(None) is False
    assert bm.driver_process_alive(999999) is False


def test_capture_driver_pid_tolera_una_api_distinta() -> None:
    """Si Playwright mueve el atributo privado, se degrada a None sin romper."""

    assert bm.capture_driver_pid(object()) is None

    class Proc:
        pid = 909

    class Transport:
        _proc = Proc()

    class Connection:
        _transport = Transport()

    class Impl:
        _connection = Connection()

    class Playwright:
        _impl_obj = Impl()

    assert bm.capture_driver_pid(Playwright()) == 909


# ---------------------------------------------------------------------------
# Dos procesos simultaneos (la app permite 2 slots a la vez)
# ---------------------------------------------------------------------------
#
# Requisito: cerrar o limpiar el proceso 1 NUNCA debe detener ni cerrar el
# proceso 2 si sigue abierto. Cada corrida arranca su propio driver de
# Playwright, con su propio PID y su propio arbol de procesos.


def test_el_vigilante_limpia_un_slot_sin_tocar_el_otro(_clean_registry, monkeypatch) -> None:
    killed = _clean_registry
    slot1, *_ = build_session(keep_open=True, driver_pid=1001)
    slot2, pw2, br2, ctx2, pg2 = build_session(keep_open=True, driver_pid=2002)
    for session in (slot1, slot2):
        BrowserManager._register_session(session)
        session.close()

    # El operador cierra solo la ventana del slot 1.
    estados = {1001: False, 2002: True}
    monkeypatch.setattr(
        type(slot1), "browser_still_open", lambda self: estados[self.driver_pid]
    )

    assert BrowserManager.reap_orphan_sessions() == 1
    assert killed == [1001], "solo debe morir el driver del slot 1"

    # El slot 2 queda intacto: ni cerrado, ni desregistrado, ni tocado.
    assert slot2.is_closed is False
    assert (pg2.closed, ctx2.closed, br2.closed, pw2.stopped) == (False, False, False, False)
    assert [item is slot2 for item in BrowserManager._sessions] == [True]


def test_cerrar_la_corrida_de_un_slot_no_cierra_la_del_otro(_clean_registry) -> None:
    """El finally de una corrida solo afecta a su propia sesion."""

    killed = _clean_registry
    slot1, pw1, *_ = build_session(keep_open=False, driver_pid=1001)
    slot2, pw2, br2, ctx2, pg2 = build_session(keep_open=False, driver_pid=2002)
    for session in (slot1, slot2):
        BrowserManager._register_session(session)

    slot1.close()   # el slot 1 termina su corrida

    assert slot1.is_closed is True and pw1.stopped is True
    assert slot2.is_closed is False
    assert (pg2.closed, ctx2.closed, br2.closed, pw2.stopped) == (False, False, False, False)
    assert [item is slot2 for item in BrowserManager._sessions] == [True]


def test_matar_el_driver_de_un_slot_usa_solo_su_propio_pid(_clean_registry) -> None:
    killed = _clean_registry
    slot1, *_ = build_session(keep_open=True, driver_pid=1001, resource=ForeignThreadResource)
    slot2, *_ = build_session(keep_open=True, driver_pid=2002, resource=ForeignThreadResource)
    slot1._owner_thread_ident = -1

    slot1.shutdown()

    assert killed == [1001]
    assert slot2.is_closed is False


def test_shutdown_all_cierra_ambos_slots_al_salir_de_la_app(_clean_registry) -> None:
    sesiones = []
    for pid in (1001, 2002):
        session, *_ = build_session(keep_open=True, driver_pid=pid)
        BrowserManager._register_session(session)
        session.close()
        sesiones.append(session)

    assert len(BrowserManager._sessions) == 2

    BrowserManager.shutdown_all()

    assert all(item.is_closed for item in sesiones)
    assert BrowserManager._sessions == []


# ---------------------------------------------------------------------------
# Rama de Windows (la maquina del operador)
# ---------------------------------------------------------------------------


def _fake_run(returncode: int, registro: list):
    class Completed:
        def __init__(self, rc):
            self.returncode = rc

    def run(cmd, **kwargs):
        registro.append(cmd)
        return Completed(returncode)

    return run


def test_en_windows_se_mata_el_arbol_de_ese_pid_y_solo_ese(monkeypatch) -> None:
    registro: list = []
    monkeypatch.setattr(bm.os, "name", "nt")
    monkeypatch.setattr(bm.subprocess, "run", _fake_run(0, registro))

    assert _KILL_REAL(1001) is True
    assert registro == [["taskkill", "/F", "/T", "/PID", "1001"]]


def test_en_windows_un_pid_inexistente_no_se_reporta_como_exito(monkeypatch) -> None:
    """taskkill devuelve != 0 si el proceso ya no esta: el recuento no debe mentir."""

    monkeypatch.setattr(bm.os, "name", "nt")
    monkeypatch.setattr(bm.subprocess, "run", _fake_run(128, []))

    assert _KILL_REAL(1001) is False


# ---------------------------------------------------------------------------
# Nombres de proceso del navegador por plataforma
#
# Fallo real, Mac Mini, 2026-10-17: el navegador se abria, metia credenciales y
# a los 15 segundos moria con "Connection closed while reading from the driver".
# El log lo dejo escrito:
#
#   Driver huerfano eliminado (run_id=1, pid=1625): el navegador ya estaba
#   cerrado.
#
# No estaba cerrado. _browser_process_names comparaba por igualdad contra una
# lista de nombres de Windows, el proceso real se llamaba "Google Chrome for
# Testing", no casaba, browser_still_attached devolvia False, y el vigilante
# mataba la sesion viva en su primera ronda (5 s).
# ---------------------------------------------------------------------------


def _psutil_con_hijos(*nombres: str, exes: dict[str, str] | None = None):
    """Doble de psutil cuyo driver tiene esos hijos."""

    rutas = exes or {}

    class FakeHijo:
        def __init__(self, nombre: str) -> None:
            self._nombre = nombre

        def name(self) -> str:
            return self._nombre

        def exe(self) -> str:
            return rutas.get(self._nombre, f"/ruta/{self._nombre}")

    class FakePsutil:
        STATUS_ZOMBIE = "zombie"
        Error = bm.psutil.Error
        NoSuchProcess = bm.psutil.NoSuchProcess

        class Process:
            def __init__(self, pid):
                pass

            def status(self):
                return "running"

            def children(self, recursive=False):
                return [FakeHijo(nombre) for nombre in nombres]

    return FakePsutil


@pytest.mark.parametrize(
    "nombre",
    [
        "chrome.exe",            # Windows
        "Google Chrome",         # macOS, el del sistema
        "Google Chrome for Testing",  # macOS, el que trae Playwright
        "chromium",
        "msedge.exe",
    ],
)
def test_se_reconoce_el_navegador_en_cada_plataforma(monkeypatch, nombre: str) -> None:
    monkeypatch.setattr(bm, "psutil", _psutil_con_hijos(nombre))

    assert bm.browser_still_attached(123) is True


def test_se_reconoce_aunque_psutil_trunque_el_nombre(monkeypatch) -> None:
    # En macOS el nombre de proceso viene cortado. Si el nombre no sirve, el
    # ejecutable si.
    monkeypatch.setattr(
        bm,
        "psutil",
        _psutil_con_hijos(
            "",
            exes={"": "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"},
        ),
    )

    assert bm.browser_still_attached(123) is True


def test_sin_hijos_es_que_no_hay_navegador(monkeypatch) -> None:
    # Driver pelado: aqui si hay huerfano que limpiar.
    monkeypatch.setattr(bm, "psutil", _psutil_con_hijos())

    assert bm.browser_still_attached(123) is False


def test_hijos_no_reconocidos_es_no_lo_se_y_no_no_hay(monkeypatch) -> None:
    """La guarda que convierte este fallo en inofensivo.

    Si manana cambia un nombre de proceso o aparece otra plataforma, el
    resultado debe ser "el vigilante no limpia un huerfano", nunca "el
    vigilante mata al agente a media faena".
    """

    monkeypatch.setattr(bm, "psutil", _psutil_con_hijos("node", "algo-raro"))

    assert bm.browser_still_attached(123) is None


def test_el_vigilante_no_mata_una_sesion_de_macos(_clean_registry, monkeypatch) -> None:
    """Regresion de extremo a extremo del fallo del Mac Mini."""

    killed = _clean_registry
    session, *_ = build_session(keep_open=True, driver_pid=1625)
    BrowserManager._register_session(session)
    session.close()
    monkeypatch.setattr(bm, "psutil", _psutil_con_hijos("Google Chrome for Testing"))

    assert BrowserManager.reap_orphan_sessions() == 0
    assert killed == []
    assert any(item is session for item in BrowserManager._sessions)
