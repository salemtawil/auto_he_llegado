"""El diagnostico de la extension no se paga cuando no hay extension.

`capture_extension_debug` recorre todos los frames cuatro veces y hace tres
copias profundas del resultado; las automatizaciones la llaman 7-8 veces por
corrida. El unico corte que habia (`if snapshot is None`) no se cumplia nunca,
porque el evaluate tiene exito igual sin extension. El corte bueno vivia en el
mixin de la v2, y la version por defecto es la v1.
"""

from __future__ import annotations

from automation.base_site import BaseSite


class _Sitio(BaseSite):
    def execute(self, *args, **kwargs):  # pragma: no cover - abstracto
        raise NotImplementedError

    def __init__(self) -> None:
        pass


class _Sesion:
    def __init__(self, *, extension_enabled: bool) -> None:
        self.extension_enabled = extension_enabled
        self.llamadas = 0

    def capture_extension_debug(self, **kwargs):
        self.llamadas += 1
        return {"marker": None}


def test_sin_extension_no_se_captura_nada():
    sesion = _Sesion(extension_enabled=False)

    assert _Sitio()._capture_extension_debug_if_useful(sesion, page=object()) is None
    assert sesion.llamadas == 0, (
        "con el motor tradicional no debe recorrerse ni un frame por este diagnostico"
    )


def test_con_extension_se_captura_igual_que_antes():
    sesion = _Sesion(extension_enabled=True)

    assert _Sitio()._capture_extension_debug_if_useful(sesion, page=object()) == {"marker": None}
    assert sesion.llamadas == 1


def test_una_sesion_sin_el_metodo_no_revienta():
    class _Vieja:
        extension_enabled = True

    assert _Sitio()._capture_extension_debug_if_useful(_Vieja()) is None


def test_sin_sesion_no_revienta():
    assert _Sitio()._capture_extension_debug_if_useful(None) is None
