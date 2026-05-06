from __future__ import annotations

from tkinter import messagebox

import customtkinter as ctk

from core.models import LocalConfig
from ui.theme import (
    ACCENT,
    ACCENT_HOVER,
    APP_BG,
    BORDER,
    CARD_BG,
    NEUTRAL_BUTTON,
    NEUTRAL_BUTTON_HOVER,
    TEXT_MUTED,
    TEXT_PRIMARY,
    THEME_OPTIONS,
)


class SettingsDialog(ctk.CTkToplevel):
    def __init__(self, master, config: LocalConfig, on_save, **kwargs) -> None:
        super().__init__(master, fg_color=APP_BG, **kwargs)
        self._on_save = on_save
        self._initial_data = {
            "agent_name": config.agent_name,
            "flow_engine": "Extension" if config.flow_engine == "extension" else "Tradicional",
            "keep_browser_open": "si" if config.keep_browser_open else "no",
            "browser_extension_overlay": "si" if config.browser_extension_overlay else "no",
            "page_timeout_seconds": str(config.page_timeout_seconds),
            "action_timeout_seconds": str(config.action_timeout_seconds),
            "max_selfie_retries": str(config.max_selfie_retries),
            "last_result_filter": "solo exitoso" if config.last_result_filter == "success_only" else "general",
            "theme_mode": config.theme_mode,
        }
        self.title("Configuracion")
        self.geometry("460x620")
        self.minsize(400, 340)
        self.resizable(True, True)
        self.transient(master)
        self.grab_set()
        self.protocol("WM_DELETE_WINDOW", self._handle_cancel)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        container = ctk.CTkFrame(
            self,
            fg_color=CARD_BG,
            corner_radius=18,
            border_width=1,
            border_color=BORDER,
        )
        container.grid(row=0, column=0, padx=14, pady=14, sticky="nsew")
        container.grid_columnconfigure(0, weight=1)
        container.grid_rowconfigure(0, weight=1)

        body = ctk.CTkScrollableFrame(
            container,
            fg_color="transparent",
            corner_radius=0,
        )
        body.grid(row=0, column=0, padx=0, pady=0, sticky="nsew")
        body.grid_columnconfigure(0, weight=1)

        title = ctk.CTkLabel(
            body,
            text="Configuracion local",
            font=ctk.CTkFont(size=20, weight="bold"),
            text_color=TEXT_PRIMARY,
        )
        title.grid(row=0, column=0, padx=16, pady=(16, 6), sticky="w")

        subtitle = ctk.CTkLabel(
            body,
            text=(
                "Estos valores se guardan localmente solo cuando confirmas con "
                "'Guardar cambios'. Si cancelas, no se persiste nada."
            ),
            text_color=TEXT_MUTED,
            justify="left",
            wraplength=340,
            font=ctk.CTkFont(size=12),
        )
        subtitle.grid(row=1, column=0, padx=16, pady=(0, 12), sticky="ew")

        self.agent_entry = self._build_entry(
            body,
            row=2,
            label="agent_name",
            placeholder="Nombre del agente",
        )
        self.agent_entry.insert(0, config.agent_name)

        self.keep_browser_open_menu = self._build_option_menu(
            body,
            row=4,
            label="dejar navegador abierto al terminar",
            values=["si", "no"],
        )
        self.keep_browser_open_menu.set("si" if config.keep_browser_open else "no")

        self.flow_engine_menu = self._build_option_menu(
            body,
            row=6,
            label="motor de flujo",
            values=["Tradicional", "Extension"],
        )
        self.flow_engine_menu.set("Extension" if config.flow_engine == "extension" else "Tradicional")

        self.browser_extension_overlay_menu = self._build_option_menu(
            body,
            row=8,
            label="overlay visual de extension",
            values=["si", "no"],
        )
        self.browser_extension_overlay_menu.set("si" if config.browser_extension_overlay else "no")

        self.page_timeout_entry = self._build_entry(
            body,
            row=10,
            label="timeout de procesamiento de foto",
            placeholder="180",
        )
        self.page_timeout_entry.insert(0, str(config.page_timeout_seconds))

        self.action_timeout_entry = self._build_entry(
            body,
            row=12,
            label="timeout de respuesta final",
            placeholder="180",
        )
        self.action_timeout_entry.insert(0, str(config.action_timeout_seconds))

        self.max_selfie_retries_entry = self._build_entry(
            body,
            row=14,
            label="max_selfie_retries",
            placeholder="10, 0 o -1 para ilimitado",
        )
        self.max_selfie_retries_entry.insert(0, str(config.max_selfie_retries))

        self.last_result_filter_menu = self._build_option_menu(
            body,
            row=16,
            label="filtro por defecto de ultimo resultado",
            values=["general", "solo exitoso"],
        )
        self.last_result_filter_menu.set("solo exitoso" if config.last_result_filter == "success_only" else "general")

        self.theme_menu = self._build_option_menu(
            body,
            row=18,
            label="tema",
            values=THEME_OPTIONS,
        )
        self.theme_menu.set(config.theme_mode)
        self._wire_dirty_tracking()

        footer = ctk.CTkFrame(
            container,
            fg_color=CARD_BG,
            corner_radius=0,
            border_width=1,
            border_color=BORDER,
        )
        footer.grid(row=1, column=0, padx=0, pady=0, sticky="ew")
        actions = ctk.CTkFrame(footer, fg_color="transparent")
        actions.grid(row=0, column=0, padx=16, pady=16, sticky="ew")
        actions.grid_columnconfigure(0, weight=1)
        actions.grid_columnconfigure(1, weight=1)

        cancel_button = ctk.CTkButton(
            actions,
            text="Cancelar / Cerrar",
            command=self._handle_cancel,
            height=36,
            corner_radius=12,
            fg_color=NEUTRAL_BUTTON,
            hover_color=NEUTRAL_BUTTON_HOVER,
            text_color=TEXT_PRIMARY,
            font=ctk.CTkFont(size=13, weight="bold"),
        )
        cancel_button.grid(row=0, column=0, padx=(0, 8), sticky="ew")

        save_button = ctk.CTkButton(
            actions,
            text="Guardar cambios",
            command=self._handle_save,
            height=36,
            corner_radius=12,
            fg_color=ACCENT,
            hover_color=ACCENT_HOVER,
            font=ctk.CTkFont(size=13, weight="bold"),
        )
        save_button.grid(row=0, column=1, padx=(8, 0), sticky="ew")
        self.save_button = save_button
        self._sync_save_button_state()

    def _build_entry(
        self,
        master,
        *,
        row: int,
        label: str,
        placeholder: str,
    ) -> ctk.CTkEntry:
        label_widget = ctk.CTkLabel(
            master,
            text=label,
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color=TEXT_PRIMARY,
        )
        label_widget.grid(row=row, column=0, padx=16, pady=(4, 6), sticky="w")

        entry = ctk.CTkEntry(
            master,
            placeholder_text=placeholder,
            corner_radius=12,
            height=34,
            border_width=1,
            border_color=BORDER,
            font=ctk.CTkFont(size=13),
        )
        entry.grid(row=row + 1, column=0, padx=16, sticky="ew")
        return entry

    def _build_option_menu(
        self,
        master,
        *,
        row: int,
        label: str,
        values: list[str],
    ) -> ctk.CTkOptionMenu:
        label_widget = ctk.CTkLabel(
            master,
            text=label,
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color=TEXT_PRIMARY,
        )
        label_widget.grid(row=row, column=0, padx=16, pady=(4, 6), sticky="w")

        menu = ctk.CTkOptionMenu(
            master,
            values=values,
            corner_radius=12,
            height=34,
            dynamic_resizing=False,
            anchor="w",
            font=ctk.CTkFont(size=13),
            dropdown_font=ctk.CTkFont(size=13),
        )
        menu.grid(row=row + 1, column=0, padx=16, sticky="ew")
        return menu

    def _wire_dirty_tracking(self) -> None:
        self.agent_entry.bind("<KeyRelease>", self._handle_dirty_state_change)
        self.keep_browser_open_menu.configure(command=self._handle_theme_change)
        self.flow_engine_menu.configure(command=self._handle_theme_change)
        self.browser_extension_overlay_menu.configure(command=self._handle_theme_change)
        self.page_timeout_entry.bind("<KeyRelease>", self._handle_dirty_state_change)
        self.action_timeout_entry.bind("<KeyRelease>", self._handle_dirty_state_change)
        self.max_selfie_retries_entry.bind("<KeyRelease>", self._handle_dirty_state_change)
        self.last_result_filter_menu.configure(command=self._handle_theme_change)
        self.theme_menu.configure(command=self._handle_theme_change)

    def _handle_theme_change(self, value: str) -> None:
        self._handle_dirty_state_change()

    def _handle_dirty_state_change(self, _event=None) -> None:
        self._sync_save_button_state()

    def _sync_save_button_state(self) -> None:
        self.save_button.configure(state="normal" if self.has_unsaved_changes() else "disabled")

    def has_unsaved_changes(self) -> bool:
        return self._collect_form_data() != self._initial_data

    def _collect_form_data(self) -> dict[str, str]:
        return {
            "agent_name": self.agent_entry.get(),
            "flow_engine": self.flow_engine_menu.get(),
            "keep_browser_open": self.keep_browser_open_menu.get(),
            "browser_extension_overlay": self.browser_extension_overlay_menu.get(),
            "page_timeout_seconds": self.page_timeout_entry.get(),
            "action_timeout_seconds": self.action_timeout_entry.get(),
            "max_selfie_retries": self.max_selfie_retries_entry.get(),
            "last_result_filter": self.last_result_filter_menu.get(),
            "theme_mode": self.theme_menu.get(),
        }

    def _handle_cancel(self) -> None:
        if self.has_unsaved_changes():
            should_discard = messagebox.askyesno(
                "Descartar cambios",
                "Hay cambios sin guardar. ¿Quieres cerrar sin guardar?",
                parent=self,
            )
            if not should_discard:
                return
        self.destroy()

    def _handle_save(self) -> None:
        self._on_save(self._collect_form_data())
