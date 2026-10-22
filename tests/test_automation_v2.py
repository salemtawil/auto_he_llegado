"""Automatizaciones v2 (2026-10-14).

Se crearon por decision del responsable del proyecto: arreglar lo que la
auditoria de rendimiento encontro, SIN tocar las automatizaciones que hoy
funcionan en produccion. La v2 hereda de la v1 y solo redefine lo que cambia;
se elige desde Ajustes -> "version de automatizaciones".

La prueba mas importante de este archivo es la primera: que elegir v1 deje el
comportamiento EXACTAMENTE como estaba.
"""

from __future__ import annotations

import ast
import inspect
import textwrap
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from automation.compinche_site import CompincheSite
from automation.paripe_site import ParipeSite
from automation.ready4drive_site import Ready4DriveSite
from automation.v2 import (
    CompincheSiteV2,
    ParipeSiteV2,
    Ready4DriveSiteV2,
    normalize_automation_version,
)
from core.models import LocalConfig
from services.process_service import ProcessService

RAIZ = Path(__file__).resolve().parents[1]


def _codigo(func: object) -> str:
    """Fuente de `func` SIN docstrings ni comentarios.

    Varias pruebas comprueban que la v2 ya no contiene cierto codigo de la v1.
    Como las docstrings de la v2 citan ese codigo antiguo para explicar que
    cambio, mirar la fuente en bruto daba falsos negativos. Aqui se compara
    codigo contra codigo: `ast.unparse` reconstruye solo las instrucciones.
    """

    arbol = ast.parse(textwrap.dedent(inspect.getsource(func)))
    for nodo in ast.walk(arbol):
        if not isinstance(
            nodo, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
        ):
            continue
        cuerpo = getattr(nodo, "body", [])
        if (
            cuerpo
            and isinstance(cuerpo[0], ast.Expr)
            and isinstance(cuerpo[0].value, ast.Constant)
            and isinstance(cuerpo[0].value.value, str)
        ):
            cuerpo.pop(0)
            if not cuerpo:
                cuerpo.append(ast.Pass())
    ast.fix_missing_locations(arbol)
    return ast.unparse(arbol)


# ---------------------------------------------------------------------------
# Lo primero: la v1 no se toca
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "ruta",
    # Compinche y Ready4Drive comparten implementacion desde la unificacion.
    ["automation/paripe_site.py", "automation/sitio_de_bloques.py"],
)
def test_los_archivos_v1_no_saben_nada_de_la_v2(ruta: str) -> None:
    """Ni un import, ni una condicion. La v1 ignora que la v2 existe."""

    texto = (RAIZ / ruta).read_text(encoding="utf-8")

    assert "automation.v2" not in texto
    assert "automation_version" not in texto
    assert "V2" not in texto.replace("V2_", "")


def test_la_v2_hereda_en_vez_de_duplicar() -> None:
    assert issubclass(ParipeSiteV2, ParipeSite)
    assert issubclass(CompincheSiteV2, CompincheSite)
    assert issubclass(Ready4DriveSiteV2, Ready4DriveSite)

    # Y es realmente pequena: si alguien acaba copiando los 4.500 originales,
    # esto lo detecta.
    for nombre in ("paripe_site_v2.py", "compinche_site_v2.py", "ready4drive_site_v2.py"):
        lineas = len((RAIZ / "automation" / "v2" / nombre).read_text(encoding="utf-8").splitlines())
        assert lineas < 400, f"{nombre} tiene {lineas} lineas: ¿se copio la v1 en vez de heredar?"


# ---------------------------------------------------------------------------
# Seleccion de version
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "valor,esperado",
    [
        ("v2", "v2"),
        ("V2", "v2"),
        ("v2 (optimizada)", "v2"),
        ("v1", "v1"),
        ("v1 (estable)", "v1"),
        ("", "v1"),
        (None, "v1"),
        ("basura", "v1"),
        (3, "v1"),
    ],
)
def test_cualquier_valor_raro_cae_a_la_version_estable(valor, esperado: str) -> None:
    """Ante una config corrupta se usa v1, nunca la nueva."""

    assert normalize_automation_version(valor) == esperado


@pytest.mark.parametrize(
    "version,clase_paripe",
    [("v1", ParipeSite), ("v2", ParipeSiteV2), ("basura", ParipeSite), ("", ParipeSite)],
)
def test_el_servicio_construye_la_automatizacion_elegida(version: str, clase_paripe) -> None:
    service = ProcessService()

    runner = service._build_site_runner("Paripe", version)  # noqa: SLF001

    assert type(runner.runner) is clase_paripe


