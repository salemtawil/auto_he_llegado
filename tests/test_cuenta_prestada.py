"""El selector cuenta prestada / cuenta propia siempre acaba en "prestada".

Aparece en el panel de Paripe nada mas entrar, y en el iframe de
Compinche/Ready4Drive al pulsar "He llegado". El proceso solo va bien con
"Cuenta prestada".

El estado NO se decide por `aria-checked`: en el panel real, con "Cuenta
prestada" activa, el switch vale `aria-checked="false"`. Esa inversion es una
decision del sitio que puede cambiar sin avisar. Lo que se lee es lo que ve el
agente: el lado activo esta `disabled` y pintado con la clase de acento.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from automation.base_site import BaseSite

RAIZ = Path(__file__).resolve().parents[1]

# HTML exacto del panel de Paripe, con "Cuenta prestada" activa.
HTML_REAL_PRESTADA = (
    '<div class="flex items-center justify-between space-x-3 rounded-lg bg-gray-200/70 p-4 text-center">'
    '<button type="button" disabled="" class="relative flex text-lg leading-5 font-semibold text-primary-500">'
    '<div class="mr-0.5 h-2 w-2 flex-shrink-0 rounded-full bg-green-500"></div>'
    '<span class="max-w-28">Cuenta prestada</span></button>'
    '<div class="w-full"><button class="inline-flex h-8 w-[4.8rem]" role="switch" type="button"'
    ' aria-checked="false"><span class="size-6 translate-x-1"></span></button></div>'
    '<button type="button" class="relative flex text-lg leading-5 font-medium text-gray-500">'
    '<span class="max-w-28">Cuenta propia</span>'
    '<div class="ml-0.5 h-2 w-2 flex-shrink-0 rounded-full bg-gray-500"></div></button></div>'
)


class _Sitio(BaseSite):
    def execute(self, *args, **kwargs):  # pragma: no cover - abstracto
        raise NotImplementedError

    def __init__(self, estados: list[dict]) -> None:
        self._estados = list(estados)
        self.clicks: list[str] = []
        self.progreso: list[str] = []
        self.esperas = 0

    # --- lo que el metodo necesita de su alrededor -------------------------
    def _leer_estado_de_cuenta(self, _root) -> dict:
        return self._estados.pop(0) if len(self._estados) > 1 else self._estados[0]

    def _localizar_interruptor_de_cuenta(self, _root):
        return "interruptor"

    def _click_locator_resilient(self, locator, *, phase: str, error_message: str) -> None:
        self.clicks.append(phase)

    def emit_progress(self, _callback, *, phase: str, message: str) -> None:  # type: ignore[override]
        self.progreso.append(message)

    def _record_run_stat(self, event: str, **detalles) -> None:
        pass


class _Raiz:
    def wait_for_timeout(self, _ms) -> None:
        pass


def test_si_ya_esta_en_prestada_no_se_toca_nada() -> None:
    sitio = _Sitio([{"encontrado": True, "prestada": True, "aria": "false"}])

    assert sitio._asegurar_cuenta_prestada(_Raiz()) == "ya_estaba"  # noqa: SLF001
    assert sitio.clicks == [], "pulsar el switch estando bien lo pondria en cuenta propia"


def test_si_no_hay_selector_el_paso_no_estorba() -> None:
    # Es lo normal en la mayoria de pantallas: el metodo se llama en varias y
    # no puede convertir su ausencia en un fallo.
    sitio = _Sitio([{"encontrado": False}])

    assert sitio._asegurar_cuenta_prestada(_Raiz()) == "ausente"  # noqa: SLF001
    assert sitio.clicks == []


def test_si_esta_en_propia_se_cambia_y_se_verifica() -> None:
    sitio = _Sitio([
        {"encontrado": True, "prestada": False, "aria": "true"},
        {"encontrado": True, "prestada": True, "aria": "false"},
    ])

    assert sitio._asegurar_cuenta_prestada(_Raiz()) == "cambiado"  # noqa: SLF001
    assert sitio.clicks == ["account_selection"]
    assert any("Cuenta prestada" in m for m in sitio.progreso)


def test_si_el_switch_no_responde_se_dice_en_vez_de_seguir() -> None:
    # Seguir con la cuenta propia hace fallar el proceso mucho mas adelante,
    # donde ya no se entiende por que.
    sitio = _Sitio([{"encontrado": True, "prestada": False, "aria": "true"}])

    with pytest.raises(RuntimeError, match="no quedo en 'Cuenta prestada'"):
        sitio._asegurar_cuenta_prestada(_Raiz())  # noqa: SLF001


def test_el_estado_no_se_decide_por_aria_checked() -> None:
    # En el panel real, prestada activa == aria-checked "false". Si alguien
    # "simplifica" esto leyendo el aria, invierte el comportamiento.
    fuente = (RAIZ / "automation" / "base_site.py").read_text(encoding="utf-8")
    js = re.search(r'_JS_ESTADO_DE_CUENTA = r"""(.*?)"""', fuente, re.S).group(1)
    decision = js[js.index("const activa"):js.index("return {")]
    assert "aria-checked" not in decision or "lado.getAttribute" in decision
    assert "disabled" in decision, "el lado activo se reconoce porque esta deshabilitado"
    assert "text-primary" in decision, "y porque lleva la clase de acento"


def test_el_html_real_del_panel_sigue_encajando_con_lo_que_se_busca() -> None:
    # Guardia barata: si el sitio renombra las etiquetas, esto salta antes de
    # que una corrida se quede en cuenta propia sin avisar.
    assert re.search(BaseSite._CUENTA_PRESTADA_RE, HTML_REAL_PRESTADA, re.I)  # noqa: SLF001
    assert re.search(BaseSite._CUENTA_PROPIA_RE, HTML_REAL_PRESTADA, re.I)  # noqa: SLF001
    assert 'role="switch"' in HTML_REAL_PRESTADA
