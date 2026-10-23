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
from time import monotonic

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
    # Las pruebas no esperan al navegador: la espera se cubre aparte.
    CUENTA_LECTURA_TIMEOUT_MS = 0
    CUENTA_BUSQUEDA_TIMEOUT_MS = 0

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


def _js_del_estado() -> str:
    fuente = (RAIZ / "automation" / "base_site.py").read_text(encoding="utf-8")
    return re.search(r'_JS_ESTADO_DE_CUENTA = r"""(.*?)"""', fuente, re.S).group(1)


def _cuerpo_de_activo(js: str) -> str:
    """El cuerpo de `activo(...)`, que es quien decide si un lado esta puesto."""

    inicio = js.index("const activo = (s) => {")
    fin = js.index("\n        };", inicio)
    return js[inicio:fin]


def test_el_aria_del_switch_no_decide_el_estado() -> None:
    """En el panel real, prestada activa == switch con aria-checked "false".

    Esa inversion es del sitio y puede cambiar sin avisar, asi que el aria del
    SWITCH solo se guarda para el log. Quien decide son las dos etiquetas: de
    ahi sale `activo(...)`, que mira cada lado por separado.
    """

    js = _js_del_estado()
    # El aria del interruptor aparece una sola vez, y es la del campo de log.
    usos = re.findall(r"interruptor\.getAttribute\('aria-checked'\)", js)
    assert len(usos) == 1, usos
    assert "aria: interruptor ? interruptor.getAttribute('aria-checked') : null," in js
    decision = _cuerpo_de_activo(js)
    assert "interruptor" not in decision, "la decision no puede mirar el switch"
    assert "s.off" in decision, "el lado activo se reconoce porque esta deshabilitado"
    assert "s.acento" in decision, "y porque lleva la clase de acento"


def test_sin_senales_el_estado_es_desconocido_y_no_falso() -> None:
    """La trampa que costo una corrida: tratar "no lo se" como "cuenta propia".

    Si ninguna de las dos etiquetas da senales -pasa mientras el panel se
    esta pintando- la respuesta tiene que ser null. Darla por falsa hace
    pulsar a ciegas, y pulsar un selector que ya estaba en prestada lo deja
    en propia: la corrida falla por culpa del arreglo.
    """

    js = _js_del_estado()
    decision = _cuerpo_de_activo(js)
    assert decision.rstrip().endswith("return null;"), decision[-80:]
    # Y la decision combinada nunca convierte un null en false por descarte.
    combinada = js[js.index("let estado = null;") : js.index("return {", js.index("let estado"))]
    assert "p === false && q === null" in combinada
    assert "q === false && p === null" in combinada


def test_el_html_real_del_panel_sigue_encajando_con_lo_que_se_busca() -> None:
    # Guardia barata: si el sitio renombra las etiquetas, esto salta antes de
    # que una corrida se quede en cuenta propia sin avisar.
    assert re.search(BaseSite._CUENTA_PRESTADA_RE, HTML_REAL_PRESTADA, re.I)  # noqa: SLF001
    assert re.search(BaseSite._CUENTA_PROPIA_RE, HTML_REAL_PRESTADA, re.I)  # noqa: SLF001
    assert 'role="switch"' in HTML_REAL_PRESTADA


def test_si_no_se_sabe_en_que_lado_esta_no_se_toca() -> None:
    """Lo mas importante de todo el paso: ante la duda, no tocar.

    Pulsar sin saber puede voltear un selector que ya estaba bien. Es
    exactamente lo que paso en paripe.io el 23/10: el paso pulso, el selector
    acabo en cuenta propia y la corrida murio por un paso de conveniencia.
    """

    sitio = _Sitio([{"encontrado": True, "prestada": None, "aria": "false", "modo": "switch"}])

    assert sitio._asegurar_cuenta_prestada(_Raiz()) == "indeterminado"  # noqa: SLF001
    assert sitio.clicks == []
    eventos = [nombre for nombre, _ in sitio.anotaciones]
    assert "cuenta_estado_indeterminado" in eventos


def test_la_ausencia_del_selector_tambien_queda_anotada() -> None:
    # Desde fuera, "no hay selector en esta pantalla" y "lo hay y no lo vi"
    # se parecen al silencio. Distinguirlas es todo el diagnostico.
    sitio = _Sitio([{"encontrado": False, "motivo": "sin_caja", "modo": "switch"}])

    assert sitio._asegurar_cuenta_prestada(_Raiz()) == "ausente"  # noqa: SLF001
    detalle = dict(sitio.anotaciones)["cuenta_selector_ausente"]
    assert detalle["motivo"] == "sin_caja"


