from __future__ import annotations

from pathlib import Path

import customtkinter as ctk

from ui.theme import BORDER, CARD_BG, TEXT_PRIMARY


class FileListPanel(ctk.CTkFrame):
    _PREVIEW_LIMIT = 100
    _RECENT_ERROR_LIMIT = 10

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
        self.grid_rowconfigure(2, weight=1)

        title_label = ctk.CTkLabel(
            self,
            text="Archivos seleccionados",
            font=ctk.CTkFont(size=18, weight="bold"),
            text_color=TEXT_PRIMARY,
        )
        title_label.grid(row=0, column=0, padx=18, pady=(18, 10), sticky="w")

        self.summary_label = ctk.CTkLabel(
            self,
            text="Sin archivos seleccionados.",
            text_color=TEXT_PRIMARY,
            anchor="w",
            justify="left",
        )
        self.summary_label.grid(row=1, column=0, padx=18, pady=(0, 8), sticky="ew")

        self.textbox = ctk.CTkTextbox(
            self,
            corner_radius=14,
            border_width=1,
            border_color=BORDER,
            fg_color=CARD_BG,
            text_color=TEXT_PRIMARY,
            wrap="none",
        )
        self.textbox.grid(row=2, column=0, padx=18, pady=(0, 18), sticky="nsew")
        self.textbox.configure(state="disabled")
        self._file_paths: list[str] = []
        self._statuses: dict[str, str] = {}
        self._completed_paths: set[str] = set()
        self._error_paths: set[str] = set()
        self._recent_error_paths: list[str] = []
        self._upload_active = False
        self._last_updated_path: str | None = None
        self._last_updated_status: str | None = None
        self.set_files([])

    def set_files(self, file_paths: list[str]) -> None:
        self._file_paths = list(file_paths)
        self._statuses = {file_path: "Pendiente" for file_path in self._file_paths}
        self._completed_paths = set()
        self._error_paths = set()
        self._recent_error_paths = []
        self._last_updated_path = None
        self._last_updated_status = None
        self._upload_active = False
        self._render_selection_view()

    def update_file_status(self, file_path: str, status: str) -> None:
        self.apply_status_updates({file_path: status})

    def apply_status_updates(self, updates: dict[str, str]) -> None:
        if not updates:
            return
        for file_path, status in updates.items():
            self._update_status_state(file_path, status)
        if self._upload_active:
            self._render_compact_view()
        else:
            self._render_selection_view()

    def set_upload_active(self, active: bool) -> None:
        self._upload_active = active
        if active:
            self._render_compact_view()
        else:
            self._render_selection_view()

    def _update_status_state(self, file_path: str, status: str) -> None:
        if file_path not in self._statuses:
            self._file_paths.append(file_path)
            self._statuses[file_path] = "Pendiente"
        previous_status = self._statuses.get(file_path, "Pendiente")
        self._statuses[file_path] = status
        self._last_updated_path = file_path
        self._last_updated_status = status

        if self._is_terminal_status(previous_status):
            self._completed_paths.discard(file_path)
        if self._is_error_status(previous_status):
            self._error_paths.discard(file_path)

        if self._is_terminal_status(status):
            self._completed_paths.add(file_path)
        if self._is_error_status(status):
            self._error_paths.add(file_path)
            self._remember_recent_error(file_path)

    def _remember_recent_error(self, file_path: str) -> None:
        if file_path in self._recent_error_paths:
            self._recent_error_paths.remove(file_path)
        self._recent_error_paths.append(file_path)
        if len(self._recent_error_paths) > self._RECENT_ERROR_LIMIT:
            self._recent_error_paths = self._recent_error_paths[-self._RECENT_ERROR_LIMIT :]

    def _render_selection_view(self) -> None:
        total = len(self._file_paths)
        if total == 0:
            self.summary_label.configure(text="Sin archivos seleccionados.")
        else:
            pending_count = total - len(self._completed_paths)
            self.summary_label.configure(
                text=(
                    f"Total: {total} | Pendientes: {pending_count} | "
                    f"Procesados: {len(self._completed_paths)} | Errores: {len(self._error_paths)}"
                )
            )
        self.textbox.configure(state="normal")
        self.textbox.delete("1.0", "end")
        if total == 0:
            self.textbox.insert("end", "Todavia no has seleccionado imagenes JPG.\n")
        else:
            display_paths = self._build_preview_paths()
            for index, file_path in display_paths:
                path = Path(file_path)
                status = self._statuses.get(file_path, "Pendiente")
                self.textbox.insert("end", f"{index:02d}. {path.name} [{status}]\n")
                self.textbox.insert("end", f"    {path}\n\n")
            if total > len(display_paths):
                self.textbox.insert(
                    "end",
                    (
                        f"... lista resumida. Mostrando {len(display_paths)} de {total} archivos. "
                        "El resto permanece en memoria.\n"
                    ),
                )
        self.textbox.configure(state="disabled")

    def _render_compact_view(self) -> None:
        total = len(self._file_paths)
        processed_count = len(self._completed_paths)
        pending_count = max(total - processed_count, 0)
        last_detail = "Sin actividad todavia."
        if self._last_updated_path and self._last_updated_status:
            last_detail = (
                f"Ultimo archivo: {Path(self._last_updated_path).name} "
                f"[{self._last_updated_status}]"
            )
        self.summary_label.configure(
            text=(
                f"Total: {total} | Pendientes: {pending_count} | "
                f"Procesados: {processed_count} | Errores: {len(self._error_paths)}"
            )
        )
        lines = [last_detail]
        if self._recent_error_paths:
            lines.append("")
            lines.append("Errores recientes:")
            for file_path in self._recent_error_paths:
                lines.append(
                    f"- {Path(file_path).name} [{self._statuses.get(file_path, 'Error')}]"
                )
        self.textbox.configure(state="normal")
        self.textbox.delete("1.0", "end")
        self.textbox.insert("end", "\n".join(lines) + "\n")
        self.textbox.configure(state="disabled")

    def _build_preview_paths(self) -> list[tuple[int, str]]:
        total = len(self._file_paths)
        if total <= self._PREVIEW_LIMIT:
            return list(enumerate(self._file_paths, start=1))
        head_size = self._PREVIEW_LIMIT // 2
        tail_start = total - head_size
        preview: list[tuple[int, str]] = []
        for index, file_path in enumerate(self._file_paths[:head_size], start=1):
            preview.append((index, file_path))
        for index, file_path in enumerate(
            self._file_paths[tail_start:],
            start=tail_start + 1,
        ):
            preview.append((index, file_path))
        return preview

    @staticmethod
    def _is_terminal_status(status: str) -> bool:
        return status in {"Completado", "Error"} or "failed_uploads" in status

    @staticmethod
    def _is_error_status(status: str) -> bool:
        return status == "Error" or "failed_uploads" in status