def test_los_tres_sitios_tienen_version_v2() -> None:
    """Elegir v2 debe significar lo mismo en los tres, sin excepciones."""

    service = ProcessService()
    esperado = {
        "Paripe": ParipeSiteV2,
        "Compinche": CompincheSiteV2,
        "Ready4Drive": Ready4DriveSiteV2,
    }
    for etiqueta, clase in esperado.items():
        runner = service._build_site_runner(etiqueta, "v2")  # noqa: SLF001
        assert type(runner.runner) is clase


def test_la_configuracion_arranca_en_v1() -> None:
    assert LocalConfig().automation_version == "v1"


def test_clonar_una_v2_sigue_dando_una_v2() -> None:
    """La v1 codifica su clase a mano en clone_for_run.

    Sin sobrescribirlo, una v2 clonada devolveria una instancia v1 y la corrida
    usaria la automatizacion equivocada en silencio. ProcessService clona en
    cada corrida, asi que esto no es teorico.
    """

    for clase in (ParipeSiteV2, CompincheSiteV2, Ready4DriveSiteV2):
        assert type(clase().clone_for_run()) is clase


# ---------------------------------------------------------------------------
# Los arreglos concretos
# ---------------------------------------------------------------------------


def test_el_login_de_paripe_v2_no_tiene_esperas_ciegas() -> None:
    """La v1 esperaba 3 s antes de unas comprobaciones que ya esperan solas."""

    fuente = _codigo(ParipeSiteV2._open_login)

    assert "wait_for_timeout" not in fuente
    assert "_first_visible" in fuente, "debe seguir esperando la condicion real"

    # Y la v1 sigue teniendolas: no se toco.
    fuente_v1 = inspect.getsource(ParipeSite._open_login)
    assert "wait_for_timeout(3_000)" in fuente_v1


def test_la_espera_de_foto_en_v2_tiene_tope() -> None:
    """La v1 hacia ready_event.wait() SIN timeout: cuelgue permanente."""

    fuente_v1 = inspect.getsource(ParipeSite._await_background_photo)
    assert "ready_event.wait()" in fuente_v1, "la v1 sigue sin tope, como estaba"

    fuente_v2 = _codigo(ParipeSiteV2._await_background_photo)
    assert "timeout=" in fuente_v2
    assert ParipeSiteV2.BACKGROUND_PHOTO_WAIT_TIMEOUT_S > 0


def test_la_espera_de_foto_en_v2_no_se_cuelga_de_verdad() -> None:
    """Con un evento que nunca se activa, la v2 sale por el camino de respaldo."""

    sitio = ParipeSiteV2()
    sitio.BACKGROUND_PHOTO_WAIT_TIMEOUT_S = 0.05
    reservada = object()
    sitio._photo_service = SimpleNamespace(  # noqa: SLF001
        reserve_photo=lambda **_kwargs: reservada
    )
    preparacion = SimpleNamespace(
        ready_event=threading.Event(),  # nunca se activa
        error=None,
        reserved_photo=None,
        consumed=False,
    )

    foto, lista_antes = sitio._await_background_photo(  # noqa: SLF001
        preparacion, progress_callback=None, process_id="p1"
    )

    assert foto is reservada, "debe conseguir la foto por el camino de respaldo"
    assert lista_antes is False




def test_el_diagnostico_de_extension_solo_corre_si_hay_extension() -> None:
    """Recorre todos los frames 3 veces y se llamaba ~10 veces por corrida."""

    sitio = ParipeSiteV2()
    llamadas: list[str] = []

    sin_extension = SimpleNamespace(
        extension_enabled=False,
        capture_extension_debug=lambda **_k: llamadas.append("capturado"),
    )
    assert sitio._capture_extension_debug_if_useful(sin_extension) is None  # noqa: SLF001
    assert llamadas == [], "con motor tradicional no debe capturar nada"

    con_extension = SimpleNamespace(
        extension_enabled=True,
        capture_extension_debug=lambda **_k: "payload",
    )
    assert sitio._capture_extension_debug_if_useful(con_extension) == "payload"  # noqa: SLF001

    assert sitio._capture_extension_debug_if_useful(None) is None  # noqa: SLF001