def test_se_espera_a_que_el_panel_termine_de_pintarse() -> None:
    """El panel de Paripe se pinta justo despues de entrar.

    Mirarlo demasiado pronto da las dos etiquetas sin deshabilitar ni pintar,
    es decir, ilegible. Rendirse en la primera lectura es lo que convierte un
    problema de tiempos en una decision equivocada.
    """

    class _SitioLento(_Sitio):
        CUENTA_LECTURA_TIMEOUT_MS = 2_000
        CUENTA_BUSQUEDA_TIMEOUT_MS = 0

    lecturas = [
        {"encontrado": True, "prestada": None, "modo": "switch"},
        {"encontrado": True, "prestada": None, "modo": "switch"},
        {"encontrado": True, "prestada": True, "aria": "false", "modo": "switch"},
    ]
    sitio = _SitioLento(lecturas)

    assert sitio._asegurar_cuenta_prestada(_Raiz()) == "ya_estaba"  # noqa: SLF001
    assert sitio.clicks == []


def test_la_espera_se_rinde_y_devuelve_lo_ultimo_que_vio() -> None:
    class _SitioCorto(_Sitio):
        CUENTA_LECTURA_TIMEOUT_MS = 120
        CUENTA_BUSQUEDA_TIMEOUT_MS = 0

    sitio = _SitioCorto([{"encontrado": True, "prestada": None, "modo": "switch"}])

    assert sitio._asegurar_cuenta_prestada(_Raiz()) == "indeterminado"  # noqa: SLF001


def test_la_radiografia_del_control_llega_al_log_en_una_linea() -> None:
    # Sin ella no hay forma de decidir desde fuera por que no se pudo leer.
    estado = {
        "encontrado": True,
        "prestada": None,
        "modo": "switch",
        "radiografia": {"prestada": {"off": False, "acento": False}, "propia": None},
    }
    detalles = BaseSite._detalles(estado)  # noqa: SLF001

    assert isinstance(detalles["radiografia"], str)
    assert "acento" in detalles["radiografia"]
    assert "\n" not in detalles["radiografia"]


def test_si_el_selector_no_esta_no_se_espera_el_presupuesto_largo() -> None:
    """Este paso esta en el camino del boton de verificacion.

    En la mayoria de pantallas el selector no existe, y gastar ahi los tres
    segundos de la espera larga retrasa el click. La espera larga es para
    cuando el selector YA aparecio pero todavia no se puede leer.
    """

    class _SitioSinSelector(_Sitio):
        CUENTA_BUSQUEDA_TIMEOUT_MS = 150
        CUENTA_LECTURA_TIMEOUT_MS = 10_000

    sitio = _SitioSinSelector([{"encontrado": False, "motivo": "sin_caja"}])
    arranque = monotonic()

    assert sitio._asegurar_cuenta_prestada(_Raiz()) == "ausente"  # noqa: SLF001
    assert monotonic() - arranque < 1.0, "se quedo esperando un selector que no esta"


def test_en_cuanto_aparece_se_le_da_tiempo_a_terminar_de_pintarse() -> None:
    class _SitioQueAparece(_Sitio):
        CUENTA_BUSQUEDA_TIMEOUT_MS = 0
        CUENTA_LECTURA_TIMEOUT_MS = 2_000

    sitio = _SitioQueAparece([
        {"encontrado": True, "prestada": None, "modo": "switch"},
        {"encontrado": True, "prestada": None, "modo": "switch"},
        {"encontrado": True, "prestada": True, "aria": "false", "modo": "switch"},
    ])

    # Aunque el presupuesto de busqueda sea 0, al estar encontrado se sigue
    # mirando con el presupuesto largo hasta poder leerlo.
    assert sitio._asegurar_cuenta_prestada(_Raiz()) == "ya_estaba"  # noqa: SLF001
    assert sitio.clicks == []


def test_paripe_le_da_tiempo_al_panel_y_compinche_no() -> None:
    """Los dos sitios llaman al mismo paso, pero no desde el mismo sitio.

    En Paripe se mira tras entrar, con el click todavia por delante: ahi
    esperar a que el panel aparezca sale barato. En Compinche se mira dentro
    del iframe, justo antes de pulsar "Iniciar verificacion": ahi cada
    milisegundo de espera retrasa el click, y el selector casi nunca esta.
    """

    fuente = (RAIZ / "automation" / "paripe_site.py").read_text(encoding="utf-8")
    assert "busqueda_ms=2_000" in fuente

    bloques = (RAIZ / "automation" / "sitio_de_bloques.py").read_text(encoding="utf-8")
    llamada = bloques[bloques.index("_complete_pre_selfie_account_step") :][:1200]
    assert "busqueda_ms" not in llamada, "el camino del click usa el presupuesto corto"
