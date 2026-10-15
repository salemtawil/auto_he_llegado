"""Compinche v2: arregla un TypeError latente y hereda los arreglos comunes.

La v1 (`automation/compinche_site.py`) NO se toca.
"""

from __future__ import annotations

from time import monotonic

from automation.compinche_site import CompincheSite
from automation.v2.mixins import AutomationV2Mixin


class CompincheSiteV2(AutomationV2Mixin, CompincheSite):
    def _wait_for_uploaded_file_input(self, *, file_input, timeout_ms: int) -> bool:
        """Arregla una llamada que revienta con TypeError.

        La v1 (compinche_site.py:1514) hace `self._wait_interval(150)`, pero la
        firma es `_wait_interval(root, milliseconds)` y es un @staticmethod con
        DOS parametros obligatorios: la llamada pasa 150 como `root` y deja
        `milliseconds` sin valor, asi que lanza TypeError en cuanto se ejecuta.

        Se alcanza al subir la selfie del titular, cuando `set_input_files` no
        se refleja al instante en el DOM. Ready4Drive NO tiene este fallo: es
        solo de Compinche, lo que encaja con que sean clones con deriva.

        Aqui se pasa el root que faltaba.
        """

        deadline = monotonic() + max(timeout_ms, 200) / 1000
        while monotonic() < deadline:
            if self._locator_has_uploaded_file(file_input):
                return True
            self._wait_interval(file_input, 150)
        return self._locator_has_uploaded_file(file_input)
