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
    ["automation/paripe_site.py", "automation/compinche_site.py", "automation/ready4drive_site.py"],
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


def test_compinche_v2_arregla_el_typeerror() -> None:
    """compinche_site.py:1514 llama _wait_interval con un solo argumento."""

    fuente_v1 = inspect.getsource(CompincheSite._wait_for_uploaded_file_input)
    assert "self._wait_interval(150)" in fuente_v1, "la v1 sigue como estaba"

    fuente_v2 = _codigo(CompincheSiteV2._wait_for_uploaded_file_input)
    assert "self._wait_interval(150)" not in fuente_v2
    assert "_wait_interval(file_input, 150)" in fuente_v2


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

_V1_SITIOS = ("paripe_site.py", "compinche_site.py", "ready4drive_site.py")


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


def test_la_costura_base_llama_igual_que_la_v1() -> None:
    """La v1 no debe cambiar de comportamiento: misma llamada, mismo retorno."""

    sitio = ParipeSite()
    recibido: list[dict] = []
    sesion = SimpleNamespace(
        extension_enabled=False,
        capture_extension_debug=lambda **kw: recibido.append(kw) or "snapshot",
    )

    assert sitio._capture_extension_debug_if_useful(  # noqa: SLF001
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
