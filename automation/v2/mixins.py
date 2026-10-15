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

    def _capture_extension_debug_if_useful(self, session, **kwargs):
        """Solo captura el diagnostico si la extension esta activa.

        `capture_extension_debug` recorre TODOS los frames tres veces por
        llamada, y las automatizaciones la llaman 7-8 veces por corrida. La v1
        no la condiciona a nada util: su unico corte es `if snapshot is None`,
        que no se cumple nunca, porque el evaluate tiene exito igual aunque no
        haya extension (devuelve un dict con nulos).

        Resultado en la v1: con el motor tradicional, sin ninguna extension
        cargada, se pagan decenas de evaluaciones de DOM por corrida para
        rellenar un diagnostico que nadie va a mirar.

        Cuando SI hay extension, delega en la v1 para no divergir: misma
        llamada, mismos errores, mismo valor de retorno.
        """

        if session is None:
            return None
        if not getattr(session, "extension_enabled", False):
            return None
        return super()._capture_extension_debug_if_useful(session, **kwargs)
