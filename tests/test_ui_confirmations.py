"""Confirmation dialogs must be accurate: irreversible only when it is true."""

from __future__ import annotations

import ui.shared.dialogs as dialogs
from ui.shared.dialogs import confirm_destructive_action


def _capture(monkeypatch, answer=True):
    seen: list[tuple[str, str]] = []

    def askyesno(title, message, **_kwargs):
        seen.append((title, message))
        return answer

    monkeypatch.setattr(dialogs.messagebox, "askyesno", askyesno)
    return seen


def test_irreversible_action_says_so(monkeypatch) -> None:
    seen = _capture(monkeypatch)
    assert confirm_destructive_action(title="Borrar", what="Se borran 3 fotos.") is True
    _title, message = seen[0]
    assert "no se puede deshacer" in message
    assert "Se borran 3 fotos." in message


def test_reversible_action_does_not_claim_to_be_permanent(monkeypatch) -> None:
    seen = _capture(monkeypatch)
    confirm_destructive_action(
        title="Deshabilitar",
        what="Perdera el acceso.",
        reversible=True,
        undo_hint="Puedes volver a habilitarlo con 'Aprobar'.",
    )
    _title, message = seen[0]
    assert "no se puede deshacer" not in message
    assert "Puedes volver a habilitarlo con 'Aprobar'." in message


def test_declining_returns_false(monkeypatch) -> None:
    _capture(monkeypatch, answer=False)
    assert confirm_destructive_action(title="Borrar", what="x") is False


def test_user_actions_are_declared_reversible() -> None:
    from ui.main_app.user_access_panel import UserAccessPanel

    for action in ("disable", "reject_video"):
        title, template, undo_hint = UserAccessPanel._CONFIRMATIONS[action]
        assert title and template and undo_hint
        assert "{who}" in template


def test_on_accent_meets_wcag_aa_on_both_accents() -> None:
    from ui.theme import ACCENT, ON_ACCENT, WARNING

    def luminance(value: str) -> float:
        value = value.lstrip("#")
        channels = [int(value[index : index + 2], 16) / 255 for index in (0, 2, 4)]
        channels = [
            channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4
            for channel in channels
        ]
        return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]

    def ratio(foreground: str, background: str) -> float:
        first, second = sorted([luminance(foreground), luminance(background)], reverse=True)
        return (first + 0.05) / (second + 0.05)

    for mode in (0, 1):  # 0 = light, 1 = dark
        assert ratio(ON_ACCENT[mode], ACCENT[mode]) >= 4.5
        assert ratio(ON_ACCENT[mode], WARNING[mode]) >= 4.5

    # The colours this replaced did not clear AA.
    assert ratio("#FFFFFF", ACCENT[1]) < 4.5


def test_progress_bar_switches_between_determinate_and_indeterminate() -> None:
    from types import SimpleNamespace

    from ui.main_app.window import MainAppWindow

    calls: list = []
    bar = SimpleNamespace(
        configure=lambda **kwargs: calls.append(("configure", kwargs)),
        start=lambda: calls.append(("start", {})),
        stop=lambda: calls.append(("stop", {})),
        set=lambda value: calls.append(("set", value)),
    )
    window = SimpleNamespace(header_video_progress=bar, _header_progress_indeterminate=False)

    MainAppWindow._set_header_progress_indeterminate(window)
    assert window._header_progress_indeterminate is True
    assert ("configure", {"mode": "indeterminate"}) in calls
    assert ("start", {}) in calls

    calls.clear()
    MainAppWindow._set_header_progress_indeterminate(window)
    assert calls == [], "already indeterminate: nothing to redo"

    MainAppWindow._set_header_progress_determinate(window, 0.5)
    assert window._header_progress_indeterminate is False
    assert ("stop", {}) in calls
    assert ("configure", {"mode": "determinate"}) in calls
    assert ("set", 0.5) in calls


def test_indeterminate_flag_is_not_set_when_the_widget_refuses() -> None:
    from types import SimpleNamespace

    from ui.main_app.window import MainAppWindow

    def boom(**_kwargs):
        raise RuntimeError("CTk refused")

    bar = SimpleNamespace(configure=boom, start=lambda: None, stop=lambda: None, set=lambda _v: None)
    window = SimpleNamespace(header_video_progress=bar, _header_progress_indeterminate=False)

    MainAppWindow._set_header_progress_indeterminate(window)

    assert window._header_progress_indeterminate is False, (
        "a stuck flag would freeze the bar for the rest of the session"
    )


def test_safe_error_summary_hides_the_exception_text(caplog) -> None:
    """The user must not see storage paths, row contents or typed values."""

    import logging

    from ui.shared.errors import safe_error_summary

    secret = "https://proyecto.supabase.co/storage/v1/object/photo-pool/available/abc.jpg?token=ZZZ"
    with caplog.at_level(logging.ERROR, logger="auto_he_llegado.ui"):
        summary = safe_error_summary(RuntimeError(secret), context="prueba")

    assert summary == "RuntimeError"
    assert secret not in summary
    # the detail is still recoverable from the log
    assert any(secret in record.getMessage() or secret in str(record.exc_info) for record in caplog.records)


def test_ui_error_messages_no_longer_interpolate_the_exception() -> None:
    from pathlib import Path

    import ui

    ui_root = Path(ui.__file__).parent
    offenders = []
    for path in ui_root.rglob("*.py"):
        if "__pycache__" in str(path):
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            stripped = line.strip()
            if "{exc}" in stripped and "safe_error_summary" not in stripped:
                if stripped.startswith("#") or "Detalle tecnico" in stripped:
                    continue
                offenders.append(f"{path.name}:{number}")
    assert offenders == [], f"raw exception text still shown to the user: {offenders}"


def test_la_contrasena_del_formulario_se_ve_mientras_se_escribe() -> None:
    """Preferencia del usuario: sin enmascarar en el formulario de proceso."""

    from pathlib import Path

    import ui.main_app.form_panel as form_panel

    fuente = Path(form_panel.__file__).read_text(encoding="utf-8")
    linea = next(
        line for line in fuente.splitlines() if "self.password_entry = " in line
    )
    assert "show=" not in linea, "el campo de contraseña debe mostrarse en claro"