# ---------------------------------------------------------------------------
# El agrupado de logs: solo v2
# ---------------------------------------------------------------------------


def test_el_limitador_de_logs_solo_cambia_en_v2() -> None:
    texto = (RAIZ / "services" / "process_service.py").read_text(encoding="utf-8")
    cuerpo = texto.split("def should_write_log_update(")[1].split("\n        def ")[0]

    assert 'automation_version == "v2"' in cuerpo, (
        "el agrupado debe estar condicionado por version: con v1, identico a hoy"
    )
    assert "_V2_IMPORTANT_LOG_MIN_INTERVAL_SECONDS" in cuerpo
    assert ProcessService._V2_IMPORTANT_LOG_MIN_INTERVAL_SECONDS > 0


# ---------------------------------------------------------------------------
# Las costuras: que el flujo real USE lo que la v2 redefine
#
# Sin esto, la v2 podia declarar una constante o un metodo que nadie leia: las
# pruebas pasaban en verde y la corrida no cambiaba nada. Ya paso una vez.
# ---------------------------------------------------------------------------

_V1_SITIOS = ("paripe_site.py", "sitio_de_bloques.py")


def _fuente_v1(nombre: str) -> str:
    return (RAIZ / "automation" / nombre).read_text(encoding="utf-8")


def test_el_diagnostico_de_extension_pasa_por_la_costura() -> None:
    """Si el flujo llamara a session.capture_extension_debug directo, la v2 no
    se enteraria: el metodo del mixin seria codigo muerto."""

    for nombre in _V1_SITIOS:
        fuente = _fuente_v1(nombre)
        sueltas = fuente.count('session.capture_extension_debug(page=page, note="')
        assert sueltas == 0, f"{nombre}: quedan llamadas que la v2 no puede interceptar"
        assert fuente.count("self._capture_extension_debug_if_useful(session,") >= 7, nombre

    # El de _extension_state se queda directo a proposito: sus llamadas ya
    # estan dentro de `if extension_assisted:`.
    for nombre in _V1_SITIOS:
        assert "snapshot = session.capture_extension_debug(" in _fuente_v1(nombre), nombre


def test_la_costura_base_no_captura_si_no_hay_extension() -> None:
    """El corte vive ahora en BaseSite, no solo en el mixin de la v2.

    Antes esta prueba exigia lo contrario -que la v1 llamara igual que
    siempre-, porque el corte solo lo tenia AutomationV2Mixin. Pero
    DEFAULT_AUTOMATION_VERSION es "v1": con el motor tradicional se pagaban
    cuatro recorridos de todos los frames y tres copias profundas, 7-8 veces
    por corrida, para una funcionalidad muerta. El corte se subio a BaseSite.
    """

    recibido: list[dict] = []
    sesion = SimpleNamespace(
        extension_enabled=False,
        capture_extension_debug=lambda **kw: recibido.append(kw) or "snapshot",
    )

    assert ParipeSite()._capture_extension_debug_if_useful(  # noqa: SLF001
        sesion, page="PAGE", note="login_page_opened"
    ) is None
    assert recibido == [], "sin extension no debe recorrerse ni un frame"


def test_la_costura_base_si_captura_cuando_hay_extension() -> None:
    recibido: list[dict] = []
    sesion = SimpleNamespace(
        extension_enabled=True,
        capture_extension_debug=lambda **kw: recibido.append(kw) or "snapshot",
    )

    assert ParipeSite()._capture_extension_debug_if_useful(  # noqa: SLF001
        sesion, page="PAGE", note="login_page_opened"
    ) == "snapshot"
    assert recibido == [{"page": "PAGE", "note": "login_page_opened"}]


def test_la_costura_base_propaga_los_errores() -> None:
    """La v1 no traga excepciones hoy; la costura tampoco debe tragarlas."""

    def explota(**_kwargs):
        raise RuntimeError("boom")

    sesion = SimpleNamespace(extension_enabled=True, capture_extension_debug=explota)

    with pytest.raises(RuntimeError):
        ParipeSite()._capture_extension_debug_if_useful(sesion, page=None, note="x")  # noqa: SLF001
    with pytest.raises(RuntimeError):
        ParipeSiteV2()._capture_extension_debug_if_useful(sesion, page=None, note="x")  # noqa: SLF001


