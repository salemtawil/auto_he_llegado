"""Automatizaciones v2: las de siempre, con los arreglos de la auditoria 2026-10-14.

Por que herencia y no una copia
-------------------------------
Las tres automatizaciones v1 suman ~13.000 lineas y Compinche y Ready4Drive son
96% identicas entre si. Copiarlas habria duplicado ese problema y enterrado los
arreglos en medio del ruido.

Heredando, cada clase v2 solo redefine lo que cambia: se ve exactamente que hace
distinto y por que, y la v1 queda intacta, sin tocar un solo caracter.

Como se elige
-------------
`LocalConfig.automation_version` ("v1" por defecto). El selector esta en
Ajustes -> "version de automatizaciones". Con v1, el comportamiento es
BIT A BIT el de siempre, incluidos los arreglos que viven en servicios
compartidos (agrupado de logs), que van condicionados por version.
"""

from automation.v2.compinche_site_v2 import CompincheSiteV2
from automation.v2.paripe_site_v2 import ParipeSiteV2
from automation.v2.ready4drive_site_v2 import Ready4DriveSiteV2

AUTOMATION_VERSIONS = ("v1", "v2")
DEFAULT_AUTOMATION_VERSION = "v1"


def normalize_automation_version(value: object) -> str:
    """Cualquier cosa que no sea exactamente v2 cae a v1.

    Deliberadamente conservador: ante un valor corrupto en la config, se usa la
    version estable, nunca la nueva.
    """

    normalized = str(value or "").strip().lower()
    return "v2" if normalized.startswith("v2") else "v1"


__all__ = [
    "AUTOMATION_VERSIONS",
    "DEFAULT_AUTOMATION_VERSION",
    "CompincheSiteV2",
    "ParipeSiteV2",
    "Ready4DriveSiteV2",
    "normalize_automation_version",
]
