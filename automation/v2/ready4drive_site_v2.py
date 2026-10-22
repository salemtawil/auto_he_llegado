"""Ready4Drive v2: hereda los arreglos comunes.

No tiene arreglos propios: el TypeError de `_wait_interval` es exclusivo de
Compinche, y las esperas ciegas son exclusivas de Paripe. Ready4Drive se
beneficia de lo compartido (cierre acotado de la foto en segundo plano,
diagnostico de extension condicionado, agrupado de logs) y existe como clase
propia para que elegir "v2" en la configuracion signifique lo mismo en los tres
sitios, sin excepciones que haya que recordar.

La v1 (`automation/sitio_de_bloques.py`, compartida con el otro sitio
de bloques) NO se toca.
"""

from __future__ import annotations

from automation.ready4drive_site import Ready4DriveSite
from automation.v2.fast_counting import ConteoRapidoDeBotonesFinales
from automation.v2.mixins import AutomationV2Mixin


class Ready4DriveSiteV2(AutomationV2Mixin, ConteoRapidoDeBotonesFinales, Ready4DriveSite):
    pass
