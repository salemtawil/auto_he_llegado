from __future__ import annotations

import customtkinter as ctk

from core.models import UploadBatchProgress, UploadItemResult
from ui.theme import BORDER, CARD_ALT_BG, TEXT_MUTED, TEXT_PRIMARY


class UploadResultPanel(ctk.CTkFrame):
    def __init__(self, master, **kwargs) -> None:
        super().__init__(master, fg_color=CARD_ALT_BG, corner_radius=18, **kwargs)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(3, weight=1)

        title_label = ctk.CTkLabel(
            self,
            text="Resultados",
            font=ctk.CTkFont(size=18, weight="bold"),
            text_color=TEXT_PRIMARY,
        )
        title_label.grid(row=0, column=0, padx=18, pady=(18, 8), sticky="w")

        self.summary_label = ctk.CTkLabel(
            self,
            text="Sin ejecucion.",
            text_color=TEXT_MUTED,
            anchor="w",
        )
        self.summary_label.grid(row=1, column=0, padx=18, pady=(0, 8), sticky="ew")
        self.progress_label = ctk.CTkLabel(
            self,
            text="Esperando seleccion.",
            text_color=TEXT_MUTED,
            anchor="w",
        )
        self.progress_label.grid(row=2, column=0, padx=18, pady=(0, 8), sticky="ew")

        self.textbox = ctk.CTkTextbox(
            self,
            corner_radius=14,
            border_width=1,
            border_color=BORDER,
            fg_color=CARD_ALT_BG,
            text_color=TEXT_PRIMARY,
            wrap="word",
        )
        self.textbox.grid(row=3, column=0, padx=18, pady=(0, 18), sticky="nsew")
        self.textbox.configure(state="disabled")
        self._results_by_path: dict[str, UploadItemResult] = {}

    def set_results(self, results: list[UploadItemResult]) -> None:
        self._results_by_path = {
            item.source_path: item.model_copy(deep=True) for item in results
        }
        self._render_results()

    def update_progress(self, progress: UploadBatchProgress) -> None:
        self.summary_label.configure(
            text=(
                f"Procesadas: {progress.processed_count}/{progress.total_files} | "
                f"Exitosas: {progress.success_count} | Fallidas: {progress.failed_count}"
            )
        )
        self.progress_label.configure(text=progress.status_text, text_color=TEXT_PRIMARY)
        if progress.result is not None:
            self._results_by_path[progress.result.source_path] = progress.result.model_copy(
                deep=True
            )
            self._render_results()

    def _render_results(self) -> None:
        results = list(self._results_by_path.values())
        total = len(results)
        success_count = sum(1 for item in results if item.success)
        warning_count = sum(
            1 for item in results if item.success and item.local_cleanup_error
        )
        failed_count = total - success_count
        self.summary_label.configure(
            text=(
                f"Procesadas: {total} | Exitosas: {success_count} | "
                f"Fallidas: {failed_count} | Advertencias: {warning_count}"
            )
        )
        self.textbox.configure(state="normal")
        self.textbox.delete("1.0", "end")
        for item in results:
            state = "OK"
            if not item.success:
                state = "ERROR"
            elif item.local_cleanup_error:
                state = "WARN"
            self.textbox.insert(
                "end",
                f"[{state}] {item.original_filename}\n",
            )
            self.textbox.insert("end", f"Mensaje: {item.message}\n")
            self.textbox.insert(
                "end",
                "Storage upload: "
                f"{'OK' if item.storage_uploaded else 'ERROR'}"
                f"{f' | {item.storage_error}' if item.storage_error else ''}\n",
            )
            self.textbox.insert(
                "end",
                "Database insert: "
                f"{'OK' if item.database_inserted else 'ERROR'}"
                f"{f' | {item.database_error}' if item.database_error else ''}\n",
            )
            local_cleanup_state = "OK"
            local_cleanup_detail = item.local_cleanup_message
            if item.local_cleanup_error:
                local_cleanup_state = "ERROR"
                local_cleanup_detail = item.local_cleanup_error
            elif not item.local_cleanup_message:
                local_cleanup_state = "SKIPPED"
                local_cleanup_detail = "Sin accion local."
            self.textbox.insert(
                "end",
                "Local cleanup: "
                f"{local_cleanup_state}"
                f"{f' | {local_cleanup_detail}' if local_cleanup_detail else ''}\n",
            )
            if item.photo_id:
                self.textbox.insert("end", f"UUID: {item.photo_id}\n")
            if item.storage_path:
                self.textbox.insert("end", f"Storage: {item.storage_path}\n")
            if item.local_file_deleted:
                self.textbox.insert("end", "Archivo local eliminado tras subir.\n")
            if item.failed_file_path:
                self.textbox.insert("end", f"Movido a: {item.failed_file_path}\n")
            self.textbox.insert("end", "\n")
        self.textbox.configure(state="disabled")

    def clear(self) -> None:
        self._results_by_path = {}
        self.summary_label.configure(text="Sin ejecucion.", text_color=TEXT_MUTED)
        self.progress_label.configure(text="Esperando seleccion.", text_color=TEXT_MUTED)
        self.textbox.configure(state="normal")
        self.textbox.delete("1.0", "end")
        self.textbox.configure(state="disabled")