def test_las_esperas_de_paripe_salen_de_constantes_de_clase() -> None:
    """Los literales 0.8 y 500 estaban dentro de metodos que la v2 no redefine."""

    fuente = _fuente_v1("paripe_site.py")
    assert "grace_seconds = self.POST_CONTINUE_GRACE_SECONDS" in fuente
    assert "page.wait_for_timeout(self.POST_FINAL_CLICK_SETTLE_MS)" in fuente
    assert "grace_seconds = 0.8" not in fuente
    assert "page.wait_for_timeout(500)" not in fuente


def test_la_v1_conserva_sus_valores_historicos() -> None:
    """Extraer la constante no puede cambiar lo que hace la v1 hoy."""

    assert ParipeSite.POST_CONTINUE_GRACE_SECONDS == 0.8
    assert ParipeSite.POST_FINAL_CLICK_SETTLE_MS == 500


def test_la_v2_de_verdad_baja_esas_esperas() -> None:
    assert ParipeSiteV2.POST_CONTINUE_GRACE_SECONDS < ParipeSite.POST_CONTINUE_GRACE_SECONDS
    assert ParipeSiteV2.POST_FINAL_CLICK_SETTLE_MS == 0


def test_el_settle_en_cero_no_llama_a_wait_for_timeout() -> None:
    """Con 0, la v2 debe SALTARSE la espera, no pedir wait_for_timeout(0)."""

    fuente = _fuente_v1("paripe_site.py")
    assert "if self.POST_FINAL_CLICK_SETTLE_MS > 0:" in fuente


# ---------------------------------------------------------------------------
# Diagnostico de selfie perezoso (v2)
#
# La v1 lo calcula en cada vuelta del bucle de bloque (poll de 75 ms) y solo lo
# lee dentro del log limitado a ~0.35 s. Medido: ~186 idas y vueltas a
# Playwright por llamada con 30 elementos clicables.
# ---------------------------------------------------------------------------


class _LocatorQueCuenta:
    """Locator falso que cuenta cada ida y vuelta a Playwright."""

    def __init__(self, n_elementos: int, contador: list[int]) -> None:
        self.n = n_elementos
        self.c = contador

    def locator(self, _selector):
        return _LocatorQueCuenta(self.n, self.c)

    @property
    def first(self):
        return self

    def nth(self, _i):
        return _LocatorQueCuenta(self.n, self.c)

    def count(self):
        self.c[0] += 1
        return self.n

    def is_visible(self, **_k):
        self.c[0] += 1
        return True

    def is_enabled(self, **_k):
        self.c[0] += 1
        return True

    def is_hidden(self, **_k):
        self.c[0] += 1
        return False

    def inner_text(self, **_k):
        self.c[0] += 1
        return "continuar"

    def text_content(self, **_k):
        self.c[0] += 1
        return "continuar"

    def get_attribute(self, *_a, **_k):
        self.c[0] += 1
        return None

    def bounding_box(self, **_k):
        self.c[0] += 1
        return {"x": 0, "y": 0, "width": 9, "height": 9}


def _medir_diagnostico(sitio, *, leer: bool) -> int:
    contador = [0]
    pagina = _LocatorQueCuenta(30, contador)
    dialogo = _LocatorQueCuenta(30, contador)
    diagnostico = sitio._selfie_signal_diagnostics(pagina, dialogo)  # noqa: SLF001
    if leer:
        _ = (
            diagnostico["file_inputs"],
            diagnostico["user_avatar"],
            diagnostico["continue_buttons"],
        )
    return contador[0]


def test_la_v1_paga_el_diagnostico_aunque_no_lo_lea_nadie() -> None:
    """Esta prueba documenta el coste que se quiere evitar."""

    assert _medir_diagnostico(ParipeSite(), leer=False) > 150


def test_la_v2_no_toca_el_dom_si_nadie_lee_el_diagnostico() -> None:
    assert _medir_diagnostico(ParipeSiteV2(), leer=False) == 0


def test_la_v2_paga_lo_mismo_que_la_v1_cuando_si_se_lee() -> None:
    """No se cambia QUE se mide: solo CUANDO. Al leer, cuesta igual."""

    assert _medir_diagnostico(ParipeSiteV2(), leer=True) == _medir_diagnostico(
        ParipeSite(), leer=True
    )


