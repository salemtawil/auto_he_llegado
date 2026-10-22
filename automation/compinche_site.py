"""Compinche: una constante y nada mas.

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
CompincheSelectors = SelectoresDeSitio
CompincheActionSpec = EspecificacionDeAccion
CompincheFlowError = ErrorDeFlujo

__all__ = [
    "BackgroundPhotoPreparation",
    "FlowRoot",
    "CompincheActionSpec",
    "CompincheFlowError",
    "CompincheSelectors",
    "CompincheSite",
]


class CompincheSite(SitioDeBloques):
    site_name = "compinche.io"
    _ENTRY_URL = "https://compinche.io/login"
