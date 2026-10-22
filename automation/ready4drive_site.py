"""Ready4Drive: una constante y nada mas.

Todo el flujo vive en `automation/sitio_de_bloques.py`, compartido con el otro
sitio de bloques. Hasta la unificacion este archivo y su gemelo tenian 151
funciones comunes IDENTICAS salvo por el nombre del sitio, con lo que cada
arreglo habia que copiarlo a mano al otro.
"""

from __future__ import annotations

from automation.sitio_de_bloques import (
    BackgroundPhotoPreparation,
    ErrorDeFlujo,
    EspecificacionDeAccion,
    FlowRoot,
    SelectoresDeSitio,
    SitioDeBloques,
)

# Nombres historicos, por si algo del repo o de las pruebas los sigue usando.
Ready4DriveSelectors = SelectoresDeSitio
Ready4DriveActionSpec = EspecificacionDeAccion
Ready4DriveFlowError = ErrorDeFlujo

__all__ = [
    "BackgroundPhotoPreparation",
    "FlowRoot",
    "Ready4DriveActionSpec",
    "Ready4DriveFlowError",
    "Ready4DriveSelectors",
    "Ready4DriveSite",
]


class Ready4DriveSite(SitioDeBloques):
    site_name = "ready4drive.com"
    _ENTRY_URL = "https://ready4drive.com/login"