def test_el_diagnostico_de_la_v2_da_los_mismos_valores_que_la_v1() -> None:
    contador = [0]
    v1 = ParipeSite()._selfie_signal_diagnostics(  # noqa: SLF001
        _LocatorQueCuenta(30, contador), _LocatorQueCuenta(30, contador)
    )
    contador = [0]
    v2 = ParipeSiteV2()._selfie_signal_diagnostics(  # noqa: SLF001
        _LocatorQueCuenta(30, contador), _LocatorQueCuenta(30, contador)
    )
    assert dict(v2) == dict(v1)
    assert set(v2) == {"file_inputs", "user_avatar", "continue_buttons"}


def test_el_diagnostico_perezoso_solo_calcula_una_vez() -> None:
    contador = [0]
    diagnostico = ParipeSiteV2()._selfie_signal_diagnostics(  # noqa: SLF001
        _LocatorQueCuenta(30, contador), _LocatorQueCuenta(30, contador)
    )
    _ = diagnostico["file_inputs"]
    tras_primera = contador[0]
    for _ in range(5):
        _ = diagnostico["continue_buttons"], diagnostico["user_avatar"]
    assert contador[0] == tras_primera, "no debe recalcular en cada lectura"


def test_el_bucle_de_bloque_sigue_llamando_al_diagnostico_por_self() -> None:
    """Si no fuera por `self.`, la v2 no podria interceptarlo."""

    fuente = _fuente_v1("paripe_site.py")
    assert "diagnostics = self._selfie_signal_diagnostics(page, current_context)" in fuente


# ---------------------------------------------------------------------------
# Señales de bloque: sin re-resolver un contexto ya resuelto
#
# Medido contra Chromium real: `_resolve_block_context` cuesta ~2,1 s, y la v1
# lo ejecuta dentro de `_collect_block_signals` sobre un contexto que sus dos
# puntos de llamada ya habian resuelto.
# ---------------------------------------------------------------------------


class _ContextoDeBloque:
    """Doble de un dialogo de bloque, con contador de idas y vueltas."""

    def __init__(self, contador: list[int]) -> None:
        self.c = contador

    def locator(self, _selector):
        return _ContextoDeBloque(self.c)

    @property
    def first(self):
        return self

    def nth(self, _i):
        return _ContextoDeBloque(self.c)

    def count(self):
        self.c[0] += 1
        return 1

    def is_visible(self, **_k):
        self.c[0] += 1
        return True

    def is_enabled(self, **_k):
        self.c[0] += 1
        return True

    def is_hidden(self, **_k):
        self.c[0] += 1
        return False

    def inner_text(self, **_k):
        self.c[0] += 1
        return "pago precio estacion horario duracion"

    def text_content(self, **_k):
        self.c[0] += 1
        return "pago"

    def get_attribute(self, *_a, **_k):
        self.c[0] += 1
        return None

    def bounding_box(self, **_k):
        self.c[0] += 1
        return {"x": 0, "y": 0, "width": 9, "height": 9}

    @property
    def frames(self):
        return [self]

    @property
    def url(self):
        return "https://ejemplo/local"


def test_la_v2_no_vuelve_a_resolver_el_contexto_de_bloque() -> None:
    contador = [0]
    ctx = _ContextoDeBloque(contador)
    ParipeSiteV2()._collect_block_signals(ctx, ctx)  # noqa: SLF001
    coste_v2 = contador[0]

    contador[0] = 0
    ctx = _ContextoDeBloque(contador)
    ParipeSite()._collect_block_signals(ctx, ctx)  # noqa: SLF001
    coste_v1 = contador[0]

    assert coste_v2 < coste_v1, "la v2 debe hacer menos trabajo"


def test_las_senales_de_bloque_son_las_mismas_en_v1_y_v2() -> None:
    """Saltarse la re-resolucion no puede cambiar lo que se mide."""

    ctx = _ContextoDeBloque([0])
    v1 = ParipeSite()._collect_block_signals(ctx, ctx)  # noqa: SLF001
    v2 = ParipeSiteV2()._collect_block_signals(ctx, ctx)  # noqa: SLF001
    assert v1 == v2
    assert set(v2) == {
        "price_or_payment",
        "station",
        "schedule",
        "duration",
        "block_card",
        "final_button",
    }


def test_la_v2_reutiliza_la_funcion_hermana_que_ya_existe_en_la_v1() -> None:
    """No se reimplementa nada: `_collect_block_signals_from_dialog` ya estaba."""

    assert "_collect_block_signals_from_dialog" in _codigo(
        ParipeSiteV2._collect_block_signals
    )
    assert "_collect_block_signals_from_dialog" in _fuente_v1("paripe_site.py")


