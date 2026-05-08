from __future__ import annotations

import customtkinter as ctk

from core.models import UploadBatchProgress, UploadItemResult
from ui.theme import BORDER, CARD_ALT_BG, TEXT_MUTED, TEXT_PRIMARY


class UploadResultPanel(ctk.CTkFrame):
    _RECENT_SUCCESS_LIMIT = 100

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
        self._result_order: list[str] = []

    def set_results(self, results: list[UploadItemResult]) -> None:
        self._results_by_path = {}
        self._result_order = []
        self.apply_result_updates(results)
        self._render_results()

    def update_progress(self, progress: UploadBatchProgress) -> None:
        self.summary_label.configure(
            text=(
                f"Procesadas: {progress.processed_count}/{progress.total_files} | "
                f"Exitosas: {progress.success_count} | "
                f"Pendientes DB: {progress.pending_count} | "
                f"Fallidas: {progress.failed_count}"
            )
        )
        self.progress_label.configure(text=progress.status_text, text_color=TEXT_PRIMARY)

    def apply_result_updates(self, results: list[UploadItemResult]) -> None:
        if not results:
            return
        for item in results:
            if item.source_path not in self._results_by_path:
                self._result_order.append(item.source_path)
            self._results_by_path[item.source_path] = item
        self._render_results()

    def _render_results(self) -> None:
        results = [self._results_by_path[path] for path in self._result_order]
        total = len(results)
        success_count = sum(1 for item in results if self._is_success(item))
        pending_count = sum(1 for item in results if self._is_pending_db(item))
        warning_count = sum(
            1 for item in results if item.success and item.local_cleanup_error
        )
        failed_count = sum(1 for item in results if self._is_failed(item))
        self.summary_label.configure(
            text=(
                f"Procesadas: {total} | Exitosas: {success_count} | "
                f"Pendientes DB: {pending_count} | "
                f"Fallidas: {failed_count} | Advertencias: {warning_count}"
            )
        )
        noteworthy = [
            item
            for item in results
            if self._is_pending_db(item) or self._is_failed(item) or item.local_cleanup_error
        ]
        recent_ok = [
            item
            for item in results
            if item.success and not item.local_cleanup_error
        ][-self._RECENT_SUCCESS_LIMIT :]
        noteworthy_paths = {entry.source_path for entry in noteworthy}
        display_results = noteworthy + [
            item for item in recent_ok if item.source_path not in noteworthy_paths
        ]
        self.textbox.configure(state="normal")
        self.textbox.delete("1.0", "end")
        if not display_results:
            self.textbox.insert("end", "Todavia no hay resultados.\n")
        else:
            self.textbox.insert(
                "end",
                (
                    f"Mostrando {len(display_results)} resultado(s): "
                    f"{len(noteworthy)} incidencia(s) + hasta {self._RECENT_SUCCESS_LIMIT} exitos recientes.\n\n"
                ),
            )
        for item in display_results:
            state = "OK"
            if self._is_failed(item):
                state = "ERROR"
            elif item.local_cleanup_error:
                state = "WARN"
            elif self._is_pending_db(item):
                state = "PENDIENTE DB"
            self.textbox.insert(
                "end",
                f"[{state}] {item.original_filename}\n",
            )
            self.textbox.insert("end", f"Mensaje: {item.message}\n")
            storage_state = "OK" if item.storage_uploaded else "ERROR"
            if not item.storage_uploaded and item.storage_error is None:
                storage_state = "PENDIENTE"
            self.textbox.insert(
                "end",
                "Storage upload: "
                f"{storage_state}"
                f"{f' | {item.storage_error}' if item.storage_error else ''}\n",
            )
            database_state = "SKIPPED"
            if item.database_inserted:
                database_state = "OK"
            elif item.database_error:
                database_state = "ERROR"
            elif item.storage_uploaded:
                database_state = "PENDIENTE"
            self.textbox.insert(
                "end",
                "Database insert: "
                f"{database_state}"
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

    @staticmethod
    def _is_success(item: UploadItemResult) -> bool:
        return item.success and item.database_inserted

    @staticmethod
    def _is_pending_db(item: UploadItemResult) -> bool:
        return (
            item.storage_uploaded
            and not item.database_inserted
            and item.database_error is None
        )

    @staticmethod
    def _is_failed(item: UploadItemResult) -> bool:
        return (
            item.storage_error is not None
            or item.database_error is not None
            or item.processing_status in {"Error", "Movido a failed_uploads"}
        )

    def clear(self) -> None:
        self._results_by_path = {}
        self._result_order = []
        self.summary_label.configure(text="Sin ejecucion.", text_color=TEXT_MUTED)
        self.progress_label.configure(text="Esperando seleccion.", text_color=TEXT_MUTED)
        self.textbox.configure(state="normal")
        self.textbox.delete("1.0", "end")
        self.textbox.configure(state="disabled")
