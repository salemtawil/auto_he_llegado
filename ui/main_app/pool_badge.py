from __future__ import annotations

import customtkinter as ctk

from services.photo_pool_service import PhotoPoolSnapshot
from ui.theme import (
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
        super().__init__(master, fg_color=CARD_ALT_BG, corner_radius=18, border_width=1, border_color=BORDER, **kwargs)
        self._refresh_callback = refresh_callback
        self._compact = False
        self.grid_columnconfigure(1, weight=1)

        self.eyebrow = ctk.CTkLabel(
            self,
            text="Pool de fotos",
            font=ctk.CTkFont(size=9, weight="bold"),
            text_color=TEXT_MUTED,
        )
        self.eyebrow.grid(row=0, column=0, padx=(12, 8), pady=(8, 0), sticky="w")

        self.level_chip = ctk.CTkLabel(
            self,
            text="Sin datos",
            corner_radius=999,
            padx=9,
            pady=3,
            fg_color=INFO_SOFT,
            text_color=INFO,
            font=ctk.CTkFont(size=9, weight="bold"),
        )
        self.level_chip.grid(row=0, column=1, padx=(0, 12), pady=(8, 0), sticky="e")

        self.count_label = ctk.CTkLabel(
            self,
            text="--",
            font=ctk.CTkFont(family="Georgia", size=22, weight="bold"),
            text_color=TEXT_PRIMARY,
        )
        self.count_label.grid(row=1, column=0, padx=(12, 6), pady=(1, 4), sticky="w")

        self.caption_label = ctk.CTkLabel(
            self,
            text="Fotos disponibles",
            text_color=TEXT_SOFT,
            justify="left",
            font=ctk.CTkFont(size=10),
        )
        self.caption_label.grid(row=1, column=1, padx=(0, 12), pady=(2, 4), sticky="w")

        self.helper_label = ctk.CTkLabel(
            self,
            text="Esperando sincronizacion.",
            text_color=TEXT_SOFT,
            font=ctk.CTkFont(size=9),
        )
        self.helper_label.grid(row=2, column=0, columnspan=2, padx=12, pady=(0, 8), sticky="w")

    def set_compact_layout(self, compact: bool) -> None:
        self._compact = compact
        self.count_label.configure(font=ctk.CTkFont(family="Georgia", size=18 if compact else 22, weight="bold"))
        self.caption_label.configure(wraplength=90 if compact else 120)
        self.helper_label.configure(wraplength=150 if compact else 220)

    def set_snapshot(self, snapshot: PhotoPoolSnapshot) -> None:
        label = (snapshot.label or "").lower()
        if snapshot.available_count <= 0:
            chip_text, chip_fg, chip_text_color = "Vacio", WARNING_SOFT, WARNING
            helper = "No hay fotos listas para consumir."
        elif "alto" in label or snapshot.available_count >= 10:
            chip_text, chip_fg, chip_text_color = "Saludable", SUCCESS_SOFT, SUCCESS
            helper = "Pool estable y listo para ejecuciones."
        else:
            chip_text, chip_fg, chip_text_color = "Atencion", INFO_SOFT, INFO
            helper = f"{snapshot.label} en estado available"
        self.count_label.configure(text=str(snapshot.available_count), text_color=snapshot.color)
        self.caption_label.configure(text="Fotos disponibles")
        self.level_chip.configure(text=chip_text, fg_color=chip_fg, text_color=chip_text_color)
        self.helper_label.configure(text=helper)

    def set_loading(self) -> None:
        self.count_label.configure(text="...", text_color=TEXT_PRIMARY)
        self.level_chip.configure(text="Actualizando", fg_color=INFO_SOFT, text_color=INFO)
        self.caption_label.configure(text="Consultando pool")
        self.helper_label.configure(text="Sincronizando contador y estado.")
