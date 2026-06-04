from __future__ import annotations

import customtkinter as ctk

from ui.main_app.extension_status_panel import ExtensionStatusPanel
from ui.main_app.form_panel import FormPanel
from ui.main_app.status_panel import StatusPanel
from ui.main_app.current_result_panel import CurrentResultPanel
from ui.theme import ACCENT, ACCENT_HOVER, BORDER, CARD_ALT_BG, NEUTRAL_BUTTON, NEUTRAL_BUTTON_HOVER, TEXT_MUTED, TEXT_PRIMARY


class ProcessSlotPanel(ctk.CTkFrame):
    _MIN_CARD_HEIGHT = 304

    def __init__(
        self,
        master,
        *,
        title: str,
        on_start,
        on_clear,
        on_export_state,
        on_open_diagnostics=None,
        on_open_extensions=None,
        on_open_browser=None,
        on_owner_selfie_toggle=None,
        on_owner_selfie_select=None,
        on_owner_selfie_remove=None,
        **kwargs,
    ) -> None:
        super().__init__(master, fg_color=CARD_ALT_BG, corner_radius=18, border_width=1, border_color=BORDER, **kwargs)
        self._compact = False
        self._secondary_visual = False
        self._on_open_diagnostics = on_open_diagnostics
        self._on_open_extensions = on_open_extensions
        self._on_open_browser = on_open_browser

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)
        self.grid_propagate(False)
        self.configure(height=self._MIN_CARD_HEIGHT)
        self.header = ctk.CTkFrame(self, fg_color="transparent")
        self.header.grid(row=0, column=0, padx=10, pady=(8, 2), sticky="ew")
        self.header.grid_columnconfigure(0, weight=1)
        self.header.grid_columnconfigure(1, weight=0)

        self.title_wrap = ctk.CTkFrame(self.header, fg_color="transparent")
        self.title_wrap.grid(row=0, column=0, sticky="w")
        self.title_wrap.grid_columnconfigure(1, weight=1)

        self.title_accent = ctk.CTkFrame(self.title_wrap, fg_color=ACCENT, width=5, height=18, corner_radius=999)
        self.title_accent.grid(row=0, column=0, padx=(0, 8), sticky="ns")

        self.eyebrow = ctk.CTkLabel(
            self.title_wrap,
            text=title,
            fg_color="transparent",
            corner_radius=0,
            padx=0,
            pady=0,
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=TEXT_PRIMARY,
        )
        self.eyebrow.grid(row=0, column=1, sticky="w")

        self.summary_label = ctk.CTkLabel(
            self.title_wrap,
            text="",
            text_color=TEXT_MUTED,
            font=ctk.CTkFont(size=1),
        )
        self.summary_label.grid(row=1, column=1, pady=0, sticky="w")
        self.summary_label.grid_remove()

        self.process_timer_label = ctk.CTkLabel(
            self.header,
            text="Tiempo: 00:00",
            text_color=TEXT_MUTED,
            font=ctk.CTkFont(size=10, weight="bold"),
        )
        self.process_timer_label.grid(row=0, column=1, sticky="e")

        self.body = ctk.CTkFrame(self, fg_color="transparent")
        self.body.grid(row=1, column=0, padx=10, pady=(0, 6), sticky="nsew")
        self.body.grid_columnconfigure(0, weight=1, uniform="slot_body")
        self.body.grid_columnconfigure(1, weight=1, uniform="slot_body")
        self.body.grid_rowconfigure(0, weight=1)
        self.body.grid_rowconfigure(1, weight=0)

        self.form_panel = FormPanel(
            self.body,
            on_owner_selfie_toggle=on_owner_selfie_toggle,
            on_owner_selfie_select=on_owner_selfie_select,
            on_owner_selfie_remove=on_owner_selfie_remove,
        )
        self.form_panel.grid(row=0, column=0, sticky="nsew")

        self.status_panel = StatusPanel(self.body)
        self.status_panel.grid(row=0, column=1, padx=(10, 0), sticky="nsew")

        self.actions = self.form_panel.get_actions_container()
        self.actions.grid_columnconfigure(0, weight=1, uniform="primary_actions")
        self.actions.grid_columnconfigure(1, weight=1, uniform="primary_actions")
        self.actions.grid_columnconfigure(2, weight=1, uniform="primary_actions")

        self.run_button = ctk.CTkButton(
            self.actions,
            text="Iniciar proceso",
            command=on_start,
            height=28,
            corner_radius=10,
            fg_color=ACCENT,
            hover_color=ACCENT_HOVER,
            font=ctk.CTkFont(size=10, weight="bold"),
        )
        self.run_button.grid(row=0, column=0, padx=(0, 5), pady=(0, 2), sticky="ew")

        self.clear_button = ctk.CTkButton(
            self.actions,
            text="Limpiar",
            command=on_clear,
            height=28,
            corner_radius=10,
            fg_color=NEUTRAL_BUTTON,
            hover_color=NEUTRAL_BUTTON_HOVER,
            text_color=TEXT_PRIMARY,
            font=ctk.CTkFont(size=10, weight="bold"),
        )
        self.clear_button.grid(row=0, column=1, padx=(0, 5), pady=(0, 2), sticky="ew")

        self.export_debug_button = ctk.CTkButton(
            self.actions,
            text="Exportar debug",
            command=on_export_state,
            height=28,
            corner_radius=10,
            fg_color=NEUTRAL_BUTTON,
            hover_color=NEUTRAL_BUTTON_HOVER,
            text_color=TEXT_PRIMARY,
            font=ctk.CTkFont(size=10, weight="bold"),
        )
        self.export_debug_button.grid(row=0, column=2, pady=(0, 2), sticky="ew")

        self.secondary_actions = ctk.CTkFrame(self.form_panel, fg_color="transparent")
        self.secondary_actions.grid_columnconfigure(0, weight=1)
        self.secondary_actions.grid_columnconfigure(1, weight=1)
        self.secondary_actions.grid_columnconfigure(2, weight=1)
        self.secondary_actions.grid(row=4, column=0, pady=(0, 0), sticky="ew")

        self.diagnostics_button = ctk.CTkButton(
            self.secondary_actions,
            text="Ver diagnóstico",
            command=self._handle_open_diagnostics,
            height=28,
            corner_radius=10,
            fg_color=NEUTRAL_BUTTON,
            hover_color=NEUTRAL_BUTTON_HOVER,
            text_color=TEXT_PRIMARY,
            font=ctk.CTkFont(size=10, weight="bold"),
        )
        self.diagnostics_button.grid(row=0, column=0, padx=(0, 6), sticky="ew")

        self.open_extensions_button = ctk.CTkButton(
            self.secondary_actions,
            text="Ver extensión",
            command=self._handle_open_extensions,
            height=28,
            corner_radius=10,
            fg_color=NEUTRAL_BUTTON,
            hover_color=NEUTRAL_BUTTON_HOVER,
            text_color=TEXT_PRIMARY,
            font=ctk.CTkFont(size=10, weight="bold"),
        )
        self.open_extensions_button.grid(row=0, column=1, padx=(0, 6), sticky="ew")

        self.open_browser_button = ctk.CTkButton(
            self.secondary_actions,
            text="Abrir navegador",
            command=self._handle_open_browser,
            height=28,
            corner_radius=10,
            fg_color=NEUTRAL_BUTTON,
            hover_color=NEUTRAL_BUTTON_HOVER,
            text_color=TEXT_PRIMARY,
            font=ctk.CTkFont(size=10, weight="bold"),
        )
        self.open_browser_button.grid(row=0, column=2, sticky="ew")

        self.result_wrap = ctk.CTkFrame(self, fg_color="transparent")
        self.result_wrap.grid_columnconfigure(0, weight=1)
        self.current_result_panel = CurrentResultPanel(self.result_wrap)
        self.extension_status_panel = ExtensionStatusPanel(self)
        self._apply_visual_layout()

    def set_compact_layout(self, compact: bool) -> None:
        self._compact = compact
        self._apply_visual_layout()

    def set_secondary_visual(self, secondary: bool) -> None:
        self._secondary_visual = secondary
        self._apply_visual_layout()

    def set_summary(self, text: str) -> None:
        self.summary_label.configure(text=text or "")

    def _apply_visual_layout(self) -> None:
        header_padx = 10
        header_pady = (8, 2)
        body_padx = 10
        body_pady = (0, 8)

        self.configure(corner_radius=18, height=self._MIN_CARD_HEIGHT)
        self.header.grid_configure(padx=header_padx, pady=header_pady)
        self.body.grid_configure(padx=body_padx, pady=body_pady)
        self.eyebrow.configure(font=ctk.CTkFont(size=12, weight="bold"))
        self.summary_label.configure(font=ctk.CTkFont(size=1))
        self.process_timer_label.configure(font=ctk.CTkFont(size=10, weight="bold"))
        self.run_button.configure(
            height=28,
            font=ctk.CTkFont(size=10, weight="bold"),
        )
        self.clear_button.configure(
            height=28,
            font=ctk.CTkFont(size=10, weight="bold"),
        )
        self.export_debug_button.configure(
            height=28,
            font=ctk.CTkFont(size=10, weight="bold"),
        )

        self.form_panel.set_compact_layout(True)
        self.status_panel.set_compact_layout(False)
        self.current_result_panel.set_compact_layout(True)
        self.extension_status_panel.set_compact_layout(True)
        self.secondary_actions.grid_remove()
        self.process_timer_label.grid_configure(row=0, column=1, pady=0, sticky="e")
        self.body.grid_columnconfigure(0, weight=1, uniform="slot_body")
        self.body.grid_columnconfigure(1, weight=1, uniform="slot_body")
        self.status_panel.grid_configure(row=0, column=1, columnspan=1, padx=(10, 0), pady=0, sticky="nsew")
        self.result_wrap.grid_forget()

    def _handle_open_diagnostics(self) -> None:
        if self._on_open_diagnostics is not None:
            self._on_open_diagnostics()

    def _handle_open_extensions(self) -> None:
        if self._on_open_extensions is not None:
            self._on_open_extensions()

    def _handle_open_browser(self) -> None:
        if self._on_open_browser is not None:
            self._on_open_browser()
