"""Turn an exception into something safe to show a user.

Exception text from Supabase, Storage, Playwright or pydantic routinely carries
storage paths, row contents, request URLs with keys, and the values the user just
typed (a phone number, a password field). None of that belongs on screen, in a
screenshot or in a support ticket. The full detail goes to the log; the user gets
the exception type, which is enough to tell a network problem from a data one.
"""

from __future__ import annotations

import logging

from core.errors import ErrorParaElAgente

_LOGGER = logging.getLogger("auto_he_llegado.ui")


def safe_error_summary(exc: BaseException, *, context: str = "") -> str:
    """Log the full exception and return a short, non-sensitive label for the UI.

    La excepcion a la regla es `ErrorParaElAgente`: su texto lo escribimos
    nosotros para que lo lea una persona, asi que se muestra entero. Sin eso,
    "el video debe durar minimo 10 s" llegaba a pantalla como "(RuntimeError)"
    y el agente no tenia forma de saber que hacer.
    """

    _LOGGER.exception(
        "Error en la interfaz%s", f" ({context})" if context else "", exc_info=exc
    )
    if isinstance(exc, ErrorParaElAgente):
        return str(exc)
    return type(exc).__name__
