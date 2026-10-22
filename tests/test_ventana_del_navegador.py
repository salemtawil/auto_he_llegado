"""Tamano y zoom del navegador de la automatizacion.

El agente los necesita para tener la app y el navegador a la vista a la vez en
pantallas chicas. Lo que NO puede pasar es que un valor mal escrito deje el
navegador inusable, ni que la ventana baje tanto que el sitio sirva su diseno
movil: ese es otro HTML y romperia todos los selectores.
"""

from __future__ import annotations

import pytest

from automation.browser_manager import BrowserManager


def _args(extra=None, **kwargs) -> list[str]:
    return BrowserManager._build_browser_launch_args(extra, **kwargs)  # noqa: SLF001


def test_sin_pedir_nada_se_mantiene_el_tamano_de_siempre() -> None:
    args = _args()
    assert "--window-size=1440,960" in args
    assert not any(a.startswith("--force-device-scale-factor") for a in args)


def test_el_zoom_se_traduce_a_factor_de_escala() -> None:
    assert "--force-device-scale-factor=0.63" in _args(zoom_percent=63)
    assert "--force-device-scale-factor=0.8" in _args(zoom_percent=80)


def test_el_zoom_al_cien_no_anade_nada() -> None:
    assert not any(a.startswith("--force-device-scale-factor") for a in _args(zoom_percent=100))


@pytest.mark.parametrize("valor", [0, 10, 500, -50, None, "sesenta"])
def test_un_zoom_absurdo_se_ignora_en_vez_de_romper_el_navegador(valor) -> None:
    assert not any(a.startswith("--force-device-scale-factor") for a in _args(zoom_percent=valor))


def test_la_ventana_tiene_suelo_para_no_caer_en_el_diseno_movil() -> None:
    # Por debajo del suelo los sitios cambian de HTML y los selectores de las
    # automatizaciones dejan de encontrar nada.
    args = _args(window_size=(320, 480))
    assert "--window-size=900,600" in args


def test_un_tamano_razonable_se_respeta() -> None:
    assert "--window-size=1100,800" in _args(window_size=(1100, 800))


def test_el_zoom_convive_con_los_argumentos_de_la_extension() -> None:
    args = _args(["--load-extension=/x"], window_size=(1000, 700), zoom_percent=75)
    assert "--load-extension=/x" in args
    assert "--window-size=1000,700" in args
    assert "--force-device-scale-factor=0.75" in args
