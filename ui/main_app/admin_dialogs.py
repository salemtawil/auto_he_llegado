from __future__ import annotations

import json
import threading

import customtkinter as ctk

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
    TEXT_MUTED,
    TEXT_PRIMARY,
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
        self._diagnostics_payloads: dict[str, dict] = {}
        self._payload_visible = False
        self._diagnostics_loading = False
        self._current_snapshot: dict = {}

        container = ctk.CTkFrame(self, fg_color="transparent")
        container.pack(fill="both", expand=True, padx=20, pady=20)
        container.grid_columnconfigure(0, weight=1)
        container.grid_rowconfigure(0, weight=1)

        self.tabs = ctk.CTkTabview(container, corner_radius=20)
        self.tabs.grid(row=0, column=0, sticky="nsew")
        self.tabs.add("Carga")
        self.tabs.add("Diagnóstico")

        self._build_upload_tab(self.tabs.tab("Carga"), uploader_service)
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
