from __future__ import annotations

import customtkinter as ctk
import tkinter as tk

from core.validators import strip_phone_number
from ui.theme import (
    ACCENT,
    ACCENT_HOVER,
    ACCENT_SOFT,
    BORDER,
    CARD_ALT_BG,
    CARD_BG,
    INPUT_BG,
    NEUTRAL_BUTTON,
    NEUTRAL_BUTTON_HOVER,
    TEXT_MUTED,
    TEXT_PRIMARY,
    TEXT_SOFT,
)


class FormPanel(ctk.CTkFrame):
    PAGE_OPTIONS = ["Compinche", "Paripe", "Ready4Drive"]
    ACTION_OPTIONS = ["He llegado instantáneo", "He llegado", "Selfie en ruta"]
    DEFAULT_PAGE = "Compinche"
    DEFAULT_ACTION = "He llegado"

    def __init__(self, master, *, on_owner_selfie_toggle=None, on_owner_selfie_select=None, on_owner_selfie_remove=None, **kwargs) -> None:
        super().__init__(master, fg_color=CARD_BG, corner_radius=18, border_width=1, border_color=BORDER, **kwargs)
        self.grid_columnconfigure(0, weight=1)
        self._phone_var = ctk.StringVar()
        self._owner_selfie_var = ctk.BooleanVar(value=False)
        self._is_syncing_phone = False
        self._phone_var.trace_add("write", self._sanitize_phone_in_place)
        self._compact_layout = False
        self._field_frames: list[ctk.CTkFrame] = []
        self._entry_context_menus: list[tk.Menu] = []
        self._owner_selfie_path: str | None = None
        self._on_owner_selfie_toggle = on_owner_selfie_toggle
        self._on_owner_selfie_select = on_owner_selfie_select
        self._on_owner_selfie_remove = on_owner_selfie_remove

        self.header_row = ctk.CTkFrame(self, fg_color="transparent")
        self.header_row.grid(row=0, column=0, padx=10, pady=(6, 1), sticky="ew")
        self.header_row.grid_columnconfigure(0, weight=1)

        self.header_text = ctk.CTkFrame(self.header_row, fg_color="transparent")
        self.header_text.grid(row=0, column=0, sticky="w")

        title = ctk.CTkLabel(
            self.header_text,
            text="Datos del proceso",
            font=ctk.CTkFont(size=10, weight="bold"),
            text_color=TEXT_PRIMARY,
        )
        title.grid(row=0, column=0, pady=(0, 0), sticky="w")

        self.fields_wrap = ctk.CTkFrame(self, fg_color="transparent")
        self.fields_wrap.grid(row=1, column=0, padx=10, pady=(0, 4), sticky="ew")

        self.owner_selfie_row = ctk.CTkFrame(self, fg_color="transparent")
        self.owner_selfie_row.grid(row=2, column=0, padx=10, pady=(0, 6), sticky="ew")
        self.owner_selfie_row.grid_columnconfigure(0, weight=0)
        self.owner_selfie_row.grid_columnconfigure(1, weight=0)
        self.owner_selfie_row.grid_columnconfigure(2, weight=0)
        self.owner_selfie_row.grid_columnconfigure(3, weight=1)

        self.actions_row = ctk.CTkFrame(self, fg_color="transparent")
        self.actions_row.grid(row=3, column=0, padx=12, pady=(4, 12), sticky="ew")
        self.actions_row.grid_columnconfigure(0, weight=1)

        self.actions_inner = ctk.CTkFrame(self.actions_row, fg_color="transparent")
        self.actions_inner.grid(row=0, column=0, padx=(4, 4), sticky="ew")

        self.page_menu = self._build_option_field("Pagina", self.PAGE_OPTIONS)
        self.action_menu = self._build_option_field("Accion", self.ACTION_OPTIONS)
        self.phone_entry = self._build_entry_field("Telefono", "+58 4121234567", textvariable=self._phone_var)
        self.phone_entry.bind("<FocusOut>", self._handle_phone_focus_out)
        self.password_entry = self._build_entry_field("Contrasena", "Contrasena")
        self.password_entry.bind("<KeyRelease>", self._sanitize_password_in_place)
        self.password_entry.bind("<FocusOut>", self._sanitize_password_in_place)
        self._attach_entry_context_menu(self.phone_entry)
        self._attach_entry_context_menu(self.password_entry)
        self.owner_selfie_checkbox = ctk.CTkCheckBox(
            self.owner_selfie_row,
            text="Selfie titular",
            variable=self._owner_selfie_var,
            command=self._handle_owner_selfie_toggle,
            checkbox_width=14,
            checkbox_height=14,
            width=116,
            font=ctk.CTkFont(size=9, weight="bold"),
            text_color=TEXT_PRIMARY,
        )
        self.owner_selfie_checkbox.grid(row=0, column=0, sticky="w")
        self.owner_selfie_button = ctk.CTkButton(
            self.owner_selfie_row,
            text="Foto",
            command=self._handle_owner_selfie_select,
            height=24,
            width=62,
            corner_radius=10,
            fg_color=NEUTRAL_BUTTON,
            hover_color=NEUTRAL_BUTTON_HOVER,
            text_color=TEXT_PRIMARY,
            font=ctk.CTkFont(size=9, weight="bold"),
        )
        self.owner_selfie_button.grid(row=0, column=1, padx=(6, 8), sticky="w")
        self.owner_selfie_remove_button = ctk.CTkButton(
            self.owner_selfie_row,
            text="Quitar",
            command=self._handle_owner_selfie_remove,
            height=24,
            width=68,
            corner_radius=10,
            fg_color=NEUTRAL_BUTTON,
            hover_color=NEUTRAL_BUTTON_HOVER,
            text_color=TEXT_PRIMARY,
            font=ctk.CTkFont(size=9, weight="bold"),
            state="disabled",
        )
        self.owner_selfie_remove_button.grid(row=0, column=2, padx=(0, 8), sticky="w")
        self.owner_selfie_label = ctk.CTkLabel(
            self.owner_selfie_row,
            text="Sin foto",
            text_color=TEXT_MUTED,
            font=ctk.CTkFont(size=9),
            anchor="w",
        )
        self.owner_selfie_label.grid(row=0, column=3, sticky="ew")

        self._style_controls()

        self.set_compact_layout(False)
        self.reset_defaults()

    def get_actions_container(self) -> ctk.CTkFrame:
        return self.actions_inner

    def _build_option_field(self, label: str, values: list[str]) -> ctk.CTkOptionMenu:
        frame = self._build_field_frame(label)
        menu = ctk.CTkOptionMenu(
            frame,
            values=values,
            corner_radius=10,
            height=28,
            dynamic_resizing=False,
            anchor="w",
            font=ctk.CTkFont(size=10, weight="bold"),
            dropdown_font=ctk.CTkFont(size=10),
        )
        menu.grid(row=1, column=0, sticky="ew")
        return menu

    def _build_entry_field(self, label: str, placeholder: str, *, textvariable=None) -> ctk.CTkEntry:
        frame = self._build_field_frame(label)
        entry = ctk.CTkEntry(
            frame,
            placeholder_text=placeholder,
            corner_radius=10,
            height=28,
            border_width=1,
            border_color=BORDER,
            textvariable=textvariable,
            fg_color=INPUT_BG,
            font=ctk.CTkFont(size=10),
        )
        entry.grid(row=1, column=0, sticky="ew")
        return entry

    def _build_field_frame(self, label: str) -> ctk.CTkFrame:
        frame = ctk.CTkFrame(self.fields_wrap, fg_color="transparent")
        frame.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            frame,
            text=label,
            font=ctk.CTkFont(size=9, weight="bold"),
            text_color=TEXT_PRIMARY,
            anchor="w",
        ).grid(row=0, column=0, pady=(0, 1), sticky="w")
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
            action_padx = (12, 12)
            action_pady = (4, 12)
        else:
            self.fields_wrap.grid_columnconfigure(0, weight=1)
            self.fields_wrap.grid_columnconfigure(1, weight=1)
            placements = (
                (self._field_frames[0], 0, 0),
                (self._field_frames[1], 0, 1),
                (self._field_frames[2], 1, 0),
                (self._field_frames[3], 1, 1),
            )
            action_padx = (12, 12)
            action_pady = (4, 12)
        for frame in self._field_frames:
            frame.grid_forget()
        for frame, row, column in placements:
            frame.grid(row=row, column=column, padx=(0, 8) if column == 0 else 0, pady=(0, 4), sticky="ew")
        self.actions_row.grid_configure(padx=action_padx, pady=action_pady, sticky="ew")

    def _style_controls(self) -> None:
        controls = (self.page_menu, self.action_menu)
        for control in controls:
            control.configure(
                fg_color=INPUT_BG,
                button_color=ACCENT,
                button_hover_color=ACCENT_HOVER,
                text_color=TEXT_PRIMARY,
                dropdown_fg_color=CARD_ALT_BG,
                dropdown_hover_color=ACCENT_SOFT,
                dropdown_text_color=TEXT_PRIMARY,
            )

    def get_form_data(self) -> dict[str, str]:
        self._apply_phone_cleanup()
        self._sanitize_password_in_place()
        return {
            "page_name": self.page_menu.get(),
            "action_name": self.action_menu.get(),
            "phone_number": self.phone_entry.get(),
            "password": self.password_entry.get(),
        }

    def get_owner_selfie_data(self) -> dict[str, object]:
        return {
            "owner_selfie_enabled": bool(self._owner_selfie_var.get()),
            "owner_selfie_path": self._owner_selfie_path,
        }

    def set_owner_selfie_state(self, *, enabled: bool, path: str | None) -> None:
        self._owner_selfie_var.set(enabled)
        self._owner_selfie_path = path
        self.owner_selfie_label.configure(text=self._owner_selfie_display_name(path))
        self.owner_selfie_remove_button.configure(state="normal" if path else "disabled")

    def clear(self) -> None:
        self.reset_defaults()
        self._phone_var.set("")
        self.password_entry.delete(0, "end")
        self.set_owner_selfie_state(enabled=False, path=None)

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

    def _sanitize_password_in_place(self, _event=None) -> None:
        cleaned = self.sanitize_password(self.password_entry.get())
        if cleaned == self.password_entry.get():
            return
        cursor_index = self.password_entry.index("insert")
        self.password_entry.delete(0, "end")
        self.password_entry.insert(0, cleaned)
        self.password_entry.icursor(min(cursor_index, len(cleaned)))

    @staticmethod
    def sanitize_password(value: str) -> str:
        return "".join(str(value or "").split())

    @staticmethod
    def _owner_selfie_display_name(path: str | None) -> str:
        if not path:
            return "Sin foto"
        filename = path.split("\\")[-1].split("/")[-1]
        if len(filename) <= 18:
            return filename
        stem, dot, suffix = filename.rpartition(".")
        if not dot:
            return filename[:15] + "..."
        trimmed_stem = stem[:11] + "..." if len(stem) > 14 else stem
        return f"{trimmed_stem}.{suffix}"

    def _handle_owner_selfie_toggle(self) -> None:
        if callable(self._on_owner_selfie_toggle):
            self._on_owner_selfie_toggle(bool(self._owner_selfie_var.get()))

    def _handle_owner_selfie_select(self) -> None:
        if callable(self._on_owner_selfie_select):
            self._on_owner_selfie_select()

    def _handle_owner_selfie_remove(self) -> None:
        if callable(self._on_owner_selfie_remove):
            self._on_owner_selfie_remove()

    def _attach_entry_context_menu(self, entry: ctk.CTkEntry) -> None:
        menu = tk.Menu(self, tearoff=0)
        menu.add_command(label="Cortar", command=lambda current_entry=entry: self._safe_entry_event(current_entry, "<<Cut>>"))
        menu.add_command(label="Copiar", command=lambda current_entry=entry: self._safe_entry_event(current_entry, "<<Copy>>"))
        menu.add_command(label="Pegar", command=lambda current_entry=entry: self._safe_entry_event(current_entry, "<<Paste>>"))
        menu.add_separator()
        menu.add_command(label="Seleccionar todo", command=lambda current_entry=entry: self._select_all_entry_text(current_entry))
        self._entry_context_menus.append(menu)

        def show_context_menu(event, *, current_entry=entry, current_menu=menu):
            try:
                current_entry.focus_force()
                current_menu.tk_popup(event.x_root, event.y_root)
            finally:
                current_menu.grab_release()
            return "break"

        for sequence in ("<Button-3>", "<Button-2>", "<Control-Button-1>"):
            entry.bind(sequence, show_context_menu, add="+")

    @staticmethod
    def _safe_entry_event(entry: ctk.CTkEntry, event_name: str) -> None:
        try:
            entry.focus_force()
            entry.event_generate(event_name)
        except Exception:
            return

    @staticmethod
    def _select_all_entry_text(entry: ctk.CTkEntry) -> None:
        try:
            entry.focus_force()
            entry.select_range(0, "end")
            entry.icursor("end")
        except Exception:
            return
