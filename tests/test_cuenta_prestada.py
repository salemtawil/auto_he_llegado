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

import ast
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


# Radiogroup real del iframe de Compinche. Las dos opciones comparten
# aria-label="borrowed-account": es el nombre del GRUPO, no de la opcion, y
# quien se fie de el marca la equivocada.
HTML_REAL_RADIOGRUPO = (
    '<div class="mt-6 grid grid-cols-2 gap-x-4" id="headlessui-radiogroup-:r0:" role="radiogroup">'
    '<span aria-label="borrowed-account" role="radio" aria-checked="false" tabindex="-1"'
    ' id="headlessui-radio-:r1:" data-headlessui-state="">'
    '<span class="block text-sm font-medium text-gray-900">Cuenta propia</span>'
    '<span class="text-sm text-gray-700">Selecciona si eres el dueno de la cuenta</span></span>'
    '<span aria-label="borrowed-account" role="radio" aria-checked="true" tabindex="0"'
    ' id="headlessui-radio-:r2:" data-headlessui-state="checked" data-checked="">'
    '<span class="block text-sm font-medium text-gray-900">Cuenta prestada</span>'
    '<span class="text-sm text-gray-700">Selecciona para generar una foto</span></span></div>'
)


class _Opcion:
    """Imita un locator de Playwright sobre una tarjeta del grupo."""

    def __init__(self, texto: str, *, aria: str | None, data: str | None) -> None:
        self.texto = texto
        self.atributos = {"aria-checked": aria, "data-checked": data}
        self.pulsada = False

    def get_attribute(self, nombre: str):
        return self.atributos.get(nombre)

    def marcar(self) -> None:
        self.pulsada = True
        self.atributos = {"aria-checked": "true", "data-checked": ""}


class _Grupo:
    def __init__(self, opciones: list[_Opcion]) -> None:
        self.opciones = opciones

    def filter(self, has_text=None, has_not_text=None):
        quedan = [o for o in self.opciones if has_text is None or has_text.search(o.texto)]
        if has_not_text is not None:
            quedan = [o for o in quedan if not has_not_text.search(o.texto)]
        return _Grupo(quedan)

    @property
    def first(self):
        return _Grupo(self.opciones[:1])

    def count(self) -> int:
        return len(self.opciones)

    def get_attribute(self, nombre: str):
        return self.opciones[0].get_attribute(nombre)


class _RaizConRadios:
    def __init__(self, opciones: list[_Opcion]) -> None:
        self.opciones = opciones

    def locator(self, selector: str):
        return _Grupo(self.opciones if selector == '[role="radio"]' else [])

    def evaluate(self, *_args, **_kwargs):
        raise RuntimeError("esta pantalla no tiene switch")

    def wait_for_timeout(self, _ms) -> None:
        pass


def _tarjetas(prestada_marcada: bool) -> list[_Opcion]:
    return [
        _Opcion("Cuenta propia Selecciona si eres el dueno", aria="false", data=None),
        _Opcion(
            "Cuenta prestada Selecciona para generar una foto",
            aria="true" if prestada_marcada else "false",
            data="" if prestada_marcada else None,
        ),
    ]


class _SitioConRadios(BaseSite):
    def execute(self, *args, **kwargs):  # pragma: no cover - abstracto
        raise NotImplementedError

    def __init__(self) -> None:
        self.pulsada: _Opcion | None = None

    def _click_locator_resilient(self, locator, *, phase: str, error_message: str) -> None:
        self.pulsada = locator.opciones[0]
        self.pulsada.marcar()

    def emit_progress(self, _callback, *, phase: str, message: str) -> None:  # type: ignore[override]
        pass

    def _record_run_stat(self, event: str, **detalles) -> None:
        pass


def test_en_el_radiogrupo_ya_marcado_no_se_pulsa_nada() -> None:
    sitio = _SitioConRadios()

    assert sitio._asegurar_cuenta_prestada(_RaizConRadios(_tarjetas(True))) == "ya_estaba"  # noqa: SLF001
    assert sitio.pulsada is None, "volver a pulsar lo dejaria en cuenta propia"


def test_en_el_radiogrupo_se_pulsa_la_tarjeta_prestada_no_la_otra() -> None:
    sitio = _SitioConRadios()
    tarjetas = _tarjetas(False)

    assert sitio._asegurar_cuenta_prestada(_RaizConRadios(tarjetas)) == "cambiado"  # noqa: SLF001
    assert sitio.pulsada is tarjetas[1], "se pulso la tarjeta equivocada"
    assert "prestada" in sitio.pulsada.texto.lower()


def test_el_radio_marcado_solo_con_data_checked_tambien_cuenta() -> None:
    # Headless UI lo pone vacio: `data-checked=""`. Comparar contra "true"
    # daria siempre falso y acabariamos pulsando una opcion ya elegida.
    sitio = _SitioConRadios()
    solo_data = [_Opcion("Cuenta prestada", aria=None, data="")]

    assert sitio._asegurar_cuenta_prestada(_RaizConRadios(solo_data)) == "ya_estaba"  # noqa: SLF001


