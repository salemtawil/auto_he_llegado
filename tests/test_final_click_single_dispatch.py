"""Un unico intento de activacion del boton final por corrida.

Regresion: un timeout de Playwright, o una confirmacion que tarda, NO prueban que
el click no llegara al sitio. El codigo anterior lo trataba como "no llego":

- `base_site._try_fast_click_final_from_flow_context` escalaba
  click -> click(force=True) -> evaluate("node.click()");
- `_submit_final` de Compinche/Ready4Drive reintentaba 3 veces, y su
  `_click_locator_resilient` escalaba a force=True, Space y Enter
  (3 x 4 = hasta 12 activaciones reales de "He llegado");
- `_submit_final` de Paripe reintentaba 3 veces con click / force / evaluate.

Cualquiera de esas rutas podia aceptar el bloque por duplicado.
"""

from __future__ import annotations

import pytest

from automation.base_site import BaseSite


class _Recorder:
    """Boton que cuenta activaciones y simula el caso peligroso.

    `fail_dispatch=True`: el sitio recibe el click, pero Playwright informa timeout.
    """

    def __init__(self, *, fail_dispatch: bool = False) -> None:
        self.activations: list[str] = []
        self._fail_dispatch = fail_dispatch

    def click(self, **kwargs):
        self.activations.append("click")
        if self._fail_dispatch:
            raise TimeoutError("Timeout 2000ms exceeded")

    def evaluate(self, _script):  # pragma: no cover - no debe llamarse nunca
        self.activations.append("evaluate")

    def press(self, key):  # pragma: no cover - no debe llamarse nunca
        self.activations.append(f"press:{key}")

    def wait_for(self, **kwargs):
        return None

    def scroll_into_view_if_needed(self, **kwargs):
        return None


class _Site(BaseSite):
    """Sitio minimo con solo lo que tocan los helpers compartidos."""

    def execute(self, *args, **kwargs):  # pragma: no cover - abstracto, no se usa
        raise NotImplementedError

    def __init__(self) -> None:
        self._timing_first_by_event: dict[str, dict] = {}
        self.progress: list[tuple[str, str]] = []

    def _mark_phase_timing(self, event, **fields):
        self._timing_first_by_event.setdefault(event, dict(fields))

    def _record_run_stat(self, event, **fields):
        return None

    def emit_progress(self, callback, *, phase, message):
        self.progress.append((phase, message))


# ---------------------------------------------------------------------------
# Helpers compartidos
# ---------------------------------------------------------------------------


def test_un_despacho_exitoso_activa_el_boton_una_sola_vez() -> None:
    site = _Site()
    button = _Recorder()

    error = site._dispatch_final_click_once(button)

    assert error is None
    assert button.activations == ["click"]


def test_un_timeout_de_playwright_no_provoca_una_segunda_activacion() -> None:
    """EL CASO PELIGROSO: el sitio recibio el click, Playwright dice timeout."""

    site = _Site()
    button = _Recorder(fail_dispatch=True)

    error = site._dispatch_final_click_once(button)

    assert isinstance(error, TimeoutError)
    assert button.activations == ["click"], (
        f"se activo el boton mas de una vez: {button.activations}"
    )
    assert "No se reintenta" in site.progress[-1][1]


def test_el_flag_se_marca_antes_de_despachar() -> None:
    """Si se marcase despues, una excepcion dejaria la corrida sin proteccion."""

    site = _Site()
    assert site._final_submit_resolved() is False

    marcado: list[bool] = []

    class _CheckingButton(_Recorder):
        def click(self, **kwargs):
            marcado.append(site._final_submit_resolved())
            return super().click(**kwargs)

    site._mark_final_submit_clicked()
    site._dispatch_final_click_once(_CheckingButton())

    assert marcado == [True], "el flag debe estar puesto ya durante el despacho"
    assert site._final_submit_resolved() is True


def test_final_click_done_registrado_tambien_resuelve() -> None:
    site = _Site()
    site._mark_phase_timing("final_click_done", source="x")
    assert site._final_submit_resolved() is True


# ---------------------------------------------------------------------------
# Via rapida compartida
# ---------------------------------------------------------------------------


class _FastPathSite(_Site):
    def __init__(self, button) -> None:
        super().__init__()
        self._button = button
        self._latest_block_snapshot_text = ""

    def _safe_page_url(self, page):
        return "https://example.test/x"

    def _find_final_submit_button(self, context, page=None):
        return self._button

    def _context_has_block_details(self, context):
        return True

    def _capture_block_snapshot_text(self, context, page):
        return "bloque"


class _Ctx:
    def locator(self, *_args, **_kwargs):
        return None


@pytest.mark.parametrize("fail_dispatch", [False, True])
def test_la_via_rapida_activa_el_boton_una_sola_vez(fail_dispatch: bool) -> None:
    button = _Recorder(fail_dispatch=fail_dispatch)
    site = _FastPathSite(button)

    resultado = BaseSite._try_fast_click_final_from_flow_context(
        site, page=object(), context=_Ctx(), progress_callback=None, source="test"
    )

    assert resultado is True, "la via rapida debe darse por despachada en ambos casos"
    assert button.activations == ["click"], (
        f"se activo el boton mas de una vez: {button.activations}"
    )
    assert site._final_submit_resolved() is True
    assert "final_click_done" in site._timing_first_by_event


def test_la_via_rapida_registra_el_error_de_despacho_sin_reintentar() -> None:
    button = _Recorder(fail_dispatch=True)
    site = _FastPathSite(button)

    BaseSite._try_fast_click_final_from_flow_context(
        site, page=object(), context=_Ctx(), progress_callback=None, source="test"
    )

    assert site._timing_first_by_event["final_click_done"]["dispatch_error"] == "TimeoutError"
    assert button.activations == ["click"]
