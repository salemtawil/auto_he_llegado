"""Interruptores de funcionalidad de la app.

Son constantes simples a proposito: no se leen del .env ni de Supabase, asi que
cambiar una aqui y reconstruir es todo lo que hace falta. Cada una documenta por
que esta como esta y que hay que hacer para revertirla.
"""

from __future__ import annotations


# Pestaña "Revision fotos" del panel de administracion: aprobar o descartar los
# fotogramas que llegan de las contribuciones de video.
#
# Deshabilitada el 2026-10-13 por decision del responsable del proyecto, "por el
# momento". El pool se alimenta mientras tanto con el cargador masivo de JPG
# (AutoHeLlegadoUploader.exe y la pestaña "Carga"), que sigue activo.
#
# Para volver a habilitarla: poner esto en True. No hace falta tocar nada mas.
#
# Lo que NO afecta: la carga de fotos, la subida de video (los videos se siguen
# procesando y sus fotogramas se acumulan como candidatos a la espera de que
# alguien los revise), la limpieza de fotos, ni el consumo del pool por las
# corridas.
PHOTO_REVIEW_ENABLED = False

PHOTO_REVIEW_DISABLED_TITLE = "Revisión de fotos deshabilitada"
PHOTO_REVIEW_DISABLED_MESSAGE = (
    "La revisión de fotos está deshabilitada por el momento.\n\n"
    "Los vídeos que suban los agentes se siguen procesando y sus fotogramas "
    "quedan guardados como candidatos: cuando se reactive esta pestaña "
    "estarán aquí para aprobarlos o descartarlos.\n\n"
    "Mientras tanto, el pool se alimenta desde \"Carga\"."
)