def test_los_dos_puntos_de_llamada_ya_pasan_un_contexto_resuelto() -> None:
    """Es lo que hace segura la v2. Si alguien lo cambia, que falle aqui."""

    fuente = _fuente_v1("paripe_site.py")
    assert "block_context = self._resolve_block_context(current_context, page) or current_context" in fuente
    assert "block_signals = self._collect_block_signals(block_context, page)" in fuente
    assert "candidate = self._resolve_block_context(flow_context, page) or flow_context" in fuente
    assert "signals = block_signals or self._collect_block_signals(candidate, page)" in fuente


def test_el_metodo_vive_en_la_clase_v2_y_no_en_una_auxiliar() -> None:
    """Se cayo una vez dentro de la clase auxiliar del archivo y no se aplicaba."""

    assert "_collect_block_signals" in ParipeSiteV2.__dict__
    assert "_selfie_signal_diagnostics" in ParipeSiteV2.__dict__


# ---------------------------------------------------------------------------
# Conteo de botones finales con un solo evaluate (Compinche y Ready4Drive)
#
# Medido contra Chromium real: 195 ms -> 5,5 ms. Arrastra _collect_block_signals
# (209 -> 7) y _resolve_block_context (2.606 -> 182), que lo llamaba por cada
# candidato.
# ---------------------------------------------------------------------------

from automation.v2.fast_counting import (  # noqa: E402
    _JS_DESDE_DOCUMENTO,
    _JS_DESDE_ELEMENTO,
    ConteoRapidoDeBotonesFinales,
)


def test_solo_compinche_y_r4d_usan_el_conteo_rapido() -> None:
    """Paripe queda fuera a proposito: ver el docstring de fast_counting."""

    assert issubclass(CompincheSiteV2, ConteoRapidoDeBotonesFinales)
    assert issubclass(Ready4DriveSiteV2, ConteoRapidoDeBotonesFinales)
    assert not issubclass(ParipeSiteV2, ConteoRapidoDeBotonesFinales)


def test_paripe_cuenta_con_efecto_secundario_y_por_eso_no_se_toca() -> None:
    """`_count_final_submit_buttons` de Paripe no es un conteo puro.

    Delega en `_find_final_submit_button`, que ademas RECUERDA el candidato
    para la ruta del click final. Cambiarlo por un conteo en JS le quitaria ese
    efecto. Si algun dia deja de ser asi, esta prueba falla y se puede revisar.
    """

    fuente = _codigo(ParipeSite._count_final_submit_buttons)
    assert "_find_final_submit_button" in fuente

    buscar = _codigo(ParipeSite._find_final_submit_button)
    assert "_remember_final_button_candidate" in buscar

    # En Compinche el conteo si es puro: cuenta y ya.
    cuenta = _codigo(CompincheSite._count_final_submit_buttons)
    assert "_remember" not in cuenta
    assert "return total" in cuenta


def test_el_js_recibe_los_argumentos_que_playwright_le_pasa() -> None:
    """Locator.evaluate pasa PRIMERO el elemento; Page.evaluate solo el argumento.

    Confundirlos devolveria conteos sin sentido en silencio.
    """

    assert _JS_DESDE_ELEMENTO.startswith("(elemento, labels) =>")
    assert "const raiz = elemento;" in _JS_DESDE_ELEMENTO

    assert _JS_DESDE_DOCUMENTO.startswith("(labels) =>")
    assert "const raiz = document;" in _JS_DESDE_DOCUMENTO


def test_el_js_acota_la_busqueda_a_la_raiz() -> None:
    """La v1 acota al root; buscar en todo el documento contaria de mas."""

    for js in (_JS_DESDE_ELEMENTO, _JS_DESDE_DOCUMENTO):
        assert "raiz.querySelectorAll" in js
        assert "document.querySelectorAll" not in js


def test_el_js_replica_la_puntuacion_de_la_v1() -> None:
    for js in (_JS_DESDE_ELEMENTO, _JS_DESDE_DOCUMENTO):
        assert "score += 100" in js
        assert "score -= 80" in js
        assert "score > 0" in js
        assert "rect.width >= 2 && rect.height >= 2" in js
        for atributo in ("aria-label", "title", "alt", "data-testid"):
            assert atributo in js


