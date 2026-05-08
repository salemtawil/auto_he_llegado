from __future__ import annotations

import json
import threading

import customtkinter as ctk

from services.photo_cleanup_service import PhotoCleanupService
from ui.main_app.current_result_panel import CurrentResultPanel
from ui.main_app.extension_status_panel import ExtensionStatusPanel
from ui.theme import (
    ACCENT,
    ACCENT_HOVER,
    APP_BG,
    BORDER,
    CARD_BG,
    ERROR,
    NEUTRAL_BUTTON,
    NEUTRAL_BUTTON_HOVER,
    SUCCESS,
    TEXT_MUTED,
    TEXT_PRIMARY,
    WARNING,
)
from ui.uploader.panel import UploaderPanel


class AdminPasswordDialog(ctk.CTkToplevel):
    def __init__(self, master, on_submit, **kwargs) -> None:
        super().__init__(master, fg_color=APP_BG, **kwargs)
        self._on_submit = on_submit
        self.title("Acceso Admin")
        self.geometry("420x260")
        self.minsize(400, 240)
        self.resizable(False, False)
        self.transient(master)
        self.grab_set()

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
            text="Modulo Admin",
            font=ctk.CTkFont(size=22, weight="bold"),
            text_color=TEXT_PRIMARY,
        )
        title.grid(row=0, column=0, padx=22, pady=(22, 8), sticky="w")

        subtitle = ctk.CTkLabel(
            container,
            text="Ingresa la contrasena para abrir la carga integrada de fotos.",
            text_color=TEXT_MUTED,
            justify="left",
            wraplength=320,
        )
        subtitle.grid(row=1, column=0, padx=22, pady=(0, 14), sticky="ew")

        self.password_entry = ctk.CTkEntry(
            container,
            placeholder_text="Contrasena Admin",
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
            text="",
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
            command=self.destroy,
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

    def set_error(self, message: str) -> None:
        self.feedback_label.configure(text=message)
        self.password_entry.select_range(0, "end")
        self.password_entry.focus()

    def _handle_submit(self, _event=None) -> None:
        self._on_submit(self.password_entry.get())


class AdminUploaderDialog(ctk.CTkToplevel):
    def __init__(
        self,
        master,
        uploader_service=None,
        on_test_log=None,
        diagnostics_provider=None,
        on_refresh_diagnostics=None,
        on_export_debug=None,
        photo_cleanup_service=None,
        **kwargs,
    ) -> None:
        super().__init__(master, fg_color=APP_BG, **kwargs)
        self.title("Admin | Herramientas")
        self.geometry("1200x820")
        self.minsize(1040, 720)
        self._on_test_log = on_test_log
        self._diagnostics_provider = diagnostics_provider
        self._on_refresh_diagnostics = on_refresh_diagnostics
        self._on_export_debug = on_export_debug
        self._photo_cleanup_service = photo_cleanup_service or PhotoCleanupService()
        self._diagnostics_payloads: dict[str, dict] = {}
        self._payload_visible = False
        self._diagnostics_loading = False
        self._current_snapshot: dict = {}
        self._cleanup_running = False
        self._cleanup_cancel_requested = False
        self._cleanup_progress_total = 0
        self._cleanup_progress_done = 0
        self._cleanup_mode = ""

        container = ctk.CTkFrame(self, fg_color="transparent")
        container.pack(fill="both", expand=True, padx=20, pady=20)
        container.grid_columnconfigure(0, weight=1)
        container.grid_rowconfigure(0, weight=1)

        self.tabs = ctk.CTkTabview(container, corner_radius=20)
        self.tabs.grid(row=0, column=0, sticky="nsew")
        self.tabs.add("Carga")
        self.tabs.add("Limpieza fotos")
        self.tabs.add("Diagnóstico")

        self._build_upload_tab(self.tabs.tab("Carga"), uploader_service)
        self._build_photo_cleanup_tab(self.tabs.tab("Limpieza fotos"))
        self._build_diagnostics_tab(self.tabs.tab("Diagnóstico"))
        self._set_diagnostics_idle_state()

    def _build_upload_tab(self, master, uploader_service) -> None:
        master.grid_columnconfigure(0, weight=1)
        master.grid_rowconfigure(1, weight=1)

        utility_card = ctk.CTkFrame(
            master,
            fg_color=CARD_BG,
            corner_radius=18,
            border_width=1,
            border_color=BORDER,
        )
        utility_card.grid(row=0, column=0, sticky="ew", pady=(0, 14))
        utility_card.grid_columnconfigure(0, weight=1)
        utility_card.grid_columnconfigure(1, weight=0)

        utility_text = ctk.CTkLabel(
            utility_card,
            text=(
                "Prueba de trazabilidad: inserta un registro real en "
                "process_logs sin ejecutar automatizacion web."
            ),
            text_color=TEXT_MUTED,
            justify="left",
            wraplength=700,
        )
        utility_text.grid(row=0, column=0, padx=(18, 12), pady=(14, 8), sticky="w")

        self.test_log_button = ctk.CTkButton(
            utility_card,
            text="Probar log",
            command=self._handle_test_log,
            height=36,
            width=110,
            corner_radius=12,
            fg_color=NEUTRAL_BUTTON,
            hover_color=NEUTRAL_BUTTON_HOVER,
            text_color=TEXT_PRIMARY,
            font=ctk.CTkFont(size=12, weight="bold"),
        )
        self.test_log_button.grid(
            row=0,
            column=1,
            rowspan=2,
            padx=(12, 18),
            pady=14,
            sticky="e",
        )

        self.test_log_feedback = ctk.CTkLabel(
            utility_card,
            text="",
            text_color=TEXT_MUTED,
            justify="left",
            wraplength=700,
        )
        self.test_log_feedback.grid(
            row=1,
            column=0,
            padx=(18, 12),
            pady=(0, 14),
            sticky="ew",
        )

        panel = UploaderPanel(
            master,
            uploader_service=uploader_service,
            title_text="Carga integrada de fotos",
            subtitle_text=(
                "Modulo restringido para subir JPG al pool y registrar "
                "el resultado por archivo."
            ),
        )
        panel.grid(row=1, column=0, sticky="nsew")

    def _build_photo_cleanup_tab(self, master) -> None:
        master.grid_columnconfigure(0, weight=1)
        master.grid_rowconfigure(3, weight=1)

        header = ctk.CTkFrame(
            master,
            fg_color=CARD_BG,
            corner_radius=18,
            border_width=1,
            border_color=BORDER,
        )
        header.grid(row=0, column=0, sticky="ew", pady=(0, 14))
        header.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            header,
            text="Limpieza de fotos",
            font=ctk.CTkFont(size=20, weight="bold"),
            text_color=TEXT_PRIMARY,
        ).grid(row=0, column=0, padx=(18, 12), pady=(14, 6), sticky="w")

        ctk.CTkLabel(
            header,
            text=(
                "Borra archivos remotos de Storage para fotos consumidas o reservadas viejas, "
                "pero conserva el histórico en photos."
            ),
            text_color=TEXT_MUTED,
            justify="left",
            wraplength=860,
        ).grid(row=1, column=0, padx=18, pady=(0, 14), sticky="ew")

        actions = ctk.CTkFrame(
            master,
            fg_color=CARD_BG,
            corner_radius=18,
            border_width=1,
            border_color=BORDER,
        )
        actions.grid(row=1, column=0, sticky="ew", pady=(0, 14))
        actions.grid_columnconfigure(5, weight=1)

        self.audit_pool_button = ctk.CTkButton(
            actions,
            text="Auditar pool",
            command=self._handle_photo_cleanup_audit,
            height=36,
            corner_radius=12,
            fg_color=NEUTRAL_BUTTON,
            hover_color=NEUTRAL_BUTTON_HOVER,
            text_color=TEXT_PRIMARY,
        )
        self.audit_pool_button.grid(row=0, column=0, padx=(18, 8), pady=14, sticky="w")

        self.cleanup_consumed_button = ctk.CTkButton(
            actions,
            text="Limpiar 100 consumidas",
            command=self._handle_cleanup_consumed,
            height=36,
            corner_radius=12,
            fg_color=ACCENT,
            hover_color=ACCENT_HOVER,
        )
        self.cleanup_consumed_button.grid(row=0, column=1, padx=8, pady=14, sticky="w")

        self.cleanup_stale_reserved_button = ctk.CTkButton(
            actions,
            text="Limpiar 100 reservadas viejas",
            command=self._handle_cleanup_stale_reserved,
            height=36,
            corner_radius=12,
            fg_color=NEUTRAL_BUTTON,
            hover_color=NEUTRAL_BUTTON_HOVER,
            text_color=TEXT_PRIMARY,
        )
        self.cleanup_stale_reserved_button.grid(row=0, column=2, padx=8, pady=14, sticky="w")

        self.cleanup_all_consumed_button = ctk.CTkButton(
            actions,
            text="Limpiar todas las consumidas",
            command=self._start_cleanup_all_consumed,
            height=36,
            corner_radius=12,
            fg_color=ACCENT,
            hover_color=ACCENT_HOVER,
        )
        self.cleanup_all_consumed_button.grid(row=0, column=3, padx=8, pady=14, sticky="w")

        self.cleanup_all_stale_reserved_button = ctk.CTkButton(
            actions,
            text="Limpiar todas las reservadas viejas",
            command=self._start_cleanup_all_stale_reserved,
            height=36,
            corner_radius=12,
            fg_color=NEUTRAL_BUTTON,
            hover_color=NEUTRAL_BUTTON_HOVER,
            text_color=TEXT_PRIMARY,
        )
        self.cleanup_all_stale_reserved_button.grid(row=0, column=4, padx=8, pady=14, sticky="w")

        self.photo_cleanup_status_label = ctk.CTkLabel(
            actions,
            text="Sin auditoría ejecutada.",
            text_color=TEXT_MUTED,
            justify="right",
            anchor="e",
        )
        self.photo_cleanup_status_label.grid(row=0, column=5, padx=(12, 18), pady=14, sticky="e")

        progress = ctk.CTkFrame(
            master,
            fg_color=CARD_BG,
            corner_radius=18,
            border_width=1,
            border_color=BORDER,
        )
        progress.grid(row=2, column=0, sticky="ew", pady=(0, 14))
        progress.grid_columnconfigure(0, weight=1)
        progress.grid_columnconfigure(1, weight=0)

        self.cleanup_progress_label = ctk.CTkLabel(
            progress,
            text="Sin limpieza masiva en curso.",
            text_color=TEXT_PRIMARY,
            justify="left",
            anchor="w",
        )
        self.cleanup_progress_label.grid(row=0, column=0, padx=16, pady=(12, 6), sticky="ew")

        self.cancel_cleanup_button = ctk.CTkButton(
            progress,
            text="Cancelar limpieza",
            command=self._cancel_cleanup,
            state="disabled",
            height=34,
            corner_radius=12,
            fg_color=NEUTRAL_BUTTON,
            hover_color=NEUTRAL_BUTTON_HOVER,
            text_color=TEXT_PRIMARY,
        )
        self.cancel_cleanup_button.grid(row=0, column=1, padx=(12, 16), pady=(12, 6), sticky="e")

        self.cleanup_progress_bar = ctk.CTkProgressBar(progress, height=16, corner_radius=999)
        self.cleanup_progress_bar.grid(row=1, column=0, columnspan=2, padx=16, pady=6, sticky="ew")
        self.cleanup_progress_bar.set(0.0)

        self.cleanup_last_batch_label = ctk.CTkLabel(
            progress,
            text="Último lote: --",
            text_color=TEXT_MUTED,
            justify="left",
            anchor="w",
        )
        self.cleanup_last_batch_label.grid(row=2, column=0, columnspan=2, padx=16, pady=(0, 4), sticky="ew")

        self.cleanup_remaining_label = ctk.CTkLabel(
            progress,
            text="Restantes: -- | Velocidad: -- fotos/min",
            text_color=TEXT_MUTED,
            justify="left",
            anchor="w",
        )
        self.cleanup_remaining_label.grid(row=3, column=0, columnspan=2, padx=16, pady=(0, 14), sticky="ew")

        summary = ctk.CTkFrame(
            master,
            fg_color=CARD_BG,
            corner_radius=18,
            border_width=1,
            border_color=BORDER,
        )
        summary.grid(row=3, column=0, sticky="nsew")
        summary.grid_columnconfigure(0, weight=1)
        summary.grid_rowconfigure(1, weight=1)

        ctk.CTkLabel(
            summary,
            text="Resumen del pool",
            font=ctk.CTkFont(size=16, weight="bold"),
            text_color=TEXT_PRIMARY,
        ).grid(row=0, column=0, padx=16, pady=(12, 6), sticky="w")

        self.photo_cleanup_summary_box = ctk.CTkTextbox(
            summary,
            height=220,
            border_width=1,
            border_color=BORDER,
            corner_radius=12,
        )
        self.photo_cleanup_summary_box.grid(row=1, column=0, padx=16, pady=(0, 14), sticky="nsew")
        self._set_photo_cleanup_summary_lines(
            [
                "Disponibles: --",
                "Reservadas: --",
                "Usadas históricas: --",
                "Descartadas: --",
                "Consumidas pendientes de limpiar Storage: --",
                "Consumidas pendientes limpiables: --",
                "Reservadas viejas pendientes: --",
                "Reservadas viejas limpiables: --",
            ]
        )

    def _build_diagnostics_tab(self, master) -> None:
        master.grid_columnconfigure(0, weight=1)
        master.grid_rowconfigure(2, weight=1)

        header = ctk.CTkFrame(
            master,
            fg_color=CARD_BG,
            corner_radius=18,
            border_width=1,
            border_color=BORDER,
        )
        header.grid(row=0, column=0, sticky="ew", pady=(0, 14))
        header.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            header,
            text="Diagnóstico",
            font=ctk.CTkFont(size=20, weight="bold"),
            text_color=TEXT_PRIMARY,
        ).grid(row=0, column=0, padx=(18, 12), pady=(14, 6), sticky="w")

        self.slot_selector = ctk.CTkOptionMenu(
            header,
            values=["Proceso 1", "Proceso 2"],
            command=lambda _value: self._apply_selected_diagnostics(),
            width=160,
        )
        self.slot_selector.grid(row=0, column=1, padx=(0, 12), pady=(14, 6), sticky="e")

        actions = ctk.CTkFrame(header, fg_color="transparent")
        actions.grid(row=1, column=0, columnspan=2, padx=18, pady=(0, 14), sticky="ew")
        actions.grid_columnconfigure(0, weight=0)
        actions.grid_columnconfigure(1, weight=0)
        actions.grid_columnconfigure(2, weight=0)
        actions.grid_columnconfigure(3, weight=1)

        self.refresh_diag_button = ctk.CTkButton(
            actions,
            text="Refrescar diagnóstico",
            command=self.refresh_diagnostics,
            height=34,
            corner_radius=12,
            fg_color=NEUTRAL_BUTTON,
            hover_color=NEUTRAL_BUTTON_HOVER,
            text_color=TEXT_PRIMARY,
        )
        self.refresh_diag_button.grid(row=0, column=0, padx=(0, 8), sticky="w")

        self.export_diag_button = ctk.CTkButton(
            actions,
            text="Exportar debug",
            command=self._handle_export_debug,
            height=34,
            corner_radius=12,
            fg_color=NEUTRAL_BUTTON,
            hover_color=NEUTRAL_BUTTON_HOVER,
            text_color=TEXT_PRIMARY,
        )
        self.export_diag_button.grid(row=0, column=1, padx=(0, 8), sticky="w")

        self.toggle_payload_button = ctk.CTkButton(
            actions,
            text="Ver payload técnico",
            command=self._toggle_payload,
            height=34,
            corner_radius=12,
            fg_color=NEUTRAL_BUTTON,
            hover_color=NEUTRAL_BUTTON_HOVER,
            text_color=TEXT_PRIMARY,
        )
        self.toggle_payload_button.grid(row=0, column=2, sticky="w")

        self.summary_label = ctk.CTkLabel(
            actions,
            text="Diagnóstico no cargado. Presiona Refrescar.",
            text_color=TEXT_MUTED,
            anchor="e",
            justify="right",
        )
        self.summary_label.grid(row=0, column=3, sticky="e")

        content = ctk.CTkFrame(master, fg_color="transparent")
        content.grid(row=1, column=0, sticky="nsew")
        content.grid_columnconfigure(0, weight=1)
        content.grid_rowconfigure(0, weight=1)
        content.grid_rowconfigure(1, weight=1)

        self.result_panel = CurrentResultPanel(content)
        self.result_panel.grid(row=0, column=0, pady=(0, 10), sticky="ew")
        self.result_panel.set_compact_layout(False)

        self.extension_panel = ExtensionStatusPanel(content)
        self.extension_panel.grid(row=1, column=0, sticky="nsew")
        self.extension_panel.set_compact_layout(False)

        technical = ctk.CTkFrame(
            master,
            fg_color=CARD_BG,
            corner_radius=18,
            border_width=1,
            border_color=BORDER,
        )
        technical.grid(row=2, column=0, sticky="nsew", pady=(14, 0))
        technical.grid_columnconfigure(0, weight=1)
        technical.grid_rowconfigure(1, weight=1)

        ctk.CTkLabel(
            technical,
            text="Payload técnico",
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color=TEXT_PRIMARY,
        ).grid(row=0, column=0, padx=16, pady=(12, 6), sticky="w")

        self.payload_box = ctk.CTkTextbox(
            technical,
            height=220,
            border_width=1,
            border_color=BORDER,
            corner_radius=12,
        )
        self.payload_box.grid(row=1, column=0, padx=16, pady=(0, 14), sticky="nsew")
        self.payload_box.configure(state="disabled")
        technical.grid_remove()
        self._technical_card = technical
        self._apply_payload({})

    def refresh_diagnostics(self) -> None:
        if self._diagnostics_loading:
            return
        if self._diagnostics_provider is None:
            self.summary_label.configure(text="Diagnóstico no disponible.")
            return
        self._diagnostics_loading = True
        self.refresh_diag_button.configure(state="disabled", text="Cargando...")
        self.summary_label.configure(text="Cargando diagnóstico...")

        def worker() -> None:
            try:
                payload = self._diagnostics_provider() or {}
                self.after(0, lambda current_payload=payload: self._finish_refresh_diagnostics(current_payload))
            except Exception as exc:
                self.after(0, lambda error=exc: self._finish_refresh_diagnostics_error(error))

        threading.Thread(target=worker, daemon=True).start()

    def _finish_refresh_diagnostics(self, payload: dict[str, dict]) -> None:
        self._diagnostics_loading = False
        self.refresh_diag_button.configure(state="normal", text="Refrescar diagnóstico")
        self._diagnostics_payloads = payload
        slot_names = list(payload.keys()) or ["Proceso 1", "Proceso 2"]
        self.slot_selector.configure(values=slot_names)
        if self.slot_selector.get() not in slot_names:
            self.slot_selector.set(slot_names[0])
        if not payload:
            self._set_diagnostics_idle_state("Diagnóstico no cargado. Presiona Refrescar.")
            return
        self._apply_selected_diagnostics()

    def _finish_refresh_diagnostics_error(self, exc: Exception) -> None:
        self._diagnostics_loading = False
        self.refresh_diag_button.configure(state="normal", text="Refrescar diagnóstico")
        self._set_diagnostics_idle_state(f"Error cargando diagnóstico: {exc}")

    def _set_diagnostics_idle_state(self, summary_text: str = "Diagnóstico no cargado. Presiona Refrescar.") -> None:
        self._diagnostics_payloads = {}
        self._current_snapshot = {}
        self.summary_label.configure(text=summary_text)
        self.result_panel.set_placeholder()
        self.extension_panel.set_placeholder()
        self._apply_payload({})

    def mark_diagnostics_stale(self) -> None:
        if self._diagnostics_loading:
            return
        self.summary_label.configure(text="Hay cambios recientes. Presiona Refrescar.")

    def _apply_selected_diagnostics(self) -> None:
        slot_name = self.slot_selector.get()
        snapshot = self._diagnostics_payloads.get(slot_name) or {}
        self._current_snapshot = snapshot
        result = snapshot.get("result")
        elapsed_text = snapshot.get("elapsed_text")
        process_id = snapshot.get("process_id") or "N/A"
        self.summary_label.configure(
            text=f"{slot_name} | process_id: {process_id} | {snapshot.get('status_summary') or 'Sin datos'}"
        )

        if result is not None:
            self.result_panel.set_result(result, elapsed_text=elapsed_text)
        else:
            self.result_panel.set_placeholder()

        self.extension_panel.set_status(
            session_active=bool(snapshot.get("session_active")),
            extension_requested=bool(snapshot.get("extension_requested")),
            flow_engine=str(snapshot.get("flow_engine") or "traditional"),
            session_debug=snapshot.get("session_debug"),
        )
        if self._payload_visible:
            self._apply_payload(snapshot)
        else:
            self._apply_payload({})

    def _apply_payload(self, snapshot: dict) -> None:
        payload = {
            "process_id": snapshot.get("process_id"),
            "timing_summary": snapshot.get("timing_summary", {}),
            "timeline": snapshot.get("timeline", []),
            "last_final_button_candidate": snapshot.get("last_final_button_candidate", {}),
            "process_debug": snapshot.get("process_debug", {}),
            "browser_debug": snapshot.get("session_debug", {}),
            "frames": snapshot.get("frames", []),
        }
        text = json.dumps(payload, indent=2, ensure_ascii=False)
        self.payload_box.configure(state="normal")
        self.payload_box.delete("1.0", "end")
        self.payload_box.insert("1.0", text)
        self.payload_box.configure(state="disabled")

    def _toggle_payload(self) -> None:
        self._payload_visible = not self._payload_visible
        self.toggle_payload_button.configure(
            text="Ocultar payload técnico" if self._payload_visible else "Ver payload técnico"
        )
        if self._payload_visible:
            self._apply_payload(self._current_snapshot)
            self._technical_card.grid()
        else:
            self._technical_card.grid_remove()

    def _handle_export_debug(self) -> None:
        if self._on_export_debug is None:
            return
        self._on_export_debug(self.slot_selector.get())

    def set_test_log_feedback(self, message: str, *, color=None) -> None:
        self.test_log_feedback.configure(text=message, text_color=color or TEXT_MUTED)

    def set_test_log_busy(self, is_busy: bool) -> None:
        self.test_log_button.configure(
            state="disabled" if is_busy else "normal",
            text="Insertando..." if is_busy else "Probar log",
        )

    def _handle_test_log(self) -> None:
        if self._on_test_log is None:
            return
        self._on_test_log()

    def _handle_photo_cleanup_audit(self) -> None:
        self._run_photo_cleanup_task(
            busy_text="Auditando...",
            success_text="Auditoría completada.",
            worker=lambda: ("audit", self._photo_cleanup_service.audit()),
        )

    def _handle_cleanup_consumed(self) -> None:
        self._run_photo_cleanup_task(
            busy_text="Limpiando consumidas...",
            success_text="Limpieza de consumidas completada.",
            worker=lambda: ("cleanup", self._photo_cleanup_service.cleanup_consumed_photos(limit=100)),
        )

    def _handle_cleanup_stale_reserved(self) -> None:
        self._run_photo_cleanup_task(
            busy_text="Limpiando reservadas viejas...",
            success_text="Limpieza de reservadas viejas completada.",
            worker=lambda: ("cleanup", self._photo_cleanup_service.cleanup_stale_reserved_photos(limit=100)),
        )

    def _start_cleanup_all_consumed(self) -> None:
        self._start_cleanup_batches(kind="consumed")

    def _start_cleanup_all_stale_reserved(self) -> None:
        self._start_cleanup_batches(kind="stale_reserved")

    def _start_cleanup_batches(self, *, kind: str) -> None:
        if self._cleanup_running:
            return
        self._cleanup_running = True
        self._cleanup_cancel_requested = False
        self._cleanup_progress_total = 0
        self._cleanup_progress_done = 0
        self._cleanup_mode = kind
        mode_label = "consumidas" if kind == "consumed" else "reservadas viejas"
        self._set_photo_cleanup_busy(True, busy_text=f"Preparando limpieza total de {mode_label}...")
        self.cleanup_progress_bar.set(0.0)
        self.cleanup_progress_label.configure(text=f"Preparando limpieza total de {mode_label}...")
        self.cleanup_last_batch_label.configure(text="Último lote: --")
        self.cleanup_remaining_label.configure(text="Restantes: -- | Velocidad: -- fotos/min")

        def background() -> None:
            try:
                result = self._run_cleanup_batches(kind)
                self.after(
                    0,
                    lambda current_result=result: self._finish_cleanup_batches(current_result),
                )
            except Exception as exc:
                self.after(0, lambda error=exc: self._finish_cleanup_batches_error(error))

        threading.Thread(target=background, daemon=True).start()

    def _run_cleanup_batches(self, kind: str):
        if kind == "consumed":
            return self._photo_cleanup_service.cleanup_all_consumed_photos(
                batch_size=100,
                progress_callback=lambda progress: self.after(0, lambda current=progress: self._update_cleanup_progress(current)),
                cancel_callback=lambda: self._cleanup_cancel_requested,
            )
        return self._photo_cleanup_service.cleanup_all_stale_reserved_photos(
            older_than_hours=2,
            batch_size=100,
            progress_callback=lambda progress: self.after(0, lambda current=progress: self._update_cleanup_progress(current)),
            cancel_callback=lambda: self._cleanup_cancel_requested,
        )

    def _run_photo_cleanup_task(self, *, busy_text: str, success_text: str, worker) -> None:
        if self._cleanup_running:
            return
        self._cleanup_mode = "single"
        self._set_photo_cleanup_busy(True, busy_text=busy_text)

        def background() -> None:
            try:
                result_type, payload = worker()
                self.after(
                    0,
                    lambda current_type=result_type, current_payload=payload: self._finish_photo_cleanup_task(
                        current_type,
                        current_payload,
                        success_text=success_text,
                    ),
                )
            except Exception as exc:
                self.after(0, lambda error=exc: self._finish_photo_cleanup_task_error(error))

        threading.Thread(target=background, daemon=True).start()

    def _finish_photo_cleanup_task(self, result_type: str, payload, *, success_text: str) -> None:
        self._set_photo_cleanup_busy(False)
        if result_type == "audit":
            self._apply_photo_cleanup_audit(payload)
            self.photo_cleanup_status_label.configure(text=success_text, text_color=SUCCESS)
            return
        self._apply_photo_cleanup_result(payload)
        self.photo_cleanup_status_label.configure(
            text=(
                f"{success_text} Eliminadas: {payload.deleted_count}. "
                f"Errores: {payload.error_count}."
            ),
            text_color=WARNING if payload.error_count else SUCCESS,
        )
        self._refresh_photo_cleanup_audit_async()

    def _finish_photo_cleanup_task_error(self, exc: Exception) -> None:
        self._set_photo_cleanup_busy(False)
        self.photo_cleanup_status_label.configure(
            text=f"Error en limpieza de fotos: {exc}",
            text_color=ERROR,
        )

    def _set_photo_cleanup_busy(self, is_busy: bool, *, busy_text: str | None = None) -> None:
        single_state = "disabled" if is_busy else "normal"
        cleanup_all_state = "disabled" if is_busy else "normal"
        cancel_state = "normal" if self._cleanup_running else "disabled"
        self.audit_pool_button.configure(state=single_state, text="Auditando..." if busy_text == "Auditando..." else "Auditar pool")
        self.cleanup_consumed_button.configure(
            state=single_state,
            text="Limpiando..." if busy_text == "Limpiando consumidas..." else "Limpiar 100 consumidas",
        )
        self.cleanup_stale_reserved_button.configure(
            state=single_state,
            text="Limpiando..." if busy_text == "Limpiando reservadas viejas..." else "Limpiar 100 reservadas viejas",
        )
        self.cleanup_all_consumed_button.configure(state=cleanup_all_state)
        self.cleanup_all_stale_reserved_button.configure(state=cleanup_all_state)
        self.cancel_cleanup_button.configure(state=cancel_state)
        if is_busy and busy_text:
            self.photo_cleanup_status_label.configure(text=busy_text, text_color=TEXT_PRIMARY)
        elif not self._cleanup_running:
            self.cancel_cleanup_button.configure(state="disabled")

    def _apply_photo_cleanup_audit(self, audit) -> None:
        self._set_photo_cleanup_summary_lines(
            [
                f"Disponibles: {audit.available_count}",
                f"Reservadas: {audit.reserved_count}",
                f"Usadas históricas: {audit.consumed_count}",
                f"Descartadas: {audit.discarded_count}",
                f"Consumidas pendientes de limpiar Storage: {audit.consumed_pending_storage_cleanup}",
                f"Consumidas pendientes limpiables: {audit.consumed_cleanable_pending_storage_cleanup}",
                f"Reservadas viejas pendientes: {audit.stale_reserved_pending_storage_cleanup}",
                f"Reservadas viejas limpiables: {audit.stale_reserved_cleanable_pending_storage_cleanup}",
                f"Archivos limpiados de Storage: {audit.storage_cleaned_count}",
                f"Errores de limpieza: {audit.cleanup_error_count}",
            ]
        )

    def _apply_photo_cleanup_result(self, result) -> None:
        lines = [
            f"Acción: {result.action}",
            f"Dry-run: {'sí' if result.dry_run else 'no'}",
            f"Límite: {result.limit}",
            f"Coincidencias: {result.matched_count}",
            f"Eliminadas de Storage: {result.deleted_count}",
            f"Saltadas: {result.skipped_count}",
            f"Errores: {result.error_count}",
        ]
        if result.older_than_hours is not None:
            lines.append(f"Antigüedad usada: {result.older_than_hours}h")
        self._set_photo_cleanup_summary_lines(lines)

    def _set_photo_cleanup_summary_lines(self, lines: list[str]) -> None:
        self.photo_cleanup_summary_box.configure(state="normal")
        self.photo_cleanup_summary_box.delete("1.0", "end")
        self.photo_cleanup_summary_box.insert("1.0", "\n".join(lines))
        self.photo_cleanup_summary_box.configure(state="disabled")

    def _update_cleanup_progress(self, progress) -> None:
        self._cleanup_progress_total = max(int(progress.total_initial), 0)
        self._cleanup_progress_done = max(int(progress.processed_count), 0)
        total = self._cleanup_progress_total
        done = min(self._cleanup_progress_done, total) if total > 0 else 0
        fraction = 0.0 if total <= 0 else max(0.0, min(done / total, 1.0))
        mode_label = "consumidas" if progress.kind == "consumed" else "reservadas viejas"
        self.cleanup_progress_bar.set(fraction)
        self.cleanup_progress_label.configure(text=f"Limpiando {mode_label}: {done} / {total}")
        self.cleanup_last_batch_label.configure(
            text=(
                f"Último lote: revisadas {progress.last_batch_matched} | "
                f"limpiadas {progress.last_batch_deleted} | "
                f"errores {progress.last_batch_errors} | "
                f"saltadas {progress.last_batch_skipped}"
            )
        )
        self.cleanup_remaining_label.configure(
            text=(
                f"Restantes: {progress.pending_current} | "
                f"Velocidad: {progress.photos_per_minute:.1f} fotos/min"
            )
        )

    def _finish_cleanup_batches(self, result) -> None:
        was_cancelled = self._cleanup_cancel_requested
        self._cleanup_running = False
        self._cleanup_cancel_requested = False
        self._set_photo_cleanup_busy(False)
        self._apply_photo_cleanup_result(result)
        if was_cancelled:
            self.photo_cleanup_status_label.configure(text="Limpieza cancelada por usuario.", text_color=WARNING)
        else:
            self.photo_cleanup_status_label.configure(
                text=(
                    f"Limpieza masiva completada. Eliminadas: {result.deleted_count}. "
                    f"Errores: {result.error_count}."
                ),
                text_color=WARNING if result.error_count else SUCCESS,
            )
        self._refresh_photo_cleanup_audit_async()

    def _finish_cleanup_batches_error(self, exc: Exception) -> None:
        self._cleanup_running = False
        self._cleanup_cancel_requested = False
        self._set_photo_cleanup_busy(False)
        self.photo_cleanup_status_label.configure(text=f"Error crítico en limpieza masiva: {exc}", text_color=ERROR)
        self._refresh_photo_cleanup_audit_async()

    def _cancel_cleanup(self) -> None:
        if not self._cleanup_running:
            return
        self._cleanup_cancel_requested = True
        self.photo_cleanup_status_label.configure(text="Cancelación solicitada. Se detendrá al terminar el lote actual.", text_color=WARNING)

    def _refresh_photo_cleanup_audit_async(self) -> None:
        def background() -> None:
            try:
                audit = self._photo_cleanup_service.audit()
                self.after(0, lambda current=audit: self._apply_photo_cleanup_audit(current))
            except Exception:
                return

        threading.Thread(target=background, daemon=True).start()
