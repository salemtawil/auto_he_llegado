from __future__ import annotations

import customtkinter as ctk

from core.validators import strip_phone_number
from ui.theme import ACCENT, ACCENT_SOFT, BORDER, CARD_BG, INPUT_BG, TEXT_MUTED, TEXT_PRIMARY, TEXT_SOFT


class FormPanel(ctk.CTkFrame):
    PAGE_OPTIONS = ["Compinche", "Paripe", "Ready4Drive"]
    ACTION_OPTIONS = ["He llegado instantáneo", "He llegado", "Selfie en ruta"]
    DEFAULT_PAGE = "Compinche"
    DEFAULT_ACTION = "He llegado"

    def __init__(self, master, **kwargs) -> None:
        super().__init__(master, fg_color=CARD_BG, corner_radius=22, border_width=1, border_color=BORDER, **kwargs)
        self.grid_columnconfigure(0, weight=1)
        self._phone_var = ctk.StringVar()
        self._is_syncing_phone = False
        self._phone_var.trace_add("write", self._sanitize_phone_in_place)
        self._compact_layout = False
        self._field_frames: list[ctk.CTkFrame] = []

        self.header_row = ctk.CTkFrame(self, fg_color="transparent")
        self.header_row.grid(row=0, column=0, padx=14, pady=(10, 4), sticky="ew")
        self.header_row.grid_columnconfigure(0, weight=1)

        self.header_text = ctk.CTkFrame(self.header_row, fg_color="transparent")
        self.header_text.grid(row=0, column=0, sticky="w")

        badge = ctk.CTkLabel(
            self.header_text,
            text="Panel operativo",
            corner_radius=999,
            fg_color=ACCENT_SOFT,
            text_color=ACCENT,
            padx=8,
            pady=3,
            font=ctk.CTkFont(size=9, weight="bold"),
        )
        badge.grid(row=0, column=0, sticky="w")

        title = ctk.CTkLabel(
            self.header_text,
            text="Datos principales",
            font=ctk.CTkFont(family="Georgia", size=16, weight="bold"),
            text_color=TEXT_PRIMARY,
        )
        title.grid(row=1, column=0, pady=(5, 0), sticky="w")

        self.actions_row = ctk.CTkFrame(self.header_row, fg_color="transparent")
        self.actions_row.grid(row=0, column=1, rowspan=2, padx=(12, 0), sticky="e")

        self.fields_wrap = ctk.CTkFrame(self, fg_color="transparent")
        self.fields_wrap.grid(row=1, column=0, padx=14, pady=(0, 8), sticky="ew")

        self.page_menu = self._build_option_field("Pagina", self.PAGE_OPTIONS)
        self.action_menu = self._build_option_field("Accion", self.ACTION_OPTIONS)
        self.phone_entry = self._build_entry_field("Telefono", "+58 4121234567", textvariable=self._phone_var)
        self.phone_entry.bind("<FocusOut>", self._handle_phone_focus_out)
        self.password_entry = self._build_entry_field("Contrasena", "Contrasena")

        self.set_compact_layout(False)
        self.reset_defaults()

    def get_actions_container(self) -> ctk.CTkFrame:
        return self.actions_row

    def _build_option_field(self, label: str, values: list[str]) -> ctk.CTkOptionMenu:
        frame = self._build_field_frame(label)
        menu = ctk.CTkOptionMenu(
            frame,
            values=values,
            corner_radius=10,
            height=32,
            dynamic_resizing=False,
            anchor="w",
            font=ctk.CTkFont(size=12, weight="bold"),
            dropdown_font=ctk.CTkFont(size=11),
        )
        menu.grid(row=1, column=0, sticky="ew")
        return menu

    def _build_entry_field(self, label: str, placeholder: str, *, textvariable=None) -> ctk.CTkEntry:
        frame = self._build_field_frame(label)
        entry = ctk.CTkEntry(
            frame,
            placeholder_text=placeholder,
            corner_radius=10,
            height=32,
            border_width=1,
            border_color=BORDER,
            textvariable=textvariable,
            fg_color=INPUT_BG,
            font=ctk.CTkFont(size=12),
        )
        entry.grid(row=1, column=0, sticky="ew")
        return entry

    def _build_field_frame(self, label: str) -> ctk.CTkFrame:
        frame = ctk.CTkFrame(self.fields_wrap, fg_color="transparent")
        frame.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            frame,
            text=label,
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color=TEXT_PRIMARY,
            anchor="w",
        ).grid(row=0, column=0, pady=(0, 3), sticky="w")
        self._field_frames.append(frame)
        return frame

    def set_compact_layout(self, compact: bool) -> None:
        if self._compact_layout == compact and all(frame.winfo_manager() for frame in self._field_frames):
            return
        self._compact_layout = compact
        for column in range(2):
            self.fields_wrap.grid_columnconfigure(column, weight=0)
        if compact:
            self.fields_wrap.grid_columnconfigure(0, weight=1)
            self.fields_wrap.grid_columnconfigure(1, weight=1)
            placements = (
                (self._field_frames[0], 0, 0),
                (self._field_frames[1], 0, 1),
                (self._field_frames[2], 1, 0),
                (self._field_frames[3], 1, 1),
            )
            action_padx = (0, 0)
        else:
            self.fields_wrap.grid_columnconfigure(0, weight=1)
            self.fields_wrap.grid_columnconfigure(1, weight=1)
            placements = (
                (self._field_frames[0], 0, 0),
                (self._field_frames[1], 0, 1),
                (self._field_frames[2], 1, 0),
                (self._field_frames[3], 1, 1),
            )
            action_padx = (16, 0)
        for frame in self._field_frames:
            frame.grid_forget()
        for frame, row, column in placements:
            frame.grid(row=row, column=column, padx=(0, 10) if column == 0 else 0, pady=(0, 7), sticky="ew")
        self.actions_row.grid_configure(padx=action_padx, pady=0, sticky="e" if not compact else "ew")

    def get_form_data(self) -> dict[str, str]:
        self._apply_phone_cleanup()
        return {
            "page_name": self.page_menu.get(),
            "action_name": self.action_menu.get(),
            "phone_number": self.phone_entry.get(),
            "password": self.password_entry.get(),
        }

    def clear(self) -> None:
        self.reset_defaults()
        self._phone_var.set("")
        self.password_entry.delete(0, "end")

    def reset_defaults(self) -> None:
        self.page_menu.set(self.DEFAULT_PAGE)
        self.action_menu.set(self.DEFAULT_ACTION)

    def _sanitize_phone_in_place(self, *_args) -> None:
        if self._is_syncing_phone:
            return
        cleaned = strip_phone_number(self._phone_var.get())[-10:]
        if cleaned == self._phone_var.get():
            return
        self._is_syncing_phone = True
        self._phone_var.set(cleaned)
        self._is_syncing_phone = False

    def _handle_phone_focus_out(self, _event) -> None:
        self._apply_phone_cleanup()

    def _apply_phone_cleanup(self) -> None:
        cleaned = strip_phone_number(self.phone_entry.get())[-10:]
        if cleaned != self.phone_entry.get():
            self._phone_var.set(cleaned)
