from __future__ import annotations

import customtkinter as ctk

from services.photo_pool_service import PhotoPoolSnapshot
from ui.theme import (
    ACCENT,
    BORDER,
    CARD_ALT_BG,
    INFO,
    INFO_SOFT,
    SUCCESS,
    SUCCESS_SOFT,
    TEXT_MUTED,
    TEXT_PRIMARY,
    TEXT_SOFT,
    WARNING,
    WARNING_SOFT,
)


class PoolBadge(ctk.CTkFrame):
    def __init__(self, master, refresh_callback, **kwargs) -> None:
        super().__init__(master, fg_color=CARD_ALT_BG, corner_radius=14, border_width=1, border_color=BORDER, **kwargs)
        self._refresh_callback = refresh_callback
        self._compact = False
        self.grid_columnconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=0)

        self.title_label = ctk.CTkLabel(
            self,
            text="Estado del pool",
            font=ctk.CTkFont(size=8, weight="bold"),
            text_color=TEXT_MUTED,
        )
        self.title_label.grid(row=0, column=0, padx=(12, 8), pady=(7, 0), sticky="w")

        self.level_chip = ctk.CTkLabel(
            self,
            text="Sin datos",
            corner_radius=999,
            padx=8,
            pady=2,
            fg_color=INFO_SOFT,
            text_color=INFO,
            font=ctk.CTkFont(size=8, weight="bold"),
        )
        self.level_chip.grid(row=0, column=1, padx=(0, 12), pady=(6, 0), sticky="e")

        self.count_label = ctk.CTkLabel(
            self,
            text="--",
            font=ctk.CTkFont(size=24, weight="bold"),
            text_color=TEXT_PRIMARY,
        )
        self.count_label.grid(row=1, column=0, columnspan=2, padx=12, pady=(0, 0), sticky="w")

        self.caption_label = ctk.CTkLabel(
            self,
            text="Fotos disponibles",
            text_color=TEXT_SOFT,
            font=ctk.CTkFont(size=9),
        )
        self.caption_label.grid(row=2, column=0, columnspan=2, padx=12, pady=(0, 8), sticky="w")

    def set_compact_layout(self, compact: bool) -> None:
        self._compact = compact
        self.count_label.configure(font=ctk.CTkFont(size=20 if compact else 24, weight="bold"))
        self.caption_label.configure(font=ctk.CTkFont(size=8 if compact else 9))

    def set_snapshot(self, snapshot: PhotoPoolSnapshot) -> None:
        label = (snapshot.label or "").lower()
        if snapshot.available_count <= 0:
            chip_text, chip_fg, chip_text_color = "Vacio", WARNING_SOFT, WARNING
        elif "alto" in label or snapshot.available_count >= 10:
            chip_text, chip_fg, chip_text_color = "Saludable", SUCCESS_SOFT, SUCCESS
        else:
            chip_text, chip_fg, chip_text_color = "Atencion", INFO_SOFT, INFO
        self.count_label.configure(text=str(snapshot.available_count), text_color=snapshot.color or ACCENT)
        self.level_chip.configure(text=chip_text, fg_color=chip_fg, text_color=chip_text_color)

    def set_loading(self) -> None:
        self.count_label.configure(text="...", text_color=TEXT_PRIMARY)
        self.level_chip.configure(text="Actualizando", fg_color=INFO_SOFT, text_color=INFO)