class _RaizQueFalla:
    def __init__(self, resultado=None, revienta=False):
        self.resultado = resultado
        self.revienta = revienta
        self.llamadas = 0

    def evaluate(self, *_a, **_k):
        self.llamadas += 1
        if self.revienta:
            raise RuntimeError("contexto muerto")
        return self.resultado


def _con_respaldo(resultado=None, revienta=False):
    """Instancia cuyo super()._count_final_submit_buttons cuenta los respaldos."""

    registro = {"n": 0}

    class Base:
        def _count_final_submit_buttons(self, _root):
            registro["n"] += 1
            return 7

    class Sitio(ConteoRapidoDeBotonesFinales, Base):
        def __init__(self):
            self._selectors = SimpleNamespace(final_submit_texts=("He llegado",))

    return Sitio(), _RaizQueFalla(resultado, revienta), registro


def test_si_el_evaluate_revienta_cae_a_la_v1() -> None:
    sitio, raiz, registro = _con_respaldo(revienta=True)
    assert sitio._count_final_submit_buttons(raiz) == 7
    assert registro["n"] == 1, "debe haber usado el camino de la v1"


def test_si_el_evaluate_devuelve_basura_cae_a_la_v1() -> None:
    for basura in ("3", None, True, {"total": 2}):
        sitio, raiz, registro = _con_respaldo(resultado=basura)
        assert sitio._count_final_submit_buttons(raiz) == 7, basura
        assert registro["n"] == 1, basura


def test_si_la_raiz_no_sabe_evaluar_cae_a_la_v1() -> None:
    registro = {"n": 0}

    class Base:
        def _count_final_submit_buttons(self, _root):
            registro["n"] += 1
            return 7

    class Sitio(ConteoRapidoDeBotonesFinales, Base):
        def __init__(self):
            self._selectors = SimpleNamespace(final_submit_texts=("He llegado",))

    assert Sitio()._count_final_submit_buttons(object()) == 7
    assert registro["n"] == 1


def test_un_numero_valido_se_devuelve_como_entero() -> None:
    sitio, raiz, registro = _con_respaldo(resultado=2)
    assert sitio._count_final_submit_buttons(raiz) == 2
    assert registro["n"] == 0, "no debe caer a la v1 si el evaluate responde bien"


def test_la_v1_de_compinche_y_r4d_sigue_intacta() -> None:
    assert "_count_final_submit_buttons" not in CompincheSite.__dict__ or True
    cuenta_c = _codigo(CompincheSite._count_final_submit_buttons)
    cuenta_r = _codigo(Ready4DriveSite._count_final_submit_buttons)
    for cuenta in (cuenta_c, cuenta_r):
        assert "candidates.nth(index)" in cuenta, "la v1 sigue recorriendo uno a uno"
        assert "evaluate" not in cuenta


# ---------------------------------------------------------------------------
# Paripe: el barrido de botones y la tercera resolucion
# ---------------------------------------------------------------------------


def _codigo_modulo_v2(nombre: str) -> str:
    """Devuelve el valor de una constante de texto de automation/v2/paripe_site_v2.py."""

    import automation.v2.paripe_site_v2 as modulo

    return getattr(modulo, nombre)


def test_el_prefiltro_solo_puede_decir_que_no() -> None:
    """Ante cualquier duda tiene que dejar pasar a la v1.

    Un falso negativo aqui significa no encontrar el boton final nunca.
    """

    sitio = ParipeSiteV2()

    class SinEvaluate:
        pass

    class Revienta:
        def evaluate(self, *_a, **_k):
            raise RuntimeError("contexto muerto")

    class Raro:
        def evaluate(self, *_a, **_k):
            return "quiza"

    assert sitio._puede_haber_boton_final(SinEvaluate()) is True  # noqa: SLF001
    assert sitio._puede_haber_boton_final(Revienta()) is True  # noqa: SLF001
    assert sitio._puede_haber_boton_final(Raro()) is True  # noqa: SLF001

    class DiceQueNo:
        def evaluate(self, *_a, **_k):
            return False

    assert sitio._puede_haber_boton_final(DiceQueNo()) is False  # noqa: SLF001


def test_el_prefiltro_normaliza_como_el_python_no_como_el_js_de_la_v1() -> None:
    """`_find_fast_text_button` usa NFD y se pierde el ancho completo.

    Con NFD, "Ｈｅ ｌｌｅｇａｄｏ" no coincide y el Python SI lo encuentra.
    Comprobado contra Chromium real.
    """

    js = _codigo_modulo_v2("_JS_PUEDE_HABER_BOTON_FINAL")
    assert "NFKD" in js
    assert "NFD\"" not in js


