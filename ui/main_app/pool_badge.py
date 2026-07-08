from __future__ import annotations

from dataclasses import dataclass

import customtkinter as ctk

from services.photo_pool_service import PhotoPoolSnapshot
from ui.theme import (
    BORDER,
    CARD_ALT_BG,
    ERROR,
    ERROR_SOFT,
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

# Modifica estos valores para cambiar los rangos visuales del contador del pool.
POOL_LOW_MAX = 1000
POOL_MEDIUM_MAX = 2200


@dataclass(frozen=True)
class PoolBadgeVisualState:
    chip_text: str
    chip_fg: str | tuple[str, str]
    chip_text_color: str | tuple[str, str]
    count_color: str | tuple[str, str]


def _normalize_pool_thresholds(
    low_max: int | None = None,
    medium_max: int | None = None,
) -> tuple[int, int]:
    resolved_low_max = low_max if isinstance(low_max, int) and low_max > 0 else POOL_LOW_MAX
    resolved_medium_max = medium_max if isinstance(medium_max, int) and medium_max > 0 else POOL_MEDIUM_MAX
    if resolved_low_max >= resolved_medium_max:
        return POOL_LOW_MAX, POOL_MEDIUM_MAX
    return resolved_low_max, resolved_medium_max


def resolve_pool_badge_visual_state(
    available_count: int,
    *,
    low_max: int | None = None,
    medium_max: int | None = None,
) -> PoolBadgeVisualState:
    resolved_low_max, resolved_medium_max = _normalize_pool_thresholds(low_max, medium_max)
    if available_count <= 0:
        return PoolBadgeVisualState(
            chip_text="Vacio",
            chip_fg=ERROR_SOFT,
            chip_text_color=ERROR,
            count_color=ERROR,
        )
    if available_count <= resolved_low_max:
        return PoolBadgeVisualState(
            chip_text="Bajo",
            chip_fg=ERROR_SOFT,
            chip_text_color=ERROR,
            count_color=ERROR,
        )
    if available_count <= resolved_medium_max:
        return PoolBadgeVisualState(
            chip_text="Medio",
            chip_fg=WARNING_SOFT,
            chip_text_color=WARNING,
            count_color=WARNING,
        )
    return PoolBadgeVisualState(
        chip_text="Saludable",
        chip_fg=SUCCESS_SOFT,
        chip_text_color=SUCCESS,
        count_color=SUCCESS,
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
        self.caption_label.configure(font=ctk.CTkFont(size=7 if compact else 8))

    def set_snapshot(self, snapshot: PhotoPoolSnapshot) -> None:
        visual_state = resolve_pool_badge_visual_state(snapshot.available_count)
        self.count_label.configure(text=str(snapshot.available_count), text_color=visual_state.count_color)
        self.caption_label.configure(text=self._format_caption(snapshot))
        self.level_chip.configure(
            text=visual_state.chip_text,
            fg_color=visual_state.chip_fg,
            text_color=visual_state.chip_text_color,
        )

    def set_loading(self) -> None:
        self.count_label.configure(text="...", text_color=TEXT_PRIMARY)
        self.caption_label.configure(text="Fotos disponibles")
        self.level_chip.configure(text="Actualizando", fg_color=INFO_SOFT, text_color=INFO)

    @staticmethod
    def _format_caption(snapshot: PhotoPoolSnapshot) -> str:
        if snapshot.new_bucket_name and not snapshot.old_bucket_name:
            return f"{snapshot.new_bucket_name} {snapshot.new_bucket_count}"
        parts = []
        if snapshot.new_bucket_name:
            parts.append(f"Nuevo {snapshot.new_bucket_count}")
        if snapshot.old_bucket_name:
            parts.append(f"Viejo {snapshot.old_bucket_count}")
        return " | ".join(parts) if parts else "Fotos disponibles"
