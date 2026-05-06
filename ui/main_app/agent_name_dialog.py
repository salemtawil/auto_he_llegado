from __future__ import annotations

import customtkinter as ctk

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
)


class AgentNameDialog(ctk.CTkToplevel):
    def __init__(self, master, *, current_value: str = "", on_submit=None, **kwargs) -> None:
        super().__init__(master, fg_color=APP_BG, **kwargs)
        self._on_submit = on_submit
        self.title("Nombre del agente")
        self.geometry("440x250")
        self.minsize(420, 230)
        self.resizable(False, False)
        self.transient(master)
        self.grab_set()
        self.protocol("WM_DELETE_WINDOW", self._handle_submit)

        container = ctk.CTkFrame(
            self,
            fg_color=CARD_BG,
            corner_radius=22,
            border_width=1,
            border_color=BORDER,
        )
        container.pack(fill="both", expand=True, padx=18, pady=18)
        container.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            container,
            text="Identifica esta instalacion",
            font=ctk.CTkFont(size=22, weight="bold"),
            text_color=TEXT_PRIMARY,
        ).grid(row=0, column=0, padx=22, pady=(22, 8), sticky="w")

        ctk.CTkLabel(
            container,
            text="Escribe el nombre del agente que usara esta PC. Se guardara localmente y no se pedira otra vez.",
            text_color=TEXT_MUTED,
            justify="left",
            wraplength=340,
        ).grid(row=1, column=0, padx=22, pady=(0, 14), sticky="ew")

        self.name_entry = ctk.CTkEntry(
            container,
            placeholder_text="Nombre del agente",
            corner_radius=14,
            height=44,
            border_width=1,
            border_color=BORDER,
        )
        self.name_entry.grid(row=2, column=0, padx=22, sticky="ew")
        if current_value:
            self.name_entry.insert(0, current_value)
            self.name_entry.select_range(0, "end")
        self.name_entry.bind("<Return>", self._handle_submit)

        self.feedback_label = ctk.CTkLabel(container, text="", text_color="#b44545", justify="left", wraplength=320)
        self.feedback_label.grid(row=3, column=0, padx=22, pady=(10, 0), sticky="ew")

        actions = ctk.CTkFrame(container, fg_color="transparent")
        actions.grid(row=4, column=0, padx=22, pady=(18, 22), sticky="ew")
        actions.grid_columnconfigure(0, weight=1)
        actions.grid_columnconfigure(1, weight=1)

        skip_button = ctk.CTkButton(
            actions,
            text="Guardar luego",
            command=self.destroy,
            height=42,
            corner_radius=14,
            fg_color=NEUTRAL_BUTTON,
            hover_color=NEUTRAL_BUTTON_HOVER,
            text_color=TEXT_PRIMARY,
        )
        skip_button.grid(row=0, column=0, padx=(0, 8), sticky="ew")

        submit_button = ctk.CTkButton(
            actions,
            text="Guardar nombre",
            command=self._handle_submit,
            height=42,
            corner_radius=14,
            fg_color=ACCENT,
            hover_color=ACCENT_HOVER,
        )
        submit_button.grid(row=0, column=1, padx=(8, 0), sticky="ew")

        self.after(100, self.name_entry.focus)

    def set_error(self, message: str) -> None:
        self.feedback_label.configure(text=message)
        self.name_entry.focus()
        self.name_entry.select_range(0, "end")

    def _handle_submit(self, _event=None) -> None:
        if self._on_submit is None:
            self.destroy()
            return
        self._on_submit(self.name_entry.get())
