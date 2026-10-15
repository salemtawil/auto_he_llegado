"""Shared confirmation helpers for destructive actions.

Anything that permanently removes data — Storage objects, photos, a user's
access, local files — must say what will be destroyed, how much of it, and that
it cannot be undone, before it runs.
"""

from __future__ import annotations

from tkinter import messagebox


def confirm_destructive_action(
    *,
    title: str,
    what: str,
    scope: str | None = None,
    reversible: bool = False,
    undo_hint: str | None = None,
    parent=None,
) -> bool:
    """Ask for confirmation before a destructive action.

    ``what`` describes what changes (ideally with a count) and ``scope`` adds any
    reassurance about what is preserved. ``reversible`` must be True whenever the
    action can be undone from the app — claiming "no se puede deshacer" for
    something reversible trains people to ignore the dialog; ``undo_hint`` then
    says how to undo it.
    """

    lines = [what]
    if scope:
        lines.append(scope)
    if reversible:
        lines.append(undo_hint or "Puedes revertirlo despues desde este mismo panel.")
    else:
        lines.append("Esta accion no se puede deshacer.")
    lines.append("")
    lines.append("¿Continuar?")
    return bool(
        messagebox.askyesno(title, "\n".join(lines), parent=parent, default=messagebox.NO)
    )
