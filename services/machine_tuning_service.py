"""Aplica a la configuracion guardada el perfil del equipo.

Se ejecuta al arrancar. Si el equipo no es el mismo con el que se calcularon
los limites guardados (o si nunca se calcularon), los recalcula y los guarda.
Mientras el equipo sea el mismo no toca nada: lo que el agente haya cambiado a
mano en la ventana de ajustes se respeta.
"""

from __future__ import annotations

from dataclasses import dataclass
import logging

from config.machine_profile import (
    MachineProfile,
    describir_equipo,
    perfil_del_equipo,
)
from core.models import LocalConfig
from services.local_config_service import LocalConfigService

_LOGGER = logging.getLogger("auto_he_llegado.machine")


@dataclass(frozen=True)
class TuningResult:
    config: LocalConfig
    perfil: MachineProfile
    aplicado: bool


class MachineTuningService:
    def __init__(
        self,
        config_service: LocalConfigService | None = None,
        *,
        perfil: MachineProfile | None = None,
    ) -> None:
        self._config_service = config_service or LocalConfigService()
        self._perfil = perfil

    def perfil(self) -> MachineProfile:
        if self._perfil is None:
            self._perfil = perfil_del_equipo()
        return self._perfil

    def ajustar(self, config: LocalConfig | None = None) -> TuningResult:
        perfil = self.perfil()
        config = config if config is not None else self._config_service.load()

        if not perfil.medicion_confiable:
            # Sin medida real los limites son una suposicion: valen para esta
            # sesion, pero no se guardan. Si se guardaran, un fallo puntual de
            # psutil dejaria a un equipo de 16 GB con el perfil 'ligero' y la
            # firma cambiada, y al arranque siguiente volveria a reescribirlo
            # todo, borrando ademas lo que el agente hubiera ajustado a mano.
            _LOGGER.warning(
                "No se pudo medir el equipo; se usan limites prudentes sin"
                " guardarlos. %s",
                describir_equipo(perfil),
            )
            datos = config.model_dump()
            datos.update(perfil.como_ajustes())
            return TuningResult(
                config=LocalConfig.model_validate(datos),
                perfil=perfil,
                aplicado=False,
            )

        if config.hardware_signature == perfil.firma:
            _LOGGER.info(
                "Equipo ya conocido. %s", describir_equipo(perfil)
            )
            return TuningResult(config=config, perfil=perfil, aplicado=False)

        datos = config.model_dump()
        datos.update(perfil.como_ajustes())
        datos["hardware_signature"] = perfil.firma
        datos["hardware_profile"] = perfil.nombre
        nueva = LocalConfig.model_validate(datos)
        guardada = self._config_service.save(nueva)
        _LOGGER.info(
            "Equipo nuevo o sin medir: se reconfiguro la app. %s",
            describir_equipo(perfil),
        )
        return TuningResult(config=guardada, perfil=perfil, aplicado=True)
