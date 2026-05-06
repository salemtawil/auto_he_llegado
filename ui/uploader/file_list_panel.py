from __future__ import annotations

from pathlib import Path

import customtkinter as ctk

from ui.theme import BORDER, CARD_BG, TEXT_PRIMARY


class FileListPanel(ctk.CTkFrame):
    def __init__(self, master, **kwargs) -> None:
        super().__init__(
            master,
            fg_color=CARD_BG,
            corner_radius=18,
            border_width=1,
            border_color=BORDER,
            **kwargs,
        )
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        title_label = ctk.CTkLabel(
            self,
            text="Archivos seleccionados",
            font=ctk.CTkFont(size=18, weight="bold"),
            text_color=TEXT_PRIMARY,
        )
        title_label.grid(row=0, column=0, padx=18, pady=(18, 10), sticky="w")

        self.textbox = ctk.CTkTextbox(
            self,
            corner_radius=14,
            border_width=1,
            border_color=BORDER,
            fg_color=CARD_BG,
            text_color=TEXT_PRIMARY,
            wrap="none",
        )
        self.textbox.grid(row=1, column=0, padx=18, pady=(0, 18), sticky="nsew")
        self.textbox.configure(state="disabled")
        self._file_paths: list[str] = []
        self._statuses: dict[str, str] = {}
        self.set_files([])

    def set_files(self, file_paths: list[str]) -> None:
        self._file_paths = list(file_paths)
        self._statuses = {file_path: "Pendiente" for file_path in self._file_paths}
        self._render()

    def update_file_status(self, file_path: str, status: str) -> None:
        if file_path not in self._statuses:
            self._file_paths.append(file_path)
        self._statuses[file_path] = status
        self._render()

    def _render(self) -> None:
        self.textbox.configure(state="normal")
        self.textbox.delete("1.0", "end")
        if not self._file_paths:
            self.textbox.insert("end", "Todavia no has seleccionado imagenes JPG.\n")
        else:
            for index, file_path in enumerate(self._file_paths, start=1):
                path = Path(file_path)
                status = self._statuses.get(file_path, "Pendiente")
                self.textbox.insert("end", f"{index:02d}. {path.name} [{status}]\n")
                self.textbox.insert("end", f"    {path}\n\n")
        self.textbox.configure(state="disabled")
