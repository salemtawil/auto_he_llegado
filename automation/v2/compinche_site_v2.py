"""Compinche v2: hereda los arreglos comunes de la v2.

La v1 (`automation/sitio_de_bloques.py`, compartida con el otro sitio
de bloques) NO se toca.

Aqui vivia un arreglo de `_wait_for_uploaded_file_input`, que en la v1 llamaba
a `self._wait_interval(150)` contra una firma de dos parametros obligatorios y
reventaba con TypeError. Ese metodo pertenecia al subsistema de "selfie del
titular" por opcion de la pagina, que el commit 19d51e5 sustituyo por subir la
foto del titular como foto principal y que ya se retiro entero de la v1: sin
metodo base al que corregir, el arreglo sobra.
"""

from __future__ import annotations

from automation.compinche_site import CompincheSite
from automation.v2.fast_counting import ConteoRapidoDeBotonesFinales
from automation.v2.mixins import AutomationV2Mixin


class CompincheSiteV2(AutomationV2Mixin, ConteoRapidoDeBotonesFinales, CompincheSite):
    """Toda la mejora viene de los mixins; no hay nada propio que anadir."""
