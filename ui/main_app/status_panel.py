from __future__ import annotations

import customtkinter as ctk

from ui.theme import (
    ACCENT,
    ACCENT_SOFT,
    BORDER,
    CARD_BG,
    ERROR,
    ERROR_SOFT,
    INFO,
    INFO_SOFT,
    INPUT_BG,
    SUCCESS,
    SUCCESS_SOFT,
    TEXTBOX_BG,
    TEXT_MUTED,
    TEXT_PRIMARY,
    TEXT_SOFT,
    WARNING,
    WARNING_SOFT,
)


class StatusPanel(ctk.CTkFrame):
    def __init__(self, master, **kwargs) -> None:
        super().__init__(master, fg_color=CARD_BG, corner_radius=18, border_width=1, border_color=BORDER, **kwargs)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)
        self._compact = False
        self._message_color = TEXT_MUTED
        self._visual_state = "neutral"

        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, padx=10, pady=(6, 3), sticky="ew")
        header.grid_columnconfigure(1, weight=1)

        title_wrap = ctk.CTkFrame(header, fg_color="transparent")
        title_wrap.grid(row=0, column=0, columnspan=2, sticky="ew")
        title_wrap.grid_columnconfigure(0, weight=1)

        self.title_label = ctk.CTkLabel(
            title_wrap,
            text="Seguimiento",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color=TEXT_PRIMARY,
        )
        self.title_label.grid(row=0, column=0, sticky="w")

        self.phase_chip = ctk.CTkLabel(
            title_wrap,
            text="General",
            fg_color=INPUT_BG,
            corner_radius=999,
            padx=8,
            pady=3,
            font=ctk.CTkFont(size=9, weight="bold"),
            text_color=TEXT_MUTED,
        )
        self.phase_chip.grid(row=0, column=1, sticky="e")

        self.chips_row = ctk.CTkFrame(header, fg_color="transparent", height=24)
        self.chips_row.grid(row=1, column=0, columnspan=2, pady=(4, 0), sticky="ew")
        self.chips_row.grid_columnconfigure(0, weight=1)
        self.chips_row.grid_columnconfigure(1, weight=1)
        self.chips_row.grid_propagate(False)

        self.alert_chip = ctk.CTkLabel(
            self.chips_row,
            text="",
            fg_color="transparent",
            corner_radius=999,
            padx=10,
            pady=4,
            font=ctk.CTkFont(size=10, weight="bold"),
            text_color=WARNING,
        )
        self.alert_chip.grid(row=0, column=0, sticky="w")

        self.retry_chip = ctk.CTkLabel(
            self.chips_row,
            text="",
            fg_color="transparent",
            corner_radius=999,
            padx=10,
            pady=4,
            font=ctk.CTkFont(size=10, weight="bold"),
            text_color=SUCCESS,
        )
        self.retry_chip.grid(row=0, column=1, sticky="e")

        self.body = ctk.CTkFrame(self, fg_color="transparent")
        self.body.grid(row=1, column=0, padx=10, pady=(0, 8), sticky="nsew")
        self.body.grid_columnconfigure(0, weight=1)
        self.body.grid_rowconfigure(0, weight=1)

        self.message_box = ctk.CTkTextbox(
            self.body,
            wrap="word",
            corner_radius=10,
            border_width=1,
            border_color=BORDER,
            fg_color=TEXTBOX_BG,
            font=ctk.CTkFont(family="Consolas", size=10),
        )
        self.message_box.grid(row=0, column=0, sticky="nsew")
        self.message_box.insert("1.0", "Sin corrida activa todavia.")
        self.message_box.configure(state="disabled")
        self.message_box.bind("<Key>", self._handle_keypress)
        self.message_box.bind("<<Paste>>", lambda _event: "break")
        self.message_box.bind("<<Cut>>", lambda _event: "break")
        self.message_box.bind("<Button-3>", lambda _event: None)
        self.compact_message_label = ctk.CTkLabel(
            self.body,
            text="Sin corrida activa todavia.",
            text_color=TEXT_PRIMARY,
            justify="left",
            anchor="w",
            wraplength=320,
            font=ctk.CTkFont(size=9),
        )
        self._apply_visual_state("neutral")
        self.chips_row.grid_remove()
        self.set_compact_layout(False)

    def set_compact_layout(self, compact: bool) -> None:
        self._compact = compact
        self.title_label.configure(text="Seguimiento", font=ctk.CTkFont(size=10 if compact else 11, weight="bold"))
        self.phase_chip.configure(font=ctk.CTkFont(size=9 if compact else 10, weight="bold"))
        self.alert_chip.configure(font=ctk.CTkFont(size=9 if compact else 10, weight="bold"))
        self.retry_chip.configure(font=ctk.CTkFont(size=9 if compact else 10, weight="bold"))
        self.message_box.configure(height=108 if compact else 116)
        self.compact_message_label.configure(wraplength=320 if compact else 520)

    def set_message(self, message: str, *, color: str | None = None) -> None:
        self._message_color = color or TEXT_MUTED
        phase_label, body = self._split_phase(message)
        visual_state = self._resolve_visual_state(body, color)
        self._apply_visual_state(visual_state)
        self.phase_chip.configure(text=self._phase_chip_label(phase_label, visual_state))
        body_text = body or message or "Sin corrida activa todavia."
        self.message_box.configure(state="normal", text_color=self._message_color)
        self.message_box.delete("1.0", "end")
        self.message_box.insert("1.0", body_text)
        self.message_box.see("end")
        self.message_box.configure(state="disabled")
        self.message_box.mark_set("insert", "1.0")
        self.compact_message_label.configure(text=self._compact_message(body_text))

    def set_persistent_alert(self, text: str) -> None:
        self.alert_chip.configure(text=text, fg_color=WARNING_SOFT, text_color=WARNING)
        self._refresh_auxiliary_chips()

    def clear_persistent_alert(self) -> None:
        self.alert_chip.configure(text="", fg_color="transparent")
        self._refresh_auxiliary_chips()

    def set_retry_indicator(self, text: str) -> None:
        normalized_text = text if "[OK]" in text else "selfie reintentada [OK]"
        self.retry_chip.configure(text=normalized_text, fg_color=SUCCESS_SOFT, text_color=SUCCESS)
        self._refresh_auxiliary_chips()

    def clear_retry_indicator(self) -> None:
        self.retry_chip.configure(text="", fg_color="transparent")
        self._refresh_auxiliary_chips()

    def _split_phase(self, message: str) -> tuple[str, str]:
        if message.startswith("[") and "]" in message:
            phase, body = message.split("]", 1)
            normalized = phase[1:].replace("_", " ").strip().title() or "Proceso"
            return normalized, body.strip()
        return "General", message

    def _resolve_visual_state(self, body: str, color: str | None) -> str:
        if color == SUCCESS:
            lowered = body.lower()
            if "tiempo final" in lowered or "resultado" in lowered:
                return "final"
            return "success"
        if color == ERROR:
            return "error"
        lowered = body.lower()
        if any(word in lowered for word in ("error", "fallo", "denegado", "invalido", "incorrecta")):
            return "error"
        if any(word in lowered for word in ("tiempo final", "resultado", "finalizado", "proceso completado")):
            return "final"
        if any(word in lowered for word in ("guardada", "actualizado", "correctamente", "concedido", "exito", "exitoso")):
            return "success"
        if any(word in lowered for word in ("procesando", "esperando", "consultando", "insertando", "ejecutando")):
            return "progress"
        return "neutral"

    def _apply_visual_state(self, state: str) -> None:
        self._visual_state = state
        palette = {
            "success": (SUCCESS_SOFT, SUCCESS, SUCCESS),
            "error": (ERROR_SOFT, ERROR, ERROR),
            "progress": (INFO_SOFT, INFO, INFO),
            "final": (ACCENT_SOFT, ACCENT, ACCENT),
            "neutral": (ACCENT_SOFT, ACCENT, TEXT_MUTED),
        }
        chip_fg, chip_text, box_border = palette.get(state, palette["neutral"])
        self.phase_chip.configure(fg_color=chip_fg, text_color=chip_text)
        self.message_box.configure(border_color=box_border)
        self.compact_message_label.configure(text_color=TEXT_PRIMARY)

    def _refresh_auxiliary_chips(self) -> None:
        has_alert = bool(self.alert_chip.cget("text"))
        has_retry = bool(self.retry_chip.cget("text"))
        if has_alert or has_retry:
            self.chips_row.grid()
            return
        self.chips_row.grid_remove()

    @staticmethod
    def _phase_chip_label(phase_label: str, visual_state: str) -> str:
        if visual_state == "error":
            return "Error"
        if visual_state == "progress":
            return "En ejecucion"
        if visual_state == "final":
            return "Final Result"
        if phase_label and phase_label != "General":
            return phase_label
        return "General"

    @staticmethod
    def _compact_message(message: str) -> str:
        normalized = " ".join((message or "").split())
        if len(normalized) <= 120:
            return normalized or "Sin actividad reciente."
        return normalized[:117] + "..."

    def _handle_keypress(self, event):
        ctrl_pressed = bool(event.state & 0x4)
        if ctrl_pressed and event.keysym.lower() in {"a", "c"}:
            return None
        if event.keysym in {"Left", "Right", "Up", "Down", "Home", "End", "Prior", "Next", "Shift_L", "Shift_R", "Control_L", "Control_R"}:
            return None
        return "break"
