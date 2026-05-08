from __future__ import annotations

from pathlib import Path
import threading
import time
import tkinter.filedialog as fd
from collections import deque

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
        self._pending_progress: UploadBatchProgress | None = None
        self._pending_result_updates: dict[str, UploadItemResult] = {}
        self._pending_file_statuses: dict[str, str] = {}
        self._progress_update_scheduled = False
        self._last_ui_update_at = 0.0
        self._ui_update_interval_ms = 300
        self._upload_started_at: float | None = None
        self._progress_callbacks_received = 0
        self._ui_updates_applied = 0
        self._processed_milestones: dict[int, float] = {}
        self._recent_progress_samples: deque[tuple[float, int]] = deque(maxlen=8)

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
        self.file_list_panel.set_upload_active(True)
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
        self._progress_callbacks_received += 1
        self._pending_progress = progress
        if progress.result is not None:
            self._pending_result_updates[progress.result.source_path] = progress.result
            self._pending_file_statuses[progress.result.source_path] = (
                progress.result.processing_status
            )
        if self._progress_update_scheduled:
            return
        force_immediate = (
            progress.current_index == 0
            or progress.total_files == 0
            or progress.processed_count == progress.total_files
            or progress.status_text == "Finalizado"
        )
        delay_ms = 0
        if not force_immediate:
            elapsed_ms = int((time.monotonic() - self._last_ui_update_at) * 1000)
            delay_ms = max(self._ui_update_interval_ms - elapsed_ms, 0)
        self._progress_update_scheduled = True
        self.after(delay_ms, self._drain_pending_progress)

    def _drain_pending_progress(self) -> None:
        self._progress_update_scheduled = False
        progress = self._pending_progress
        self._pending_progress = None
        if progress is None:
            return
        result_updates = list(self._pending_result_updates.values())
        file_statuses = dict(self._pending_file_statuses)
        self._pending_result_updates.clear()
        self._pending_file_statuses.clear()
        self._apply_progress_update(
            progress,
            result_updates=result_updates,
            file_statuses=file_statuses,
        )

    def _apply_progress_update(
        self,
        progress: UploadBatchProgress,
        *,
        result_updates: list[UploadItemResult],
        file_statuses: dict[str, str],
    ) -> None:
        self._last_progress = progress
        self._last_ui_update_at = time.monotonic()
        self._ui_updates_applied += 1
        total = max(progress.total_files, 1)
        self.progress_bar.set(progress.processed_count / total)
        self.progress_label.configure(
            text=f"Progreso: {progress.processed_count}/{progress.total_files}"
        )
        self._record_metrics(progress)
        self.result_panel.update_progress(progress)
        self.result_panel.apply_result_updates(result_updates)
        self.file_list_panel.apply_status_updates(file_statuses)

        self.status_label.configure(
            text=self._build_status_text(progress),
            text_color=self._resolve_status_color(progress),
        )

    def _finish_upload(self, results: list[UploadItemResult]) -> None:
        if self._pending_progress is not None:
            self._drain_pending_progress()
        self._is_running = False
        self._set_controls_state("normal")
        self.file_list_panel.set_upload_active(False)
        self.result_panel.set_results(results)

        success_count = sum(1 for item in results if item.success)
        failed_count = sum(1 for item in results if self._is_failed_result(item))
        pending_count = sum(1 for item in results if self._is_pending_db_result(item))
        warning_count = sum(
            1 for item in results if item.success and item.local_cleanup_error
        )
        elapsed_seconds = self._elapsed_seconds()
        average_speed = self._calculate_average_speed(len(results))
        if failed_count:
            self.status_label.configure(
                text=(
                    f"Proceso completado | OK {success_count} | Pendientes DB {pending_count} | "
                    f"Fallos {failed_count} | "
                    f"Tiempo {elapsed_seconds:.1f}s | Velocidad {average_speed:.1f} fotos/min"
                ),
                text_color=ERROR,
            )
        elif warning_count:
            self.status_label.configure(
                text=(
                    f"Proceso completado | OK {success_count} | Pendientes DB {pending_count} | "
                    f"Advertencias {warning_count} | "
                    f"Tiempo {elapsed_seconds:.1f}s | Velocidad {average_speed:.1f} fotos/min"
                ),
                text_color=TEXT_PRIMARY,
            )
        else:
            self.status_label.configure(
                text=(
                    f"Proceso completado | OK {success_count} | Pendientes DB {pending_count} | "
                    f"Fallos 0 | "
                    f"Tiempo {elapsed_seconds:.1f}s | Velocidad {average_speed:.1f} fotos/min"
                ),
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
        self.file_list_panel.set_upload_active(False)
        self.status_label.configure(text=f"Error inesperado: {exc}", text_color=ERROR)

    def _set_controls_state(self, state: str) -> None:
        self.select_button.configure(state=state)
        self.upload_button.configure(state=state)
        self.delete_local_checkbox.configure(state=state)

    def _reset_progress_state(self, *, total_files: int = 0) -> None:
        self._last_progress = UploadBatchProgress(total_files=total_files)
        self._pending_progress = None
        self._pending_result_updates = {}
        self._pending_file_statuses = {}
        self._progress_update_scheduled = False
        self._last_ui_update_at = 0.0
        self._upload_started_at = time.monotonic() if total_files else None
        self._progress_callbacks_received = 0
        self._ui_updates_applied = 0
        self._processed_milestones = {}
        self._recent_progress_samples.clear()
        self.progress_bar.set(0)
        self.progress_label.configure(text=f"Progreso: 0/{total_files}")

    def _record_metrics(self, progress: UploadBatchProgress) -> None:
        elapsed_seconds = self._elapsed_seconds()
        self._recent_progress_samples.append((time.monotonic(), progress.processed_count))
        previous_processed = self._last_progress.processed_count
        for milestone in range(50, progress.processed_count + 1, 50):
            if milestone > previous_processed:
                self._processed_milestones.setdefault(milestone, elapsed_seconds)

    def _build_status_text(self, progress: UploadBatchProgress) -> str:
        recent_speed = self._calculate_recent_speed()
        return (
            f"Subidas {progress.processed_count}/{progress.total_files} | "
            f"OK {progress.success_count} | Pendientes DB {progress.pending_count} | "
            f"Fallos {progress.failed_count} | "
            f"Velocidad: {recent_speed:.1f} fotos/min | "
            f"Callbacks {self._progress_callbacks_received} | UI {self._ui_updates_applied}"
        )

    def _resolve_status_color(self, progress: UploadBatchProgress) -> str:
        if progress.failed_count:
            return ERROR
        if progress.processed_count and progress.processed_count == progress.total_files:
            return SUCCESS
        return TEXT_PRIMARY

    def _elapsed_seconds(self) -> float:
        if self._upload_started_at is None:
            return 0.0
        return max(time.monotonic() - self._upload_started_at, 0.0)

    def _calculate_average_speed(self, processed_count: int) -> float:
        elapsed_seconds = self._elapsed_seconds()
        if processed_count <= 0 or elapsed_seconds <= 0:
            return 0.0
        return (processed_count / elapsed_seconds) * 60

    def _calculate_recent_speed(self) -> float:
        if len(self._recent_progress_samples) < 2:
            return self._calculate_average_speed(self._last_progress.processed_count)
        first_time, first_count = self._recent_progress_samples[0]
        last_time, last_count = self._recent_progress_samples[-1]
        delta_seconds = max(last_time - first_time, 0.0)
        delta_count = max(last_count - first_count, 0)
        if delta_seconds <= 0 or delta_count <= 0:
            return self._calculate_average_speed(self._last_progress.processed_count)
        return (delta_count / delta_seconds) * 60

    @staticmethod
    def _is_pending_db_result(item: UploadItemResult) -> bool:
        return (
            item.storage_uploaded
            and not item.database_inserted
            and item.database_error is None
        )

    @staticmethod
    def _is_failed_result(item: UploadItemResult) -> bool:
        return (
            item.storage_error is not None
            or item.database_error is not None
            or item.processing_status in {"Error", "Movido a failed_uploads"}
        )
