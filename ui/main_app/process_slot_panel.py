from __future__ import annotations

import customtkinter as ctk

from ui.main_app.current_result_panel import CurrentResultPanel
from ui.main_app.extension_status_panel import ExtensionStatusPanel
from ui.main_app.form_panel import FormPanel
from ui.main_app.status_panel import StatusPanel
from ui.theme import BORDER, CARD_ALT_BG, INPUT_BG, NEUTRAL_BUTTON, NEUTRAL_BUTTON_HOVER, TEXT_MUTED, TEXT_PRIMARY


class ProcessSlotPanel(ctk.CTkFrame):
    def __init__(
        self,
        master,
        *,
        title: str,
        on_start,
        on_clear,
        on_export_state,
        **kwargs,
    ) -> None:
        super().__init__(
            master,
            fg_color=CARD_ALT_BG,
            corner_radius=24,
            border_width=1,
            border_color=BORDER,
            **kwargs,
        )
        self._compact = False

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, padx=16, pady=(14, 8), sticky="ew")
        header.grid_columnconfigure(0, weight=1)
        header.grid_columnconfigure(1, weight=0)

        title_wrap = ctk.CTkFrame(header, fg_color="transparent")
        title_wrap.grid(row=0, column=0, sticky="w")

        self.eyebrow = ctk.CTkLabel(
            title_wrap,
            text=title,
            fg_color=INPUT_BG,
            corner_radius=999,
            padx=10,
            pady=4,
            font=ctk.CTkFont(size=10, weight="bold"),
            text_color=TEXT_PRIMARY,
        )
        self.eyebrow.grid(row=0, column=0, sticky="w")

        self.summary_label = ctk.CTkLabel(
            title_wrap,
            text="Listo para ejecutar.",
            text_color=TEXT_MUTED,
            font=ctk.CTkFont(size=10),
        )
        self.summary_label.grid(row=1, column=0, pady=(4, 0), sticky="w")

        self.process_timer_label = ctk.CTkLabel(
            header,
            text="Tiempo: 00:00",
            text_color=TEXT_MUTED,
            font=ctk.CTkFont(size=11, weight="bold"),
        )
        self.process_timer_label.grid(row=0, column=1, rowspan=2, sticky="e")

        self.body = ctk.CTkFrame(self, fg_color="transparent")
        self.body.grid(row=1, column=0, padx=14, pady=(0, 14), sticky="nsew")
        self.body.grid_columnconfigure(0, weight=3)
        self.body.grid_columnconfigure(1, weight=2)
        self.body.grid_rowconfigure(0, weight=1)

        self.form_panel = FormPanel(self.body)
        self.form_panel.grid(row=0, column=0, sticky="ew")

        self.status_panel = StatusPanel(self.body)
        self.status_panel.grid(row=0, column=1, padx=(12, 0), sticky="nsew")

        actions = self.form_panel.get_actions_container()
        actions.grid_columnconfigure(0, weight=1)
        actions.grid_columnconfigure(1, weight=1)
        actions.grid_columnconfigure(2, weight=1)

        self.run_button = ctk.CTkButton(
            actions,
            text="Iniciar proceso",
            command=on_start,
            height=34,
            corner_radius=12,
            font=ctk.CTkFont(size=12, weight="bold"),
        )
        self.run_button.grid(row=0, column=0, padx=(0, 6), pady=(0, 6), sticky="ew")

        self.clear_button = ctk.CTkButton(
            actions,
            text="Limpiar",
            command=on_clear,
            height=32,
            corner_radius=12,
            font=ctk.CTkFont(size=11, weight="bold"),
        )
        self.clear_button.grid(row=0, column=1, padx=(0, 6), pady=(0, 6), sticky="ew")

        self.export_debug_button = ctk.CTkButton(
            actions,
            text="Exportar debug",
            command=on_export_state,
            height=32,
            corner_radius=12,
            fg_color=NEUTRAL_BUTTON,
            hover_color=NEUTRAL_BUTTON_HOVER,
            text_color=TEXT_PRIMARY,
            font=ctk.CTkFont(size=11, weight="bold"),
        )
        self.export_debug_button.grid(row=0, column=2, pady=(0, 6), sticky="ew")

        self.current_result_panel = CurrentResultPanel(self)
        self.extension_status_panel = ExtensionStatusPanel(self)

    def set_compact_layout(self, compact: bool) -> None:
        self._compact = compact
        self.form_panel.set_compact_layout(compact)
        self.status_panel.set_compact_layout(True)
        self.current_result_panel.set_compact_layout(True)
        self.extension_status_panel.set_compact_layout(compact)

        if compact:
            self.process_timer_label.grid_configure(row=2, column=0, columnspan=2, rowspan=1, pady=(8, 0), sticky="w")
            self.body.grid_columnconfigure(0, weight=1)
            self.body.grid_columnconfigure(1, weight=1)
            self.status_panel.grid_configure(row=1, column=0, columnspan=2, padx=0, pady=(12, 0), sticky="nsew")
        else:
            self.process_timer_label.grid_configure(row=0, column=1, rowspan=2, pady=0, sticky="e")
            self.body.grid_columnconfigure(0, weight=3)
            self.body.grid_columnconfigure(1, weight=2)
            self.status_panel.grid_configure(row=0, column=1, columnspan=1, padx=(12, 0), pady=0, sticky="nsew")
