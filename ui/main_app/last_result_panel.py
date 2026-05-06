from __future__ import annotations

from datetime import datetime
import re

import customtkinter as ctk

from core.models import LastResultSnapshot, ProcessLogRecord
from ui.theme import (
    ACCENT,
    ACCENT_SOFT,
    BORDER,
    CARD_ALT_BG,
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


class LastResultPanel(ctk.CTkFrame):
    def __init__(self, master, *, on_filter_change=None, **kwargs) -> None:
        super().__init__(master, fg_color=CARD_ALT_BG, corner_radius=20, border_width=1, border_color=BORDER, **kwargs)
        self._on_filter_change = on_filter_change
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)
        self._compact = False
        self._detail_values: dict[str, ctk.CTkLabel] = {}

        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, padx=14, pady=(10, 6), sticky="ew")
        header.grid_columnconfigure(0, weight=1)

        self.eyebrow = ctk.CTkLabel(
            header,
            text="Persistido",
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
            text="Ultimo resultado",
            font=ctk.CTkFont(family="Georgia", size=17, weight="bold"),
            text_color=TEXT_PRIMARY,
        ).grid(row=1, column=0, pady=(5, 1), sticky="w")

        self.subline = ctk.CTkLabel(
            header,
            text="Sin registros recientes.",
            text_color=TEXT_SOFT,
            font=ctk.CTkFont(size=10),
        )
        self.subline.grid(row=2, column=0, sticky="w")

        self.filter_menu = ctk.CTkSegmentedButton(
            header,
            values=["General", "Solo exitoso"],
            command=self._handle_filter_change,
        )
        self.filter_menu.grid(row=0, column=1, rowspan=3, sticky="e")
        self.filter_menu.set("General")

        self.body = ctk.CTkScrollableFrame(
            self,
            fg_color="transparent",
            corner_radius=0,
            border_width=0,
        )
        self.body.grid(row=1, column=0, padx=8, pady=(0, 8), sticky="nsew")
        self.body.grid_columnconfigure(0, weight=1)

        self.metrics = ctk.CTkFrame(self.body, fg_color="transparent")
        self.metrics.grid(row=0, column=0, padx=6, pady=(0, 10), sticky="ew")
        for column in range(4):
            self.metrics.grid_columnconfigure(column, weight=1)

        self.site_chip = self._build_metric(self.metrics, 0, "Sitio", "--")
        self.action_chip = self._build_metric(self.metrics, 1, "Accion", "--")
        self.phase_chip = self._build_metric(self.metrics, 2, "Fase", "--")
        self.status_chip = self._build_metric(self.metrics, 3, "Estado", "--")

        self.details = ctk.CTkFrame(self.body, fg_color=INPUT_BG, corner_radius=14)
        self.details.grid(row=1, column=0, padx=6, pady=(0, 10), sticky="ew")
        self.details.grid_columnconfigure(0, weight=1)
        self.details.grid_columnconfigure(1, weight=1)

        detail_labels = (
            "Fecha y hora",
            "Agente",
            "Telefono",
            "Estacion",
            "Precio",
            "Duracion",
            "Reintentos selfie",
            "Deepfakescore",
            "Mensaje breve",
        )
        full_width_labels = {"Mensaje breve"}
        detail_index = 0
        visual_row = 0
        for label in detail_labels:
            card = ctk.CTkFrame(self.details, fg_color="transparent")
            if label in full_width_labels:
                card.grid(row=visual_row, column=0, columnspan=2, padx=12, pady=(10 if visual_row == 0 else 0, 10), sticky="ew")
                visual_row += 1
            else:
                row = detail_index // 2
                column = detail_index % 2
                card.grid(row=row, column=column, padx=(12, 6) if column == 0 else (6, 12), pady=(10 if row == 0 else 0, 10), sticky="ew")
                detail_index += 1
                visual_row = max(visual_row, row + 1)
            card.grid_columnconfigure(0, weight=1)
            ctk.CTkLabel(card, text=label, font=ctk.CTkFont(size=9, weight="bold"), text_color=TEXT_MUTED).grid(row=0, column=0, sticky="w")
            value = ctk.CTkLabel(card, text="--", font=ctk.CTkFont(size=12, weight="bold"), text_color=TEXT_PRIMARY, anchor="w", justify="left", wraplength=520)
            value.grid(row=1, column=0, pady=(2, 0), sticky="ew")
            self._detail_values[label] = value

        self.message_card = ctk.CTkFrame(self.body, fg_color=INPUT_BG, corner_radius=14, border_width=1, border_color=BORDER)
        self.message_card.grid(row=2, column=0, padx=6, pady=(0, 6), sticky="ew")
        self.message_card.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(self.message_card, text="Mensaje completo", font=ctk.CTkFont(size=9, weight="bold"), text_color=TEXT_MUTED).grid(row=0, column=0, padx=12, pady=(10, 0), sticky="w")
        self.message_label = ctk.CTkLabel(
            self.message_card,
            text="Sin registros recientes.",
            text_color=TEXT_PRIMARY,
            justify="left",
            anchor="w",
            wraplength=520,
            font=ctk.CTkFont(size=11),
        )
        self.message_label.grid(row=1, column=0, padx=12, pady=(6, 12), sticky="ew")

        self._apply_visual_state("neutral")
        self.set_placeholder()

    def _build_metric(self, master, column: int, label: str, value: str) -> ctk.CTkLabel:
        tile = ctk.CTkFrame(master, fg_color=INPUT_BG, corner_radius=12)
        tile.grid(row=0, column=column, padx=(0, 8) if column < 3 else 0, sticky="ew")
        tile.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(tile, text=label, font=ctk.CTkFont(size=9, weight="bold"), text_color=TEXT_MUTED).grid(row=0, column=0, padx=10, pady=(8, 0), sticky="w")
        value_label = ctk.CTkLabel(tile, text=value, font=ctk.CTkFont(size=12, weight="bold"), text_color=TEXT_PRIMARY)
        value_label.grid(row=1, column=0, padx=10, pady=(2, 9), sticky="w")
        return value_label

    def set_placeholder(self) -> None:
        self.subline.configure(text="Sin registros recientes.")
        for metric in (self.site_chip, self.action_chip, self.phase_chip, self.status_chip):
            metric.configure(text="--")
        self._detail_values["Fecha y hora"].configure(text="--")
        self._detail_values["Agente"].configure(text="--")
        self._detail_values["Telefono"].configure(text="--")
        self._detail_values["Estacion"].configure(text="--")
        self._detail_values["Precio"].configure(text="--")
        self._detail_values["Duracion"].configure(text="--")
        self._detail_values["Reintentos selfie"].configure(text="--")
        self._detail_values["Deepfakescore"].configure(text="--")
        self._detail_values["Mensaje breve"].configure(text="--")
        self.message_label.configure(text="Sin registros recientes.")
        self._apply_visual_state("neutral")

    def set_filter_mode(self, mode: str) -> None:
        normalized_mode = "Solo exitoso" if mode == "success_only" else "General"
        self.filter_menu.set(normalized_mode)

    def set_compact_layout(self, compact: bool) -> None:
        self._compact = compact
        wrap = 320 if compact else 520
        self._detail_values["Mensaje breve"].configure(wraplength=wrap)
        self.message_label.configure(wraplength=wrap)
        if compact:
            for column in range(4):
                self.metrics.grid_columnconfigure(column, weight=0)
            for index, child in enumerate(self.metrics.winfo_children()):
                child.grid_configure(row=index // 2, column=index % 2, padx=(0, 8), pady=(0, 6), sticky="ew")
            for column in range(2):
                self.metrics.grid_columnconfigure(column, weight=1)
        else:
            for index, child in enumerate(self.metrics.winfo_children()):
                child.grid_configure(row=0, column=index, padx=(0, 8) if index < 3 else 0, pady=0, sticky="ew")
            for column in range(4):
                self.metrics.grid_columnconfigure(column, weight=1)

    def set_snapshot(self, snapshot: LastResultSnapshot | None) -> None:
        if snapshot is None:
            self.set_placeholder()
            return
        self.subline.configure(text=f"{snapshot.site_name} | {snapshot.action_name}")
        self._apply_visual_state("success" if snapshot.success else "error")
        self.site_chip.configure(text=snapshot.site_name or "N/A")
        self.action_chip.configure(text=snapshot.action_name or "N/A")
        self.phase_chip.configure(text="final_result" if snapshot.success else snapshot.final_status or "N/A")
        self.status_chip.configure(text=snapshot.final_status or "N/A")
        self._detail_values["Fecha y hora"].configure(text=self._format_datetime(snapshot.completed_at))
        self._detail_values["Agente"].configure(text=snapshot.agent_name or "N/A")
        self._detail_values["Telefono"].configure(text=snapshot.phone_number or "N/A")
        self._detail_values["Estacion"].configure(text=snapshot.station_name or "N/A")
        self._detail_values["Precio"].configure(text=snapshot.block_price or "N/A")
        self._detail_values["Duracion"].configure(text=snapshot.block_duration or "N/A")
        self._detail_values["Reintentos selfie"].configure(text=str(snapshot.deepfakescore_retries))
        self._detail_values["Deepfakescore"].configure(text="Activado" if snapshot.deepfakescore_retries > 0 else "No")
        message = snapshot.message or "N/A"
        self._detail_values["Mensaje breve"].configure(text=(message[:140] + "...") if len(message) > 140 else message)
        self.message_label.configure(text=message)

    def set_log(self, log_record: ProcessLogRecord | None) -> None:
        if log_record is None:
            self.set_placeholder()
            return
        self.subline.configure(text=f"{log_record.site} | {log_record.action}")
        self._apply_visual_state(self._resolve_visual_state(log_record))
        self.site_chip.configure(text=log_record.site or "N/A")
        self.action_chip.configure(text=log_record.action or "N/A")
        self.phase_chip.configure(text=log_record.phase or "N/A")
        self.status_chip.configure(text=log_record.final_status or "N/A")
        self._detail_values["Fecha y hora"].configure(text=self._format_datetime(log_record.finished_at or log_record.created_at))
        self._detail_values["Agente"].configure(text=log_record.agent_name or "N/A")
        self._detail_values["Telefono"].configure(text=log_record.phone or "N/A")
        self._detail_values["Estacion"].configure(text=log_record.station_name or "N/A")
        self._detail_values["Precio"].configure(text=log_record.block_price or "N/A")
        self._detail_values["Duracion"].configure(text="N/A")
        message = log_record.page_message or log_record.error_message or "N/A"
        retry_count, deepfakescore_state = self._extract_retry_metadata(message)
        self._detail_values["Reintentos selfie"].configure(text=str(retry_count) if retry_count is not None else "--")
        self._detail_values["Deepfakescore"].configure(text=deepfakescore_state or "--")
        self._detail_values["Mensaje breve"].configure(text=(message[:140] + "...") if len(message) > 140 else message)
        self.message_label.configure(text=message)

    def _resolve_visual_state(self, log_record: ProcessLogRecord) -> str:
        final_status = (log_record.final_status or "").lower()
        phase = (log_record.phase or "").lower()
        if any(word in final_status for word in ("success", "completed", "ok")):
            return "success"
        if any(word in final_status for word in ("failed", "error", "denied")):
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

    @staticmethod
    def _extract_retry_metadata(message: str) -> tuple[int | None, str | None]:
        retry_match = re.search(r"reintentos selfie:\s*(\d+)", message, re.IGNORECASE)
        deepfakescore_match = re.search(r"deepfakescore:\s*([a-zA-Z ]+)", message, re.IGNORECASE)
        retry_count = int(retry_match.group(1)) if retry_match else None
        deepfakescore_state = None
        if deepfakescore_match:
            normalized = deepfakescore_match.group(1).strip().lower()
            deepfakescore_state = "Activado" if "activado" in normalized else "No"
        return retry_count, deepfakescore_state

    def _handle_filter_change(self, value: str) -> None:
        if self._on_filter_change is None:
            return
        self._on_filter_change("success_only" if value == "Solo exitoso" else "general")

    @staticmethod
    def _format_datetime(value: datetime | str | None) -> str:
        if value is None:
            return "N/A"
        if isinstance(value, datetime):
            return value.astimezone().strftime("%Y-%m-%d %H:%M:%S")
        return str(value)