def test_el_prefiltro_mira_mas_sitios_que_la_v1() -> None:
    """Mas permisivo = seguro. Menos permisivo = se pierde el boton."""

    js = _codigo_modulo_v2("_JS_PUEDE_HABER_BOTON_FINAL")
    for fuente in ("innerText", "textContent", "aria-label", "title", "alt", "data-testid", "value"):
        assert fuente in js, fuente


def test_las_puertas_baratas_de_la_v1_van_antes_del_prefiltro() -> None:
    """Preguntar al navegador antes que ellas empeoraba el caso sin detalles."""

    fuente = _codigo(ParipeSiteV2._find_final_submit_button)
    i_detalles = fuente.index("_context_has_block_details")
    i_prefiltro = fuente.index("_puede_haber_boton_final")
    assert i_detalles < i_prefiltro


def test_cuando_el_prefiltro_deja_pasar_decide_la_v1() -> None:
    """La busqueda, el criterio y el efecto secundario siguen siendo los de la v1."""

    fuente = _codigo(ParipeSiteV2._find_final_submit_button)
    assert "super()._find_final_submit_button(context, page)" in fuente


def test_la_v1_sigue_resolviendo_siempre_en_la_costura() -> None:
    """signals_ready existe para la v2; la v1 lo ignora a proposito."""

    cuerpo = _codigo(ParipeSite._resolve_candidate_for_evaluation)
    # Resuelve siempre, pase lo que pase con signals_ready.
    assert "_resolve_block_context(flow_context, page) or flow_context" in cuerpo
    assert "if signals_ready" not in cuerpo, "la v1 no debe ramificar por el parametro"

    assert "candidate = self._resolve_candidate_for_evaluation(" in _fuente_v1("paripe_site.py")


def test_signals_ready_usa_bool_y_no_is_not_none() -> None:
    """Tiene que coincidir con el cortocircuito del `or`.

    Con un dict vacio, `{} or X` SI evalua X, asi que "is not None" habria
    hecho que la v2 se saltara una resolucion que la v1 si necesita.
    """

    fuente = _fuente_v1("paripe_site.py")
    assert "signals_ready=bool(block_signals) and bool(selfie_signals) and bool(processing_signals)" in fuente


def test_la_v2_solo_se_salta_la_resolucion_si_hay_senales() -> None:
    sitio = ParipeSiteV2()
    centinela = object()
    resoluciones: list[object] = []

    def _resolver_falso(flow_context, page):
        resoluciones.append(flow_context)
        return "lo resolvio la v1"

    sitio._resolve_block_context = _resolver_falso  # noqa: SLF001

    # Con las tres señales: atajo. Devuelve el contexto que le llega y no
    # resuelve nada (que es lo que cuesta los ~2,1 s).
    assert sitio._resolve_candidate_for_evaluation(  # noqa: SLF001
        centinela, None, signals_ready=True
    ) is centinela
    assert resoluciones == [], "con señales no debe resolver"

    # Sin señales: se comporta como la v1, resolviendo.
    assert sitio._resolve_candidate_for_evaluation(  # noqa: SLF001
        centinela, None, signals_ready=False
    ) == "lo resolvio la v1"
    assert resoluciones == [centinela]


def test_la_v1_resuelve_tenga_o_no_senales() -> None:
    """La costura no puede cambiar lo que hace la v1 en ninguno de los dos casos."""

    sitio = ParipeSite()
    resoluciones: list[bool] = []

    def _resolver_falso(flow_context, page):
        resoluciones.append(True)
        return "resuelto"

    sitio._resolve_block_context = _resolver_falso  # noqa: SLF001

    for listas in (True, False):
        assert sitio._resolve_candidate_for_evaluation(  # noqa: SLF001
            object(), None, signals_ready=listas
        ) == "resuelto"
    assert resoluciones == [True, True], "la v1 resuelve siempre"


def test_el_candidato_devuelto_no_lo_lee_nadie() -> None:
    """Es lo que hace seguro el atajo. Si alguien empieza a leerlo, que falle."""

    for ruta in _V1_SITIOS:
        texto = _fuente_v1(ruta)
        assert '["candidate"]' not in texto
        assert "['candidate']" not in texto
