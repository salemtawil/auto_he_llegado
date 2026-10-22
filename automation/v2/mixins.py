"""Arreglos comunes a las tres automatizaciones v2.

Cada uno documenta QUE hacia la v1, POR QUE es un problema y QUE cambia.
Todos salen de la auditoria de rendimiento del 2026-10-14, verificada contra el
codigo linea a linea.
"""

from __future__ import annotations


class AutomationV2Mixin:
    """Comportamiento compartido por las tres automatizaciones optimizadas."""

    #: Marca de version. La usa ProcessService para decidir, por ejemplo, si
    #: agrupa los updates de log. No cambiar sin mirar process_service.
    AUTOMATION_VERSION = "v2"

    #: Tope para esperar a que el hilo de reserva de foto en segundo plano
    #: termine. La v1 esperaba SIN limite (paripe_site.py:564): si ese hilo se
    #: colgaba, la corrida se quedaba bloqueada para siempre, sin timeout y sin
    #: forma de enterarse. base_site.py ya acotaba lo analogo a 20 s.
    BACKGROUND_PHOTO_WAIT_TIMEOUT_S = 30.0

    def clone_for_run(self):
        """Clona manteniendo la clase v2.

        La v1 codifica su propia clase a mano (`return ParipeSite(...)`), asi
        que heredar sin sobrescribir esto devolveria una instancia v1 y la
        corrida usaria la automatizacion equivocada en silencio.
        """

        return type(self)(selectors=self._selectors)

    # ------------------------------------------------------------------
    # Diagnostico de extension
    # ------------------------------------------------------------------

    # El corte por `extension_enabled` que vivia aqui se subio a BaseSite: la
    # v1 es la que corre de verdad y era justo la que no lo tenia. Mantener una
    # copia aqui solo garantizaria que la proxima correccion se aplique a una
    # de las dos.
