"""Prueba de la fuga con procesos REALES (lenta, desactivada por defecto).

Lanza Chromium de verdad, asi que no entra en la suite normal. Para ejecutarla:

    AHL_BROWSER_E2E=1 python -m pytest tests/test_browser_session_leak_real.py -v

En Windows basta con eso (usa el canal "chrome" instalado). Para apuntar a un
binario concreto:  AHL_BROWSER_E2E_EXECUTABLE=C:\\ruta\\a\\chrome.exe

Lo que demuestra, con procesos del sistema y no con dobles:
  * Sin el arreglo, cada corrida deja un navegador y un driver vivos.
  * Con el arreglo, el driver se puede matar desde otro hilo aunque el hilo
    propietario ya haya muerto, que es el caso que Playwright no permite cerrar.
"""

from __future__ import annotations

import os
import threading
import time

import pytest

from automation import browser_manager as bm

pytestmark = pytest.mark.skipif(
    not os.environ.get("AHL_BROWSER_E2E"),
    reason="lanza navegadores reales; activar con AHL_BROWSER_E2E=1",
)

psutil = pytest.importorskip("psutil")


def _launch_kwargs() -> dict:
    executable = os.environ.get("AHL_BROWSER_E2E_EXECUTABLE")
    kwargs: dict = {
        "headless": True,
        "args": ["--no-sandbox", "--disable-dev-shm-usage"],
    }
    if executable:
        kwargs["executable_path"] = executable
    else:
        kwargs["channel"] = "chrome"
    return kwargs


def _abrir_en_hilo_que_muere() -> int:
    """Replica una corrida: abre en un hilo worker que termina sin cerrar."""

    from playwright.sync_api import sync_playwright

    capturado: dict[str, int | None] = {}

    def corrida() -> None:
        playwright = sync_playwright().start()
        capturado["pid"] = bm.capture_driver_pid(playwright)
        browser = playwright.chromium.launch(**_launch_kwargs())
        browser.new_context().new_page().goto("about:blank")
        # keep_open=True: el hilo termina sin cerrar nada.

    hilo = threading.Thread(target=corrida, name="corrida-falsa")
    hilo.start()
    hilo.join(timeout=120)
    assert not hilo.is_alive(), "la corrida de prueba no termino"
    pid = capturado.get("pid")
    assert pid, "no se pudo capturar el PID del driver (¿cambio la API de Playwright?)"
    return pid


def test_el_driver_sobrevive_al_hilo_y_se_puede_matar_por_pid() -> None:
    driver_pid = _abrir_en_hilo_que_muere()
    time.sleep(2)

    # El driver y su navegador siguen vivos: esta es la fuga.
    assert psutil.pid_exists(driver_pid)
    assert bm.browser_still_attached(driver_pid) is True

    # Y el arreglo los recupera desde un hilo que no es el propietario.
    assert bm.kill_process_tree(driver_pid) is True
    for _ in range(20):
        time.sleep(0.5)
        if bm.browser_still_attached(driver_pid) is False:
            break
    assert bm.browser_still_attached(driver_pid) is False


def test_el_vigilante_detecta_el_navegador_cerrado_a_mano() -> None:
    """Cerrar la ventana deja el driver vivo; el vigilante lo debe detectar."""

    driver_pid = _abrir_en_hilo_que_muere()
    time.sleep(2)
    assert bm.browser_still_attached(driver_pid) is True

    # El operador cierra la ventana: matamos solo el navegador, no el driver.
    navegadores = [
        child
        for child in psutil.Process(driver_pid).children(recursive=True)
        if (child.name() or "").lower() in bm._browser_process_names()
    ]
    assert navegadores, "no se encontro el proceso del navegador"
    min(navegadores, key=lambda c: c.pid).terminate()

    for _ in range(20):
        time.sleep(0.5)
        if bm.browser_still_attached(driver_pid) is False:
            break

    # El driver sigue vivo (la basura que el usuario reporto)...
    assert psutil.pid_exists(driver_pid)
    # ...y el vigilante lo ve como huerfano.
    assert bm.browser_still_attached(driver_pid) is False

    bm.kill_process_tree(driver_pid)


def test_dos_procesos_simultaneos_quedan_aislados() -> None:
    """La app permite 2 slots a la vez: limpiar uno no debe tocar al otro.

    Con procesos reales: cada corrida arranca su propio driver, con su propio
    arbol. Se cierra la ventana del slot 1 y se comprueba que el slot 2 sigue
    entero.
    """

    import threading

    from playwright.sync_api import sync_playwright

    pids: dict[int, int] = {}
    barrera = threading.Barrier(2)

    def corrida(slot: int) -> None:
        playwright = sync_playwright().start()
        pids[slot] = bm.capture_driver_pid(playwright)
        browser = playwright.chromium.launch(**_launch_kwargs())
        browser.new_context().new_page().goto("about:blank")
        barrera.wait(timeout=120)   # los dos abiertos a la vez

    hilos = [threading.Thread(target=corrida, args=(slot,)) for slot in (1, 2)]
    for hilo in hilos:
        hilo.start()
    for hilo in hilos:
        hilo.join(timeout=180)
    assert not any(hilo.is_alive() for hilo in hilos)

    uno, dos = pids[1], pids[2]
    assert uno != dos, "cada corrida debe tener su propio driver"
    try:
        arbol_uno = {c.pid for c in psutil.Process(uno).children(recursive=True)}
        arbol_dos = {c.pid for c in psutil.Process(dos).children(recursive=True)}
        assert arbol_uno.isdisjoint(arbol_dos), "los arboles no deben solaparse"
        assert bm.browser_still_attached(uno) is True
        assert bm.browser_still_attached(dos) is True

        # Se limpia el slot 1 exactamente como hace el vigilante.
        bm.kill_process_tree(uno)
        for _ in range(20):
            time.sleep(0.5)
            if bm.browser_still_attached(uno) is False:
                break

        assert bm.browser_still_attached(uno) is False
        assert bm.browser_still_attached(dos) is True, "el slot 2 no debe verse afectado"
    finally:
        for pid in (uno, dos):
            bm.kill_process_tree(pid)
