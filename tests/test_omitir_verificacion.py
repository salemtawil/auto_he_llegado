"""El dialogo "Verificacion del propietario de la cuenta", version nueva.

Aparece en Compinche y Ready4Drive al pulsar "Iniciar verificacion", despues
de confirmar cuenta prestada. Trae tres opciones y llega con la primera ya
elegida:

- "Enviar enlace al dueno": espera a que una persona abra un enlace en su
  telefono. No hay nadie.
- "Verificacion automatica de video": pide tres selfies del dueno.
- "Omitir verificacion - Continua solo con tu selfie": la unica con la que el
  proceso puede seguir solo.

El boton de seguir aparece al elegir. Si no se elige nada, el proceso se
queda esperando en una pantalla que nunca avanza.
"""

from __future__ import annotations

import re

from automation.base_site import BaseSite
from automation.compinche_site import CompincheSite
from automation.paripe_site import ParipeSite
from automation.ready4drive_site import Ready4DriveSite


class _Sitio(BaseSite):
    site_name = "prueba"
    _ENTRY_URL = "https://ejemplo/login"

    def execute(self, *args, **kwargs):  # pragma: no cover - abstracto
        raise NotImplementedError

    def __init__(self, opcion, *, marcada_tras_click: bool = True) -> None:
        self._opcion = opcion
        self._marcada_tras_click = marcada_tras_click
        self.clicks: list[str] = []
        self.anotaciones: list[str] = []

    def _localizar_opcion(self, _root, _patron):
        return self._opcion

    def _opcion_esta_marcada(self, opcion):
        if opcion is None:
            return None
        if self.clicks and self._marcada_tras_click:
            return True
        return opcion.marcada

    def _click_locator_resilient(self, _locator, *, phase: str, error_message: str) -> None:
        self.clicks.append(phase)

    def _anotar(self, evento: str, **_detalles) -> None:
        self.anotaciones.append(evento)

    def _record_run_stat(self, *_args, **_kwargs) -> None:
        pass


class _Opcion:
    def __init__(self, marcada=False) -> None:
        self.marcada = marcada


class _Raiz:
    def wait_for_timeout(self, _ms) -> None:
        pass


PATRON = BaseSite._patron_de_textos(  # noqa: SLF001
    ("Omitir verificacion", "Omitir verificación", "Skip verification")
)


def test_el_patron_encaja_con_la_tilde_de_la_pagina() -> None:
    """La trampa: el texto de la pagina lleva tilde.

    Construir el patron a partir del texto normalizado sin acentos daria una
    expresion que nunca encaja con "Omitir verificación", y el paso no haria
    nada sin que nada fallara.
    """

    assert re.search(PATRON, "Omitir verificación", re.I)
    assert re.search(PATRON, "Omitir verificacion", re.I)
    # Los espacios se aflojan: el sitio puede partir el texto en dos nodos.
    assert re.search(PATRON, "Omitir  verificación", re.I)


def test_el_patron_no_encaja_con_las_otras_dos_opciones() -> None:
    # Elegir la equivocada deja el proceso esperando a una persona.
    for otra in (
        "Enviar enlace al dueño",
        "El dueño se verifica desde su propio teléfono.",
        "Verificación automática de video",
        "Sube tres selfies del dueño.",
    ):
        assert not re.search(PATRON, otra, re.I), otra


def test_si_la_opcion_no_esta_marcada_se_pulsa() -> None:
    sitio = _Sitio(_Opcion(marcada=False))

    assert sitio._elegir_opcion(_Raiz(), PATRON, evento="omitir") == "elegida"  # noqa: SLF001
    assert sitio.clicks == ["account_selection"]


def test_si_ya_estaba_elegida_no_se_vuelve_a_pulsar() -> None:
    # Un segundo click en una lista de opciones puede deseleccionar lo que ya
    # estaba bien.
    sitio = _Sitio(_Opcion(marcada=True))

    assert sitio._elegir_opcion(_Raiz(), PATRON, evento="omitir") == "ya_estaba"  # noqa: SLF001
    assert sitio.clicks == []


def test_si_no_hay_opciones_no_es_un_fallo() -> None:
    # Es el dialogo de la version anterior, el que solo trae el boton.
    sitio = _Sitio(None)

    assert sitio._elegir_opcion(_Raiz(), PATRON, evento="omitir") == "ausente"  # noqa: SLF001
    assert sitio.clicks == []


def test_si_se_pulsa_y_no_se_confirma_no_se_reintenta() -> None:
    sitio = _Sitio(_Opcion(marcada=False), marcada_tras_click=False)
    sitio.CUENTA_SWITCH_TIMEOUT_MS = 10

    assert sitio._elegir_opcion(_Raiz(), PATRON, evento="omitir") == "no_confirmado"  # noqa: SLF001
    assert sitio.clicks == ["account_selection"], "un segundo click la desmarcaria"


def test_los_tres_sitios_conocen_la_opcion_de_omitir() -> None:
    # Paripe sirve el mismo iframe, asi que le va a llegar igual.
    for sitio in (CompincheSite, Ready4DriveSite, ParipeSite):
        textos = sitio()._selectors.owner_verification_skip_texts  # noqa: SLF001
        assert any("Omitir" in t for t in textos)
        assert any("ó" in t for t in textos), "hace falta la version con tilde"


def test_el_titulo_del_dialogo_nuevo_se_reconoce() -> None:
    # Es lo que decide que el paso se ejecute: sin esto no se mira nada.
    textos = CompincheSite()._selectors.owner_verification_texts  # noqa: SLF001
    assert "Verificación del propietario de la cuenta" in textos


def test_ningun_sitio_busca_el_boton_por_posicion() -> None:
    """En este dialogo hay tambien "Copiar enlace" y la X de cerrar.

    Coger "el ultimo boton" o "el primero" abriria el flujo del enlace al
    dueno, que es justo el que no se puede seguir sin una persona delante.
    """

    import inspect

    for clase in (CompincheSite, ParipeSite):
        fuente = inspect.getsource(clase._esperar_boton_de_continuar)  # noqa: SLF001
        assert "etiquetas" in fuente
        for prohibido in (".last", ".first", "nth(", "[-1]"):
            assert prohibido not in fuente, (clase.__name__, prohibido)


def test_las_etiquetas_del_boton_no_chocan_con_las_otras_opciones() -> None:
    """Un boton mal elegido abre el flujo del enlace al dueno.

    Las etiquetas con las que se busca el boton de seguir no pueden encajar
    con "Copiar enlace", ni con los titulos de las otras dos opciones.
    """

    peligrosos = (
        "Copiar enlace",
        "Copy link",
        "Enviar enlace al dueño",
        "Verificación automática de video",
        "Sube tres selfies del dueño.",
    )
    for sitio in (CompincheSite, Ready4DriveSite, ParipeSite):
        selectores = sitio()._selectors  # noqa: SLF001
        etiquetas = (
            selectores.self_owner_continue_texts
            + selectores.continue_texts
            + selectores.owner_verification_continue_texts
        )
        for etiqueta in etiquetas:
            for texto in peligrosos:
                assert etiqueta.lower() not in texto.lower(), (etiqueta, texto)
