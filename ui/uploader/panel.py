from __future__ import annotations

from pathlib import Path
import contextlib
import logging
import threading
import time
import tkinter.filedialog as fd
from collections import deque

import customtkinter as ctk

from core.models import UploadBatchProgress, UploadItemResult
from services.photo_pool_policy_service import PhotoPoolPolicyService
from services.uploader_service import UploaderService
from ui.shared.dialogs import confirm_destructive_action
from ui.theme import (
    ACCENT,
    ON_ACCENT,
    ACCENT_HOVER,
    BORDER,
    CARD_BG,
    ERROR,
    SECONDARY_BUTTON,
    SECONDARY_BUTTON_HOVER,
    SUCCESS,
    TEXT_MUTED,
    TEXT_PRIMARY,
    WARNING,
)
from ui.uploader.file_list_panel import FileListPanel
from ui.uploader.upload_result_panel import UploadResultPanel


_LOGGER = logging.getLogger(__name__)


class UploaderPanel(ctk.CTkFrame):
    # How often the UI thread checks the buffers the upload worker fills.
    _UI_POLL_INTERVAL_MS = 80
    # Placeholder del selector de destino: no hay valor por defecto a proposito,
    # el administrador tiene que elegir el pool antes de poder subir.
    _POOL_PLACEHOLDER = "Elige el pool destino..."
    _POOL_LOADING = "Cargando pools..."
    _POOL_POLL_INTERVAL_MS = 120

    def __init__(
        self,
        master,
        uploader_service: UploaderService | None = None,
        *,
        pool_policy_service: PhotoPoolPolicyService | None = None,
        title_text: str = "Carga masiva de JPG a Supabase",
        subtitle_text: str = (
            "Sube fotos al bucket, registra cada fila en photos y conserva "
            "el resultado por archivo."
        ),
        **kwargs,
    ) -> None:
        super().__init__(master, fg_color="transparent", **kwargs)
        self._uploader_service = uploader_service or UploaderService()
        self._pool_policy_service = pool_policy_service or PhotoPoolPolicyService()
        self._selected_files: list[str] = []
        self._pool_load_result: tuple[str, object] | None = None
        self._pool_poller_id = None
        self._allowed_pools: list[str] = []
        self._active_pool: str | None = None
        self._upload_targets = None
        self._is_running = False
        self._last_progress = UploadBatchProgress()
        self._pending_progress: UploadBatchProgress | None = None
        self._pending_result_updates: dict[str, UploadItemResult] = {}
        self._pending_file_statuses: dict[str, str] = {}
        self._progress_lock = threading.Lock()
        self._progress_update_scheduled = False
        self._pending_force_immediate = False
        self._terminal_event: tuple[str, object] | None = None
        self._ui_poller_id = None
        self._panel_closed = False
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
        self._load_pool_options_async()

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
            text_color=ON_ACCENT,
            hover_color=ACCENT_HOVER,
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

        pool_row = ctk.CTkFrame(controls_card, fg_color="transparent")
        pool_row.grid(row=2, column=0, columnspan=2, padx=18, pady=(0, 12), sticky="ew")
        # Solo la etiqueta y el desplegable comparten fila; el resto del texto va
        # en filas propias para que no se recorte en una ventana estrecha.
        pool_row.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            pool_row,
            text="Pool destino de esta carga:",
            text_color=TEXT_PRIMARY,
            anchor="w",
        ).grid(row=0, column=0, sticky="w")

        self.pool_menu = ctk.CTkOptionMenu(
            pool_row,
            values=[self._POOL_LOADING],
            command=self._on_pool_selected,
            fg_color=SECONDARY_BUTTON,
            button_color=SECONDARY_BUTTON,
            button_hover_color=SECONDARY_BUTTON_HOVER,
            text_color=TEXT_PRIMARY,
            corner_radius=12,
            width=220,
            state="disabled",
        )
        self.pool_menu.set(self._POOL_LOADING)
        self.pool_menu.grid(row=0, column=1, padx=(12, 0), sticky="w")

        # El pool activo y el destino de la carga son cosas distintas: se
        # muestran por separado para que no se confundan.
        self.active_pool_label = ctk.CTkLabel(
            pool_row,
            text="Pool activo (del que consumen las corridas): consultando...",
            text_color=TEXT_MUTED,
            anchor="w",
            justify="left",
        )
        self.active_pool_label.configure(wraplength=720)
        self.active_pool_label.grid(row=1, column=0, columnspan=2, pady=(6, 0), sticky="ew")

        self.pool_hint_label = ctk.CTkLabel(
            pool_row,
            text="",
            text_color=TEXT_MUTED,
            anchor="w",
            justify="left",
            wraplength=720,
        )
        self.pool_hint_label.grid(row=2, column=0, columnspan=2, pady=(4, 0), sticky="ew")

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
        self.progress_label.grid(row=3, column=0, padx=18, pady=(0, 8), sticky="w")

        self.progress_bar = ctk.CTkProgressBar(controls_card, height=12, corner_radius=999)
        self.progress_bar.grid(row=3, column=1, padx=18, pady=(0, 8), sticky="ew")
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

    # ------------------------------------------------------------------
    # Carga de la lista blanca de pools. El RPC va en un hilo aparte; el hilo
    # de UI solo lee el resultado desde su propio poller, nunca toca Tk desde
    # el worker.
    # ------------------------------------------------------------------

    def _load_pool_options_async(self) -> None:
        thread = threading.Thread(
            target=self._fetch_pool_options,
            name="uploader-pool-options",
            daemon=True,
        )
        self._start_pool_poller()
        thread.start()

    def _fetch_pool_options(self) -> None:
        try:
            targets = self._pool_policy_service.list_upload_targets()
            active = self._pool_policy_service.get_policy().bucket
            payload: tuple[str, object] = ("ok", (targets, active))
        except Exception as exc:  # noqa: BLE001 - se muestra en el hilo de UI
            payload = ("error", exc)
        with self._progress_lock:
            self._pool_load_result = payload

    def _start_pool_poller(self) -> None:
        if self._pool_poller_id is not None or self._panel_closed:
            return
        self._pool_poller_id = self.after(
            self._POOL_POLL_INTERVAL_MS, self._poll_pool_options
        )

    def _stop_pool_poller(self) -> None:
        poller_id = self._pool_poller_id
        self._pool_poller_id = None
        if poller_id is not None:
            with contextlib.suppress(Exception):
                self.after_cancel(poller_id)

    def _poll_pool_options(self) -> None:
        self._pool_poller_id = None
        if self._panel_closed:
            return
        try:
            if not self.winfo_exists():
                self._panel_closed = True
                return
        except Exception:  # noqa: BLE001 - widget ya destruido
            self._panel_closed = True
            return

        with self._progress_lock:
            payload = self._pool_load_result
            self._pool_load_result = None
        if payload is None:
            self._start_pool_poller()
            return

        kind, value = payload
        if kind == "error":
            _LOGGER.exception(
                "No se pudo cargar la lista de pools permitidos", exc_info=value
            )
            self._allowed_pools = []
            self.pool_menu.configure(values=[self._POOL_PLACEHOLDER], state="disabled")
            self.pool_menu.set(self._POOL_PLACEHOLDER)
            self.active_pool_label.configure(
                text="Pool activo: no disponible.", text_color=ERROR
            )
            self.pool_hint_label.configure(
                text=(
                    "No se pudo obtener la lista de pools permitidos. "
                    "Revisa la conexion con Supabase antes de subir."
                ),
                text_color=ERROR,
            )
            return

        targets, active = value
        self._apply_pool_options(targets, str(active or ""))

    def _apply_pool_options(self, targets, active: str) -> None:
        self._upload_targets = targets
        self._allowed_pools = [item.bucket for item in targets.eligible]
        self._active_pool = active or None
        self.active_pool_label.configure(
            text=(
                "Pool activo (del que consumen las corridas): "
                f"{active or 'desconocido'}"
            ),
            text_color=TEXT_MUTED,
        )

        if not targets.migration_applied:
            # Nunca presentar el pool activo como si fuese la lista completa:
            # aqui simplemente no sabemos cuales son los buckets reales.
            self._allowed_pools = []
            self.pool_menu.configure(values=[self._POOL_PLACEHOLDER], state="disabled")
            self.pool_menu.set(self._POOL_PLACEHOLDER)
            self.pool_hint_label.configure(
                text=(
                    "FALTA APLICAR LA MIGRACION sql/020_multi_photo_pool_buckets.sql "
                    "en Supabase. Hasta entonces no se pueden listar los buckets "
                    "reales de Storage ni elegir destino, y la carga queda "
                    "bloqueada. Esta lista NO es el inventario completo."
                ),
                text_color=ERROR,
            )
            return

        if not self._allowed_pools:
            self.pool_menu.configure(values=[self._POOL_PLACEHOLDER], state="disabled")
            self.pool_menu.set(self._POOL_PLACEHOLDER)
            excluded = ", ".join(
                item.bucket for item in targets.targets if not item.is_eligible
            )
            self.pool_hint_label.configure(
                text=(
                    "Supabase no devolvio ningun bucket apto como destino."
                    + (f" Excluidos: {excluded}." if excluded else "")
                ),
                text_color=ERROR,
            )
            return
        # Sin preseleccion: el placeholder obliga a una eleccion explicita.
        self.pool_menu.configure(
            values=[self._POOL_PLACEHOLDER, *self._allowed_pools],
            state="normal" if not self._is_running else "disabled",
        )
        self.pool_menu.set(self._POOL_PLACEHOLDER)
        self._refresh_pool_hint()

    def _on_pool_selected(self, _value: str) -> None:
        self._refresh_pool_hint()

    def _selected_pool(self) -> str | None:
        value = str(self.pool_menu.get() or "").strip()
        if value in {self._POOL_PLACEHOLDER, self._POOL_LOADING, ""}:
            return None
        if value not in self._allowed_pools:
            return None
        return value

    def _refresh_pool_hint(self) -> None:
        selected = self._selected_pool()
        if selected is None:
            excluded = ""
            if self._upload_targets is not None:
                names = [
                    item.bucket
                    for item in self._upload_targets.targets
                    if not item.is_eligible
                ]
                if names:
                    excluded = (
                        f" Buckets excluidos como destino: {', '.join(names)}."
                    )
            self.pool_hint_label.configure(
                text=(
                    f"{len(self._allowed_pools)} bucket(s) de Supabase disponibles "
                    f"como destino. Elige uno para habilitar la carga.{excluded}"
                ),
                text_color=TEXT_MUTED,
            )
            return
        if self._active_pool and selected != self._active_pool:
            self.pool_hint_label.configure(
                text=(
                    f"Destino '{selected}': NO es el pool activo. Las fotos quedaran "
                    f"ahi y las corridas no las consumiran hasta que se active "
                    f"'{selected}' manualmente. El pool activo sigue siendo "
                    f"'{self._active_pool}'."
                ),
                text_color=WARNING,
            )
            return
        self.pool_hint_label.configure(
            text=(
                f"Destino '{selected}': coincide con el pool activo, las corridas "
                "podran consumir estas fotos."
            ),
            text_color=SUCCESS,
        )

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
        # El destino se lee en el hilo de UI y se congela para todo el lote.
        target_bucket = self._selected_pool()
        if target_bucket is None:
            self.status_label.configure(
                text="Elige el pool destino antes de iniciar la carga.",
                text_color=ERROR,
            )
            self._refresh_pool_hint()
            return
        self._is_running = True
        self._set_controls_state("disabled")
        self.result_panel.clear()
        self._reset_progress_state(total_files=len(self._selected_files))
        self.file_list_panel.set_upload_active(True)
        self.status_label.configure(text="Preparando archivos...", text_color=TEXT_PRIMARY)
        # Tk widgets must only be touched from the UI thread: read the checkbox here
        # and hand the plain value to the worker.
        delete_local = bool(self.delete_local_checkbox.get())
        if delete_local and not confirm_destructive_action(
            title="Borrado local",
            what=(
                f"Los {len(self._selected_files)} archivos se borraran de tu disco "
                "despues de subirse correctamente."
            ),
            scope=(
                "Solo se borran los que suban bien. Los que fallen se conservan: "
                "segun el fallo, se quedan donde estan o se mueven a "
                "local_data/failed_uploads."
            ),
            parent=self,
        ):
            self._is_running = False
            self._set_controls_state("normal")
            self.file_list_panel.set_upload_active(False)
            self.status_label.configure(text="Carga cancelada.", text_color=TEXT_MUTED)
            return
        files = list(self._selected_files)
        self._terminal_event = None
        thread = threading.Thread(
            target=self._run_upload,
            args=(files, delete_local, target_bucket),
            name="uploader-worker",
            daemon=True,
        )
        # The UI thread owns every widget call: it polls the buffers the worker
        # fills. The worker never calls after(), configure() or any other Tk method.
        self._start_ui_poller()
        thread.start()

    # ------------------------------------------------------------------
    # Worker side. Nothing below this line may touch a Tk/CTk widget: Tcl is
    # not thread-safe, and that includes Misc.after(), which is itself an
    # interpreter call.
    # ------------------------------------------------------------------

    def _run_upload(self, files: list[str], delete_local: bool, target_bucket: str) -> None:
        try:
            results = self._uploader_service.upload_files(
                files,
                target_bucket=target_bucket,
                delete_local_on_success=delete_local,
                progress_callback=self._schedule_progress_update,
            )
            self._publish_terminal_event("done", results)
        except Exception as exc:  # noqa: BLE001 - surfaced on the UI thread
            self._publish_terminal_event("error", exc)

    def _publish_terminal_event(self, kind: str, payload) -> None:
        with self._progress_lock:
            self._terminal_event = (kind, payload)

    def _schedule_progress_update(self, progress: UploadBatchProgress) -> None:
        """Buffer one progress callback. Runs on the upload worker thread."""

        with self._progress_lock:
            self._progress_callbacks_received += 1
            self._pending_progress = progress
            if progress.result is not None:
                # dicts keep insertion order, so per-file results stay in the order
                # the service produced them.
                self._pending_result_updates[progress.result.source_path] = progress.result
                self._pending_file_statuses[progress.result.source_path] = (
                    progress.result.processing_status
                )
            if (
                progress.current_index == 0
                or progress.total_files == 0
                or progress.processed_count == progress.total_files
                or progress.status_text == "Finalizado"
            ):
                self._pending_force_immediate = True

    # ------------------------------------------------------------------
    # UI side. Only the Tk thread runs anything below.
    # ------------------------------------------------------------------

    def _start_ui_poller(self) -> None:
        if self._ui_poller_id is not None or self._panel_closed:
            return
        self._ui_poller_id = self.after(self._UI_POLL_INTERVAL_MS, self._poll_upload_events)

    def _stop_ui_poller(self) -> None:
        poller_id = self._ui_poller_id
        self._ui_poller_id = None
        if poller_id is not None:
            with contextlib.suppress(Exception):
                self.after_cancel(poller_id)

    def _poll_upload_events(self) -> None:
        self._ui_poller_id = None
        if self._panel_closed:
            return
        try:
            if not self.winfo_exists():
                self._panel_closed = True
                return
        except Exception:  # noqa: BLE001 - widget already torn down
            self._panel_closed = True
            return

        try:
            self._drain_pending_progress()
        except Exception as exc:  # noqa: BLE001
            # A CTk error while repainting must not strand the terminal event:
            # that would leave the controls disabled with no way to retry.
            _LOGGER.exception("No se pudo repintar el progreso de la carga", exc_info=exc)

        with self._progress_lock:
            terminal = self._terminal_event
            self._terminal_event = None
        if terminal is None:
            if self._is_running:
                self._start_ui_poller()
            return

        kind, payload = terminal
        if kind == "done":
            self._finish_upload(payload)
        else:
            self._handle_unexpected_error(payload)

    def _drain_pending_progress(self) -> None:
        with self._progress_lock:
            progress = self._pending_progress
            force_immediate = self._pending_force_immediate
            if progress is None:
                return
            if not force_immediate:
                elapsed_ms = int((time.monotonic() - self._last_ui_update_at) * 1000)
                if elapsed_ms < self._ui_update_interval_ms:
                    return  # coalesce: keep buffering, apply on a later tick
            self._pending_progress = None
            self._pending_force_immediate = False
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
        self._stop_ui_poller()
        with self._progress_lock:
            has_pending = self._pending_progress is not None
            if has_pending:
                self._pending_force_immediate = True  # bypass the coalescing window
        if has_pending:
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
        self._stop_ui_poller()
        self._is_running = False
        self._set_controls_state("normal")
        self.file_list_panel.set_upload_active(False)
        # The exception text can carry storage paths, tokens or row contents: log the
        # detail, show the user only what they can act on.
        _LOGGER.exception("La carga de fotos fallo de forma inesperada", exc_info=exc)
        self.status_label.configure(
            text=(
                "La carga se interrumpió por un error inesperado "
                f"({type(exc).__name__}). Los archivos siguen seleccionados: "
                "pulsa 'Subir archivos' para reintentar."
            ),
            text_color=ERROR,
        )

    def destroy(self) -> None:
        # The panel can be closed while an upload is still running: stop the poller
        # so no callback fires against a destroyed widget. The worker is a daemon
        # thread that only writes to buffers, so it can finish harmlessly.
        self._panel_closed = True
        self._stop_ui_poller()
        self._stop_pool_poller()
        super().destroy()

    def _set_controls_state(self, state: str) -> None:
        self.select_button.configure(state=state)
        self.upload_button.configure(state=state)
        self.delete_local_checkbox.configure(state=state)
        if state == "normal" and not self._allowed_pools:
            # Sin lista blanca cargada no se puede elegir destino, asi que el
            # selector sigue deshabilitado.
            self.pool_menu.configure(state="disabled")
        else:
            self.pool_menu.configure(state=state)

    def _reset_progress_state(self, *, total_files: int = 0) -> None:
        self._last_progress = UploadBatchProgress(total_files=total_files)
        self._pending_progress = None
        self._pending_result_updates = {}
        self._pending_file_statuses = {}
        self._progress_update_scheduled = False
        self._pending_force_immediate = False
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
            f"Velocidad: {recent_speed:.1f} fotos/min"
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
