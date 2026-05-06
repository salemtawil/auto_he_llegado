from __future__ import annotations

from datetime import datetime

import customtkinter as ctk

from core.models import ProcessExecutionResult
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
    TEXT_MUTED,
    TEXT_PRIMARY,
    TEXT_SOFT,
    WARNING,
    WARNING_SOFT,
)


class CurrentResultPanel(ctk.CTkFrame):
    def __init__(self, master, **kwargs) -> None:
        super().__init__(master, fg_color=CARD_BG, corner_radius=20, border_width=1, border_color=BORDER, **kwargs)
        self.grid_columnconfigure(0, weight=1)
        self._compact = False
        self._detail_values: dict[str, ctk.CTkLabel] = {}
        self._elapsed_value = "--"

        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, padx=14, pady=(10, 6), sticky="ew")
        header.grid_columnconfigure(0, weight=1)

        self.eyebrow = ctk.CTkLabel(
            header,
            text="Ejecucion actual",
            fg_color=ACCENT_SOFT,
            corner_radius=999,
            padx=8,
            pady=3,
            font=ctk.CTkFont(size=9, weight="bold"),
            text_color=TEXT_PRIMARY,
        )
        self.eyebrow.grid(row=0, column=0, sticky="w")

        ctk.CTkLabel(
            header,
            text="Resultado",
            font=ctk.CTkFont(family="Georgia", size=17, weight="bold"),
            text_color=TEXT_PRIMARY,
        ).grid(row=1, column=0, pady=(5, 1), sticky="w")

        self.subline = ctk.CTkLabel(
            header,
            text="Sin corrida activa todavía.",
            text_color=TEXT_SOFT,
            font=ctk.CTkFont(size=10),
        )
        self.subline.grid(row=2, column=0, sticky="w")

        self.body = ctk.CTkFrame(self, fg_color=INPUT_BG, corner_radius=14)
        self.body.grid(row=1, column=0, padx=12, pady=(0, 12), sticky="ew")
        for column in range(2):
            self.body.grid_columnconfigure(column, weight=1)

        for index, label in enumerate(("Estado", "Pagina", "Accion", "Tiempo final")):
            row = index // 2
            column = index % 2
            card = ctk.CTkFrame(self.body, fg_color="transparent")
            card.grid(
                row=row,
                column=column,
                padx=(10, 6) if column == 0 else (6, 10),
                pady=(10 if row == 0 else 6, 0),
                sticky="ew",
            )
            card.grid_columnconfigure(0, weight=1)
            ctk.CTkLabel(
                card,
                text=label,
                font=ctk.CTkFont(size=9, weight="bold"),
                text_color=TEXT_MUTED,
            ).grid(row=0, column=0, sticky="w")
            value = ctk.CTkLabel(
                card,
                text="--",
                font=ctk.CTkFont(size=12, weight="bold"),
                text_color=TEXT_PRIMARY,
                anchor="w",
                justify="left",
            )
            value.grid(row=1, column=0, pady=(2, 0), sticky="ew")
            self._detail_values[label] = value

        self.message_card = ctk.CTkFrame(
            self,
            fg_color=INPUT_BG,
            corner_radius=14,
            border_width=1,
            border_color=BORDER,
        )
        self.message_card.grid(row=2, column=0, padx=12, pady=(0, 12), sticky="ew")
        self.message_card.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            self.message_card,
            text="Mensaje",
            font=ctk.CTkFont(size=9, weight="bold"),
            text_color=TEXT_MUTED,
        ).grid(row=0, column=0, padx=12, pady=(10, 0), sticky="w")
        self.message_label = ctk.CTkLabel(
            self.message_card,
            text="Todavía no hay resultado.",
            text_color=TEXT_PRIMARY,
            justify="left",
            anchor="w",
            wraplength=520,
            font=ctk.CTkFont(size=11),
        )
        self.message_label.grid(row=1, column=0, padx=12, pady=(6, 12), sticky="ew")

        self._apply_visual_state("neutral")
        self.set_placeholder()

    def set_placeholder(self) -> None:
        self.subline.configure(text="Sin corrida activa todavía.")
        self._elapsed_value = "--"
        for value in self._detail_values.values():
            value.configure(text="--")
        self.message_label.configure(text="Todavía no hay resultado.")
        self._apply_visual_state("neutral")

    def set_compact_layout(self, compact: bool) -> None:
        self._compact = compact
        self.message_label.configure(wraplength=340 if compact else 720)

    def set_result(self, result: ProcessExecutionResult, *, elapsed_text: str | None = None) -> None:
        self.subline.configure(text=f"{result.page_name} | {result.action_name}")
        self._apply_visual_state(self._resolve_visual_state(result))
        self._elapsed_value = elapsed_text or "--"
        self._detail_values["Estado"].configure(text=self._status_label(result))
        self._detail_values["Pagina"].configure(text=result.page_name)
        self._detail_values["Accion"].configure(text=result.action_name)
        self._detail_values["Tiempo final"].configure(text=self._elapsed_value)
        self.message_label.configure(text=self._short_message(result.message))

    def _status_label(self, result: ProcessExecutionResult) -> str:
        if result.success:
            return "Exitoso"
        phase = (result.phase or "").lower()
        if phase in {"login", "initial_action", "photo_upload", "continue_submit", "block_read", "final_submit"}:
            return "Ejecutando"
        if (result.final_status or "").lower() in {"failed", "error", "timeout"}:
            return "Error"
        return "Pendiente"

    @staticmethod
    def _short_message(message: str) -> str:
        normalized = " ".join((message or "").split())
        if len(normalized) <= 180:
            return normalized or "Sin mensaje."
        return normalized[:177] + "..."

    def _resolve_visual_state(self, result: ProcessExecutionResult) -> str:
        if result.success:
            return "success"
        final_status = (result.final_status or "").lower()
        phase = (result.phase or "").lower()
        if any(word in final_status for word in ("failed", "error", "denied", "timeout")):
            return "error"
        if any(word in phase for word in ("login", "upload", "submit", "result", "read")):
            return "progress"
        return "warning"

    def _apply_visual_state(self, state: str) -> None:
        palette = {
            "success": (SUCCESS_SOFT, SUCCESS, SUCCESS),
            "error": (ERROR_SOFT, ERROR, ERROR),
            "progress": (INFO_SOFT, INFO, INFO),
            "warning": (WARNING_SOFT, WARNING, WARNING),
            "neutral": (ACCENT_SOFT, ACCENT, BORDER),
        }
        chip_fg, chip_text, border = palette.get(state, palette["neutral"])
        self.eyebrow.configure(fg_color=chip_fg, text_color=chip_text)
        self.message_card.configure(border_color=border)
        self._detail_values["Estado"].configure(text_color=chip_text)

    @staticmethod
    def _format_datetime(value: datetime | None) -> str:
        if value is None:
            return "N/A"
        return value.astimezone().strftime("%Y-%m-%d %H:%M:%S")