def test_el_aria_label_no_sirve_para_distinguir_las_opciones() -> None:
    # Las DOS tarjetas llevan aria-label="borrowed-account": es el nombre del
    # GRUPO. Nombrarlo en un comentario o un docstring esta bien -explica la
    # trampa-; usarlo como selector marca la opcion equivocada.
    assert HTML_REAL_RADIOGRUPO.count('aria-label="borrowed-account"') == 2

    arbol = ast.parse((RAIZ / "automation" / "base_site.py").read_text(encoding="utf-8"))
    docstrings = {
        id(n.body[0].value)
        for n in ast.walk(arbol)
        if isinstance(n, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
        and n.body
        and isinstance(n.body[0], ast.Expr)
        and isinstance(n.body[0].value, ast.Constant)
        and isinstance(n.body[0].value.value, str)
    }
    usados = [
        n.value
        for n in ast.walk(arbol)
        if isinstance(n, ast.Constant)
        and isinstance(n.value, str)
        and id(n) not in docstrings
        and "borrowed-account" in n.value
    ]
    assert usados == [], f"ese aria-label no puede usarse para elegir: {usados}"


class _Sitio(BaseSite):
    def execute(self, *args, **kwargs):  # pragma: no cover - abstracto
        raise NotImplementedError

    def __init__(self, estados: list[dict]) -> None:
        self._estados = list(estados)
        self.clicks: list[str] = []
        self.progreso: list[str] = []
        self.anotaciones: list[tuple[str, dict]] = []
        self.esperas = 0

    def _record_timeline_event(self, evento: str, **detalles) -> None:
        self.anotaciones.append((evento, detalles))

    # --- lo que el metodo necesita de su alrededor -------------------------
    def _leer_estado_de_cuenta(self, _root) -> dict:
        return self._estados.pop(0) if len(self._estados) > 1 else self._estados[0]

    def _localizar_control_de_cuenta(self, _root):
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


def test_lo_que_se_leyo_queda_anotado_para_poder_diagnosticarlo() -> None:
    # Sin esos datos no hay forma de saber, desde fuera, si el estado se leyo
    # mal o si el control no respondio.
    sitio = _Sitio([{"encontrado": True, "prestada": False, "aria": "true", "modo": "switch"}])

    sitio._asegurar_cuenta_prestada(_Raiz())  # noqa: SLF001

    eventos = [nombre for nombre, _ in sitio.anotaciones]
    assert "cuenta_en_propia_detectada" in eventos
    assert "cuenta_prestada_no_confirmada" in eventos
    detalle = dict(sitio.anotaciones)["cuenta_prestada_no_confirmada"]
    assert detalle["antes"]["modo"] == "switch"
    assert detalle["antes"]["aria"] == "true"


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


def test_si_el_switch_no_responde_la_corrida_sigue() -> None:
    """Un paso de conveniencia no puede ser la causa de que una corrida muera.

    La primera version lanzaba aqui, y eso convirtio en fallo seguro un flujo
    que antes funcionaba sin tocar el selector: paso de verdad en paripe.io el
    23/10. Si la lectura del estado esta equivocada, lanzar mata una corrida
    buena; si es correcta, el sitio dara su propio error mas adelante, que es
    informacion real.
    """

    sitio = _Sitio([{"encontrado": True, "prestada": False, "aria": "true"}])

    assert sitio._asegurar_cuenta_prestada(_Raiz()) == "no_confirmado"  # noqa: SLF001


def test_el_estado_no_se_decide_por_aria_checked() -> None:
    # En el panel real, prestada activa == aria-checked "false". Si alguien
    # "simplifica" esto leyendo el aria, invierte el comportamiento.
    fuente = (RAIZ / "automation" / "base_site.py").read_text(encoding="utf-8")
    js = re.search(r'_JS_ESTADO_DE_CUENTA = r"""(.*?)"""', fuente, re.S).group(1)
    decision = js[js.index("const activa") : js.rindex("return {")]
    assert "aria-checked" not in decision or "lado.getAttribute" in decision
    assert "disabled" in decision, "el lado activo se reconoce porque esta deshabilitado"
    assert "text-primary" in decision, "y porque lleva la clase de acento"


def test_el_html_real_del_panel_sigue_encajando_con_lo_que_se_busca() -> None:
    # Guardia barata: si el sitio renombra las etiquetas, esto salta antes de
    # que una corrida se quede en cuenta propia sin avisar.
    assert re.search(BaseSite._CUENTA_PRESTADA_RE, HTML_REAL_PRESTADA, re.I)  # noqa: SLF001
    assert re.search(BaseSite._CUENTA_PROPIA_RE, HTML_REAL_PRESTADA, re.I)  # noqa: SLF001
    assert 'role="switch"' in HTML_REAL_PRESTADA
