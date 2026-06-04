from __future__ import annotations

import tkinter as tk
from typing import Callable

import customtkinter as ctk

from config.settings import Settings, get_settings
from ui.theme import (
    ACCENT,
    ACCENT_HOVER,
    APP_BG,
    BORDER,
    CARD_BG,
    ERROR,
    NEUTRAL_BUTTON,
    NEUTRAL_BUTTON_HOVER,
    TEXT_MUTED,
    TEXT_PRIMARY,
)


class StandaloneAdminAccessDialog(ctk.CTkToplevel):
    def __init__(
        self,
        master,
        *,
        prompt_text: str = "Acceso administrativo requerido",
        error_text: str = "",
        **kwargs,
    ) -> None:
        super().__init__(master, fg_color=APP_BG, **kwargs)
        self._result: str | None = None
        self.title("Acceso administrativo requerido")
        self.geometry("420x250")
        self.minsize(400, 230)
        self.resizable(False, False)
        self.transient(master)
        self.grab_set()
        self.protocol("WM_DELETE_WINDOW", self._handle_cancel)

        container = ctk.CTkFrame(
            self,
            fg_color=CARD_BG,
            corner_radius=22,
            border_width=1,
            border_color=BORDER,
        )
        container.pack(fill="both", expand=True, padx=18, pady=18)
        container.grid_columnconfigure(0, weight=1)

        title = ctk.CTkLabel(
            container,
            text=prompt_text,
            font=ctk.CTkFont(size=20, weight="bold"),
            text_color=TEXT_PRIMARY,
        )
        title.grid(row=0, column=0, padx=22, pady=(22, 8), sticky="w")

        subtitle = ctk.CTkLabel(
            container,
            text="Ingresa la clave admin para continuar.",
            text_color=TEXT_MUTED,
            justify="left",
            wraplength=320,
        )
        subtitle.grid(row=1, column=0, padx=22, pady=(0, 14), sticky="ew")

        self.password_entry = ctk.CTkEntry(
            container,
            placeholder_text="Clave admin",
            show="*",
            corner_radius=14,
            height=44,
            border_width=1,
            border_color=BORDER,
        )
        self.password_entry.grid(row=2, column=0, padx=22, sticky="ew")
        self.password_entry.bind("<Return>", self._handle_submit)

        self.feedback_label = ctk.CTkLabel(
            container,
            text=error_text,
            text_color=ERROR,
            justify="left",
            wraplength=320,
        )
        self.feedback_label.grid(row=3, column=0, padx=22, pady=(10, 0), sticky="ew")

        actions = ctk.CTkFrame(container, fg_color="transparent")
        actions.grid(row=4, column=0, padx=22, pady=(18, 22), sticky="ew")
        actions.grid_columnconfigure(0, weight=1)
        actions.grid_columnconfigure(1, weight=1)

        cancel_button = ctk.CTkButton(
            actions,
            text="Cancelar",
            command=self._handle_cancel,
            height=42,
            corner_radius=14,
            fg_color=NEUTRAL_BUTTON,
            hover_color=NEUTRAL_BUTTON_HOVER,
            text_color=TEXT_PRIMARY,
        )
        cancel_button.grid(row=0, column=0, padx=(0, 8), sticky="ew")

        submit_button = ctk.CTkButton(
            actions,
            text="Entrar",
            command=self._handle_submit,
            height=42,
            corner_radius=14,
            fg_color=ACCENT,
            hover_color=ACCENT_HOVER,
        )
        submit_button.grid(row=0, column=1, padx=(8, 0), sticky="ew")

        self.after(100, self.password_entry.focus)

    @property
    def result(self) -> str | None:
        return self._result

    def set_error(self, message: str) -> None:
        self.feedback_label.configure(text=message)
        self.password_entry.select_range(0, "end")
        self.password_entry.focus()

    def _handle_submit(self, _event=None) -> None:
        self._result = self.password_entry.get()
        self.destroy()

    def _handle_cancel(self) -> None:
        self._result = None
        self.destroy()


def is_admin_password_valid(password: str, settings: Settings | None = None) -> bool:
    return password == (settings or get_settings()).admin_access_password


def request_admin_access(
    *,
    parent=None,
    settings: Settings | None = None,
    dialog_factory: Callable[[], str | None] | None = None,
) -> bool:
    current_settings = settings or get_settings()
    if dialog_factory is not None:
        password = dialog_factory()
        return password is not None and is_admin_password_valid(password, current_settings)

    root = tk.Tk()
    root.withdraw()
    root.configure(bg=APP_BG)
    try:
        error_text = ""
        while True:
            dialog = StandaloneAdminAccessDialog(parent or root, error_text=error_text)
            dialog.wait_window()
            password = dialog.result
            if password is None:
                return False
            if is_admin_password_valid(password, current_settings):
                return True
            error_text = "Clave incorrecta."
    finally:
        root.destroy()
