from __future__ import annotations

from pathlib import Path
import threading
import tkinter.filedialog as fd

import customtkinter as ctk

from core.models import UploadBatchProgress, UploadItemResult
from services.uploader_service import UploaderService
from ui.theme import (
    ACCENT,
    ACCENT_HOVER,
    BORDER,
    CARD_BG,
    ERROR,
    SECONDARY_BUTTON,
    SECONDARY_BUTTON_HOVER,
    SUCCESS,
    TEXT_MUTED,
    TEXT_PRIMARY,
)
from ui.uploader.file_list_panel import FileListPanel
from ui.uploader.upload_result_panel import UploadResultPanel


class UploaderPanel(ctk.CTkFrame):
    def __init__(
        self,
        master,
        uploader_service: UploaderService | None = None,
        *,
        title_text: str = "Carga masiva de JPG a Supabase",
        subtitle_text: str = (
            "Sube fotos al bucket, registra cada fila en photos y conserva "
            "el resultado por archivo."
        ),
        **kwargs,
    ) -> None:
        super().__init__(master, fg_color="transparent", **kwargs)
        self._uploader_service = uploader_service or UploaderService()
        self._selected_files: list[str] = []
        self._is_running = False
        self._last_progress = UploadBatchProgress()

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        self._build_header(title_text, subtitle_text)
        self._build_content()

    def _build_header(self, title_text: str, subtitle_text: str) -> None:
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, padx=4, pady=(4, 16), sticky="ew")
        header.grid_columnconfigure(0, weight=1)

        title_label = ctk.CTkLabel(
            header,
            text=title_text,
            font=ctk.CTkFont(family="Georgia", size=28, weight="bold"),
            text_color=TEXT_PRIMARY,
        )
        title_label.grid(row=0, column=0, sticky="w")

        subtitle_label = ctk.CTkLabel(
            header,
            text=subtitle_text,
            font=ctk.CTkFont(size=14),
            text_color=TEXT_MUTED,
            justify="left",
            wraplength=760,
        )
        subtitle_label.grid(row=1, column=0, pady=(6, 0), sticky="w")

    def _build_content(self) -> None:
        content = ctk.CTkFrame(self, fg_color="transparent")
        content.grid(row=1, column=0, sticky="nsew")
        content.grid_columnconfigure(0, weight=5)
        content.grid_columnconfigure(1, weight=6)
        content.grid_rowconfigure(1, weight=1)

        controls_card = ctk.CTkFrame(
            content,
            fg_color=CARD_BG,
            corner_radius=20,
            border_width=1,
            border_color=BORDER,
        )
        controls_card.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 16))
        controls_card.grid_columnconfigure(1, weight=1)

        self.select_button = ctk.CTkButton(
            controls_card,
            text="Seleccionar JPG",
            command=self._select_files,
            fg_color=ACCENT,
            hover_color=ACCENT_HOVER,
            text_color="#fff7f0",
            corner_radius=14,
            height=42,
        )
        self.select_button.grid(row=0, column=0, padx=18, pady=18, sticky="w")

        self.selection_label = ctk.CTkLabel(
            controls_card,
            text="0 archivos listos.",
            text_color=TEXT_PRIMARY,
            anchor="w",
        )
        self.selection_label.grid(row=0, column=1, padx=(12, 18), pady=18, sticky="ew")

        self.delete_local_checkbox = ctk.CTkCheckBox(
            controls_card,
            text="Borrar archivo local si sube bien",
            text_color=TEXT_PRIMARY,
            checkbox_width=20,
            checkbox_height=20,
            border_width=2,
        )
        self.delete_local_checkbox.grid(row=1, column=0, padx=18, pady=(0, 18), sticky="w")

        self.upload_button = ctk.CTkButton(
            controls_card,
            text="Subir archivos",
            command=self._start_upload,
            fg_color=SECONDARY_BUTTON,
            hover_color=SECONDARY_BUTTON_HOVER,
            corner_radius=14,
            height=42,
        )
        self.upload_button.grid(row=1, column=1, padx=18, pady=(0, 18), sticky="e")

        self.progress_label = ctk.CTkLabel(
            controls_card,
            text="Progreso: 0/0",
            text_color=TEXT_MUTED,
            anchor="w",
        )
        self.progress_label.grid(row=2, column=0, padx=18, pady=(0, 8), sticky="w")

        self.progress_bar = ctk.CTkProgressBar(controls_card, height=12, corner_radius=999)
        self.progress_bar.grid(row=2, column=1, padx=18, pady=(0, 8), sticky="ew")
        self.progress_bar.set(0)

        self.file_list_panel = FileListPanel(content)
        self.file_list_panel.grid(row=1, column=0, sticky="nsew", padx=(0, 10))

        self.result_panel = UploadResultPanel(content)
        self.result_panel.grid(row=1, column=1, sticky="nsew", padx=(10, 0))

        self.status_label = ctk.CTkLabel(
            self,
            text="Listo para cargar.",
            text_color=TEXT_MUTED,
            anchor="w",
        )
        self.status_label.grid(row=2, column=0, padx=4, pady=(0, 4), sticky="ew")

    def _select_files(self) -> None:
        selected = fd.askopenfilenames(
            title="Seleccionar imagenes JPG",
            filetypes=[("JPEG files", "*.jpg *.jpeg")],
        )
        self._selected_files = [str(Path(path)) for path in selected]
        self.file_list_panel.set_files(self._selected_files)
        self.result_panel.clear()
        self._reset_progress_state()
        self.selection_label.configure(text=f"{len(self._selected_files)} archivos listos.")
        if self._selected_files:
            self.status_label.configure(text="Archivos cargados en la lista.", text_color=TEXT_MUTED)
        else:
            self.status_label.configure(text="No se seleccionaron archivos.", text_color=TEXT_MUTED)

    def _start_upload(self) -> None:
        if self._is_running:
            return
        if not self._selected_files:
            self.status_label.configure(
                text="Selecciona al menos un archivo JPG antes de subir.",
                text_color=ERROR,
            )
            return
        self._is_running = True
        self._set_controls_state("disabled")
        self.result_panel.clear()
        self._reset_progress_state(total_files=len(self._selected_files))
        self.status_label.configure(text="Preparando archivos...", text_color=TEXT_PRIMARY)
        thread = threading.Thread(target=self._run_upload, daemon=True)
        thread.start()

    def _run_upload(self) -> None:
        try:
            results = self._uploader_service.upload_files(
                self._selected_files,
                delete_local_on_success=bool(self.delete_local_checkbox.get()),
                progress_callback=self._schedule_progress_update,
            )
            self.after(0, lambda: self._finish_upload(results))
        except Exception as exc:
            self.after(0, lambda: self._handle_unexpected_error(exc))

    def _schedule_progress_update(self, progress: UploadBatchProgress) -> None:
        self.after(0, lambda: self._apply_progress_update(progress))

    def _apply_progress_update(self, progress: UploadBatchProgress) -> None:
        self._last_progress = progress
        total = max(progress.total_files, 1)
        self.progress_bar.set(progress.processed_count / total)
        self.progress_label.configure(
            text=f"Progreso: {progress.processed_count}/{progress.total_files}"
        )
        self.result_panel.update_progress(progress)

        if progress.result is not None:
            self.file_list_panel.update_file_status(
                progress.result.source_path,
                progress.result.processing_status,
            )

        status_color = TEXT_PRIMARY
        if progress.failed_count:
            status_color = ERROR
        elif progress.processed_count and progress.processed_count == progress.total_files:
            status_color = SUCCESS
        self.status_label.configure(text=progress.status_text, text_color=status_color)

    def _finish_upload(self, results: list[UploadItemResult]) -> None:
        self._is_running = False
        self._set_controls_state("normal")
        self.result_panel.set_results(results)

        success_count = sum(1 for item in results if item.success)
        failed_count = len(results) - success_count
        warning_count = sum(
            1 for item in results if item.success and item.local_cleanup_error
        )
        if failed_count:
            self.status_label.configure(
                text=f"Proceso completado con {failed_count} fallo(s).",
                text_color=ERROR,
            )
        elif warning_count:
            self.status_label.configure(
                text=(
                    "Proceso completado con "
                    f"{warning_count} advertencia(s) de local cleanup."
                ),
                text_color=TEXT_PRIMARY,
            )
        else:
            self.status_label.configure(
                text=f"Proceso completado. {success_count} archivo(s) subidos.",
                text_color=SUCCESS,
            )

        self._selected_files = [item.source_path for item in results if not item.success]
        if self._selected_files:
            self.selection_label.configure(
                text=f"{len(self._selected_files)} archivo(s) listos para reintentar."
            )
        else:
            self.selection_label.configure(text="0 archivos pendientes.")

    def _handle_unexpected_error(self, exc: Exception) -> None:
        self._is_running = False
        self._set_controls_state("normal")
        self.status_label.configure(text=f"Error inesperado: {exc}", text_color=ERROR)

    def _set_controls_state(self, state: str) -> None:
        self.select_button.configure(state=state)
        self.upload_button.configure(state=state)
        self.delete_local_checkbox.configure(state=state)

    def _reset_progress_state(self, *, total_files: int = 0) -> None:
        self._last_progress = UploadBatchProgress(total_files=total_files)
        self.progress_bar.set(0)
        self.progress_label.configure(text=f"Progreso: 0/{total_files}")
