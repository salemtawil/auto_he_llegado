"""Turn an exception into something safe to show a user.

Exception text from Supabase, Storage, Playwright or pydantic routinely carries
storage paths, row contents, request URLs with keys, and the values the user just
typed (a phone number, a password field). None of that belongs on screen, in a
screenshot or in a support ticket. The full detail goes to the log; the user gets
the exception type, which is enough to tell a network problem from a data one.
"""

from __future__ import annotations

import logging

_LOGGER = logging.getLogger("auto_he_llegado.ui")


def safe_error_summary(exc: BaseException, *, context: str = "") -> str:
    """Log the full exception and return a short, non-sensitive label for the UI."""

    _LOGGER.exception(
        "Error en la interfaz%s", f" ({context})" if context else "", exc_info=exc
    )
    return type(exc).__name__
