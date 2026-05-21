from __future__ import annotations

import contextlib
import json
import os
import platform
import re
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from time import monotonic
from tkinter import filedialog
from uuid import uuid4

import customtkinter as ctk

from automation.browser_manager import BrowserManager
from config.paths import DEFAULT_LOCAL_DATA_DIR
from config.settings import get_settings
from core.models import LocalConfig, ProcessExecutionRequest, ProcessExecutionResult
from core.validators import sanitize_phone_number, validate_non_empty_string, validate_positive_int
from services.last_result_service import LastResultService
from services.local_config_service import LocalConfigService
from services.log_service import LogService
from services.photo_pool_service import PhotoPoolService
from services.process_service import ProcessService
from ui.main_app.admin_dialogs import AdminPasswordDialog, AdminUploaderDialog
from ui.main_app.agent_name_dialog import AgentNameDialog
from ui.main_app.pool_badge import PoolBadge
from ui.main_app.process_slot_panel import ProcessSlotPanel
from ui.main_app.settings_dialog import SettingsDialog
from ui.theme import (
    ACCENT,
    ACCENT_SOFT,
    APP_BG,
    CARD_ALT_BG,
    ERROR,
    HEADER_BG,
    HEADER_BORDER,
    NEUTRAL_BUTTON,
    NEUTRAL_BUTTON_HOVER,
    SUCCESS,
    TEXT_MUTED,
    TEXT_PRIMARY,
    apply_theme_mode,
)


@dataclass
class ProcessSlotRuntime:
    slot_id: str
    panel: ProcessSlotPanel
    process_id: str | None = None
    last_process_id: str | None = None
    last_process_debug: dict | None = None
    last_result: ProcessExecutionResult | None = None
    thread: threading.Thread | None = None
    timer_started_at: float | None = None
    timer_running: bool = False
    timer_generation: int = 0
    execution_mode: str = "traditional"


class MainAppWindow(ctk.CTk):
    def __init__(
        self,
        config_service: LocalConfigService | None = None,
        photo_pool_service: PhotoPoolService | None = None,
        process_service: ProcessService | None = None,
        log_service: LogService | None = None,
        last_result_service: LastResultService | None = None,
    ) -> None:
        super().__init__()
        self._config_service = config_service or LocalConfigService()
        self._photo_pool_service = photo_pool_service or PhotoPoolService()
        self._process_service = process_service or ProcessService()
        self._log_service = log_service or LogService()
        self._last_result_service = last_result_service or LastResultService()
        self._settings = get_settings()
        self._current_config = self._config_service.load()
        self._settings_dialog: SettingsDialog | None = None
        self._agent_name_dialog: AgentNameDialog | None = None
        self._admin_password_dialog: AdminPasswordDialog | None = None
        self._admin_uploader_dialog: AdminUploaderDialog | None = None
        self._layout_mode = ""
        self._is_closing = False
        self._slots: dict[str, ProcessSlotRuntime] = {}
        self._process_to_slot: dict[str, str] = {}
        self._active_slot_id = "slot_1"
        self._latest_debug_slot_id = "slot_1"
        self._pending_admin_tab: str | None = None

        apply_theme_mode(self._current_config.theme_mode)
        self.title("Auto He Llegado")
        self.geometry("1280x760")
        self.minsize(1020, 680)
        self.configure(fg_color=APP_BG)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        self._build_header()
        self._build_content()
        self.bind("<Configure>", self._handle_window_resize)
        self.protocol("WM_DELETE_WINDOW", self._handle_app_close)
        self._safe_after(150, self.refresh_pool_count)
        self._safe_after(200, self.refresh_extension_status)
        self._safe_after(220, self._prompt_agent_name_if_needed)
        self._safe_after(50, lambda: self._apply_responsive_layout(self.winfo_width()))

    def _build_header(self) -> None:
        self.header = ctk.CTkFrame(
            self,
            fg_color=HEADER_BG,
            corner_radius=16,
            border_width=1,
            border_color=HEADER_BORDER,
        )
        self.header.grid(row=0, column=0, padx=10, pady=(8, 4), sticky="ew")
        self.header.grid_columnconfigure(0, weight=1)
        self.header.grid_columnconfigure(1, weight=0)
        self.header.grid_columnconfigure(2, weight=0)
        self.header.grid_rowconfigure(0, weight=1)

        self.title_wrap = ctk.CTkFrame(self.header, fg_color="transparent")
        self.title_wrap.grid(row=0, column=0, padx=(12, 12), pady=7, sticky="w")
        self.title_wrap.grid_columnconfigure(0, weight=1)

        self.title_label = ctk.CTkLabel(
            self.title_wrap,
            text="Auto He Llegado",
            font=ctk.CTkFont(size=17, weight="bold"),
            text_color=TEXT_PRIMARY,
        )
        self.title_label.grid(row=0, column=0, sticky="w")

        self.header_meta_label = ctk.CTkLabel(
            self.title_wrap,
            text="Motor: Tradicional | Procesos activos: 0/2",
            font=ctk.CTkFont(size=8, weight="bold"),
            text_color=TEXT_MUTED,
        )
        self.header_meta_label.grid(row=1, column=0, pady=(2, 0), sticky="w")

        self.header_status_label = ctk.CTkLabel(
            self.title_wrap,
            text="",
            font=ctk.CTkFont(size=1),
            text_color=TEXT_MUTED,
        )
        self.header_status_label.grid_forget()

        self.pool_badge = PoolBadge(self.header, refresh_callback=self.refresh_pool_count)
        self.pool_badge.grid(row=0, column=1, padx=(0, 16), pady=6, sticky="nsew")

        self.header_actions = ctk.CTkFrame(self.header, fg_color="transparent")
        self.header_actions.grid(row=0, column=2, padx=(0, 12), pady=6, sticky="nsew")
        self.header_actions.grid_rowconfigure(0, weight=1)
        for column in range(5):
            self.header_actions.grid_columnconfigure(column, weight=1)

        self.refresh_button = self._create_header_tile(
            self.header_actions,
            icon="⟳",
            text="Refrescar",
            command=self.refresh_pool_count,
        )
        self.refresh_button.grid(row=0, column=0, padx=(0, 6), sticky="nsew")

        self.admin_button = self._create_header_tile(
            self.header_actions,
            icon="◈",
            text="Admin",
            command=self._open_admin_home,
        )
        self.admin_button.grid(row=0, column=1, padx=(0, 6), sticky="nsew")

        self.uploader_button = self._create_header_tile(
            self.header_actions,
            icon="⤴",
            text="Uploader",
            command=lambda: self._open_admin_tool("Carga"),
        )
        self.uploader_button.grid(row=0, column=2, padx=(0, 6), sticky="nsew")

        self.cleanup_button = self._create_header_tile(
            self.header_actions,
            icon="✦",
            text="Limpieza",
            command=lambda: self._open_admin_tool("Limpieza fotos"),
        )
        self.cleanup_button.grid(row=0, column=3, padx=(0, 6), sticky="nsew")

        self.settings_button = self._create_header_tile(
            self.header_actions,
            icon="⚙",
            text="Configuracion",
            command=self.open_settings_dialog,
            highlighted=True,
        )
        self.settings_button.grid(row=0, column=4, sticky="nsew")
        self._refresh_header_summary()

    def _create_header_tile(self, master, *, icon: str, text: str, command, highlighted: bool = False):
        border_color = ACCENT if highlighted else HEADER_BORDER
        fg_color = CARD_ALT_BG
        text_color = ACCENT if highlighted else TEXT_PRIMARY
        tile = ctk.CTkFrame(
            master,
            fg_color=fg_color,
            corner_radius=12,
            border_width=1,
            border_color=border_color,
            width=96,
            height=76,
        )
        tile.grid_propagate(False)
        tile.grid_columnconfigure(0, weight=1)
        tile.grid_rowconfigure(0, weight=1)
        tile.grid_rowconfigure(1, weight=1)

        icon_label = ctk.CTkLabel(
            tile,
            text=icon,
            text_color=ACCENT,
            font=ctk.CTkFont(size=20, weight="bold"),
        )
        icon_label.grid(row=0, column=0, padx=0, pady=(10, 0), sticky="s")

        text_label = ctk.CTkLabel(
            tile,
            text=text,
            text_color=text_color,
            font=ctk.CTkFont(size=10, weight="bold"),
        )
        text_label.grid(row=1, column=0, padx=6, pady=(0, 10), sticky="n")

        def on_enter(_event=None):
            tile.configure(border_color=ACCENT, fg_color=NEUTRAL_BUTTON_HOVER)

        def on_leave(_event=None):
            tile.configure(border_color=border_color, fg_color=fg_color)

        def on_click(_event=None):
            command()

        for widget in (tile, icon_label, text_label):
            widget.bind("<Enter>", on_enter)
            widget.bind("<Leave>", on_leave)
            widget.bind("<Button-1>", on_click)

        return tile

    def _build_content(self) -> None:
        self.content = ctk.CTkFrame(self, fg_color="transparent")
        self.content.grid(row=1, column=0, padx=10, pady=(0, 10), sticky="nsew")
        self.content.grid_columnconfigure(0, weight=1)
        self.content.grid_rowconfigure(0, weight=1)

        self.main_column = ctk.CTkFrame(self.content, fg_color="transparent")
        self.main_column.grid(row=0, column=0, sticky="nsew")
        self.main_column.grid_columnconfigure(0, weight=1)
        self.main_column.grid_rowconfigure(0, weight=1)
        self.main_column.grid_rowconfigure(1, weight=1)

        slot_1_panel = ProcessSlotPanel(
            self.main_column,
            title="Proceso 1",
            on_start=lambda: self.start_process("slot_1"),
            on_clear=lambda: self.clear_form("slot_1"),
            on_export_state=lambda: self.export_extension_state("slot_1"),
            on_open_diagnostics=self._open_diagnostics_panel,
            on_open_extensions=lambda: self.open_extension_test_browser("slot_1"),
            on_open_browser=lambda: self.open_manual_browser("slot_1"),
        )

        slot_2_panel = ProcessSlotPanel(
            self.main_column,
            title="Proceso 2",
            on_start=lambda: self.start_process("slot_2"),
            on_clear=lambda: self.clear_form("slot_2"),
            on_export_state=lambda: self.export_extension_state("slot_2"),
            on_open_diagnostics=self._open_diagnostics_panel,
            on_open_extensions=lambda: self.open_extension_test_browser("slot_2"),
            on_open_browser=lambda: self.open_manual_browser("slot_2"),
        )

        self._slots = {
            "slot_1": ProcessSlotRuntime(slot_id="slot_1", panel=slot_1_panel),
            "slot_2": ProcessSlotRuntime(slot_id="slot_2", panel=slot_2_panel),
        }

        self._sync_primary_slot_refs()

    def open_settings_dialog(self) -> None:
        if self._settings_dialog is not None and self._settings_dialog.winfo_exists():
            self._settings_dialog.focus()
            return
        self._settings_dialog = SettingsDialog(
            self,
            config=self._current_config,
            on_save=self.save_local_config,
        )
        self._settings_dialog.focus()

    def open_admin_access(self) -> None:
        if self._admin_uploader_dialog is not None and self._admin_uploader_dialog.winfo_exists():
            self._apply_pending_admin_tab()
            self._admin_uploader_dialog.focus()
            return
        if self._admin_password_dialog is not None and self._admin_password_dialog.winfo_exists():
            self._admin_password_dialog.focus()
            return
        self._admin_password_dialog = AdminPasswordDialog(self, on_submit=self._validate_admin_access)
        self._admin_password_dialog.focus()

    def _open_admin_home(self) -> None:
        self._pending_admin_tab = None
        self.open_admin_access()

    def _open_admin_tool(self, tab_name: str) -> None:
        self._pending_admin_tab = tab_name
        self.open_admin_access()

    def _open_diagnostics_panel(self) -> None:
        self._open_admin_tool("Diagnóstico")

    def _validate_admin_access(self, password: str) -> None:
        if password != self._settings.admin_access_password:
            if self._admin_password_dialog is not None and self._admin_password_dialog.winfo_exists():
                self._admin_password_dialog.set_error("Contrasena incorrecta. Acceso Admin denegado.")
            self._broadcast_status_message("Acceso Admin denegado por contrasena incorrecta.", color=ERROR)
            return

        if self._admin_password_dialog is not None and self._admin_password_dialog.winfo_exists():
            self._admin_password_dialog.destroy()
        self._admin_password_dialog = None

        self._admin_uploader_dialog = AdminUploaderDialog(
            self,
            on_test_log=self.insert_test_log_from_admin,
            diagnostics_provider=self._build_admin_diagnostics_payload,
            on_refresh_diagnostics=self.refresh_extension_status,
            on_export_debug=self._handle_admin_export_debug,
        )
        self._apply_pending_admin_tab()
        self._admin_uploader_dialog.focus()
        self._broadcast_status_message("Acceso Admin concedido. Modulo de carga abierto.", color=SUCCESS)

    def save_local_config(self, data: dict[str, str] | None = None) -> None:
        try:
            config = self._extract_local_config(data)
            self._persist_local_config(config)
            if self._settings_dialog is not None and self._settings_dialog.winfo_exists():
                self._settings_dialog.destroy()
            self._settings_dialog = None
            self._broadcast_status_message(
                "Configuracion local guardada correctamente.",
                color=SUCCESS,
            )
        except Exception as exc:
            self._broadcast_status_message(f"Error al guardar configuracion: {exc}", color=ERROR)

    def toggle_theme_mode(self) -> None:
        next_mode = "dark" if self._current_config.theme_mode == "light" else "light"
        config = self._current_config.model_copy(update={"theme_mode": next_mode})
        try:
            self._persist_local_config(config)
            self._broadcast_status_message(
                f"Tema cambiado a {'oscuro' if next_mode == 'dark' else 'claro'} y guardado localmente.",
                color=SUCCESS,
            )
            if self._settings_dialog is not None and self._settings_dialog.winfo_exists():
                self._settings_dialog.destroy()
                self._settings_dialog = None
        except Exception as exc:
            self._broadcast_status_message(f"No se pudo cambiar el tema: {exc}", color=ERROR)

    def _persist_local_config(self, config: LocalConfig) -> None:
        previous_theme_mode = self._current_config.theme_mode
        self._current_config = self._config_service.save(config)
        apply_theme_mode(self._current_config.theme_mode)
        self.refresh_extension_status()
        if previous_theme_mode != self._current_config.theme_mode:
            self._refresh_theme_widgets()
        self._sync_theme_toggle_button()
        self._sync_run_button_state()
        self._refresh_header_summary()

    def _prompt_agent_name_if_needed(self) -> None:
        if self._current_config.agent_name_confirmed:
            return
        if self._agent_name_dialog is not None and self._agent_name_dialog.winfo_exists():
            self._agent_name_dialog.focus()
            return
        self._agent_name_dialog = AgentNameDialog(
            self,
            current_value="" if self._current_config.agent_name == "Agente Local" else self._current_config.agent_name,
            on_submit=self._save_agent_name_from_dialog,
        )
        self._agent_name_dialog.focus()

    def _save_agent_name_from_dialog(self, raw_name: str) -> None:
        try:
            validated_name = validate_non_empty_string(raw_name, "agent_name")
            updated = self._current_config.model_copy(
                update={"agent_name": validated_name, "agent_name_confirmed": True}
            )
            self._persist_local_config(updated)
            if self._agent_name_dialog is not None and self._agent_name_dialog.winfo_exists():
                self._agent_name_dialog.destroy()
            self._agent_name_dialog = None
            self._broadcast_status_message("Nombre del agente guardado localmente.", color=SUCCESS)
        except Exception as exc:
            if self._agent_name_dialog is not None and self._agent_name_dialog.winfo_exists():
                self._agent_name_dialog.set_error(str(exc))

    def _handle_last_result_filter_change(self, mode: str) -> None:
        if mode == self._current_config.last_result_filter:
            return
        updated = self._current_config.model_copy(update={"last_result_filter": mode})
        self._persist_local_config(updated)

    def _refresh_theme_widgets(self) -> None:
        self.configure(fg_color=APP_BG)
        self._refresh_widget_tree(self)
        self.update_idletasks()

    def _sync_theme_toggle_button(self) -> None:
        return

    def _handle_window_resize(self, event) -> None:
        if event.widget is not self:
            return
        self._apply_responsive_layout(event.width)

    def _apply_responsive_layout(self, width: int) -> None:
        mode = "fixed"
        if mode == self._layout_mode:
            return
        self._layout_mode = mode
        self._layout_header(mode)
        self._layout_slots(mode)
        self.pool_badge.set_compact_layout(False)

    def _layout_header(self, mode: str) -> None:
        return

    def _layout_slots(self, mode: str) -> None:
        slot_1 = self._slots["slot_1"].panel
        slot_2 = self._slots["slot_2"].panel

        for slot in self._slots.values():
            slot.panel.grid_forget()
            slot.panel.set_secondary_visual(False)
            slot.panel.set_compact_layout(False)

        self._sync_primary_slot_refs()
        self.main_column.grid(row=0, column=0, sticky="nsew")
        self.main_column.grid_columnconfigure(0, weight=1)
        self.main_column.grid_columnconfigure(1, weight=0)
        slot_1.grid(row=0, column=0, pady=(0, 10), sticky="ew")
        slot_2.grid(row=1, column=0, sticky="nsew")

        self._refresh_header_summary()

    def _sync_primary_slot_refs(self) -> None:
        primary_panel = (
            self._slots[self._active_slot_id].panel
            if self._active_slot_id in self._slots
            else self._slots["slot_1"].panel
        )
        self.form_panel = primary_panel.form_panel
        self.status_panel = primary_panel.status_panel
        self.current_result_panel = primary_panel.current_result_panel
        self.extension_status_panel = primary_panel.extension_status_panel
        self.run_button = primary_panel.run_button
        self.clear_button = primary_panel.clear_button

    def _apply_pending_admin_tab(self) -> None:
        if self._pending_admin_tab is None:
            return
        if self._admin_uploader_dialog is None or not self._admin_uploader_dialog.winfo_exists():
            return
        with contextlib.suppress(Exception):
            self._admin_uploader_dialog.tabs.set(self._pending_admin_tab)
        self._pending_admin_tab = None

    def _refresh_header_summary(self) -> None:
        if not hasattr(self, "header_meta_label") or not self._slots:
            return
        primary_slot_id = self._active_slot_id if self._active_slot_id in self._slots else "slot_1"
        primary_slot = self._get_slot(primary_slot_id)
        page_name = primary_slot.panel.form_panel.page_menu.get() or "N/A"
        slot_title = "Proceso 1" if primary_slot_id == "slot_1" else "Proceso 2"
        engine_label = self._flow_engine_label(self._current_config.flow_engine)
        self.header_meta_label.configure(
            text=f"Motor: {engine_label} | Procesos activos: {self._active_process_count()}/2 | Principal: {slot_title} | Pagina: {page_name}"
        )

    def _refresh_widget_tree(self, widget) -> None:
        theme_keys = (
            "fg_color",
            "bg_color",
            "border_color",
            "text_color",
            "hover_color",
            "button_color",
            "button_hover_color",
            "dropdown_fg_color",
            "dropdown_hover_color",
            "dropdown_text_color",
        )
        for key in theme_keys:
            try:
                current_value = widget.cget(key)
            except Exception:
                continue
            try:
                widget.configure(**{key: current_value})
            except Exception:
                continue
        for child in widget.winfo_children():
            self._refresh_widget_tree(child)

    def _get_slot(self, slot_id: str) -> ProcessSlotRuntime:
        return self._slots[slot_id]

    def _active_process_count(self) -> int:
        return sum(1 for slot in self._slots.values() if slot.thread is not None)

    def _slot_process_count_label(self) -> str:
        return f"Procesos activos: {self._active_process_count()}/2"

    def _set_slot_summary(self, slot_id: str, text: str) -> None:
        panel = self._get_slot(slot_id).panel
        if hasattr(panel, "set_summary"):
            try:
                panel.set_summary(text)
            except Exception:
                pass
        elif hasattr(panel, "summary_label"):
            try:
                panel.summary_label.configure(text=text)
            except Exception:
                pass
        if slot_id == self._active_slot_id:
            self._refresh_header_summary()

    def _set_slot_status(self, slot_id: str, message: str, *, color: str | None = None) -> None:
        slot = self._get_slot(slot_id)
        slot.panel.status_panel.set_message(message, color=color)
        self._set_slot_summary(slot_id, message.splitlines()[0][:110] if message else "Sin actividad reciente.")

    def _broadcast_status_message(self, message: str, *, color: str | None = None) -> None:
        for slot_id in self._slots:
            try:
                self._set_slot_status(slot_id, message, color=color)
            except Exception:
                continue

    def refresh_pool_count(self) -> None:
        if self._is_closing:
            return
        self.pool_badge.set_loading()
        thread = threading.Thread(target=self._refresh_pool_worker, daemon=True)
        thread.start()

    def _refresh_pool_worker(self) -> None:
        try:
            snapshot = self._photo_pool_service.get_snapshot()
            self._safe_after(0, lambda: self._apply_pool_snapshot(snapshot))
        except Exception as exc:
            error_message = f"No se pudo consultar el contador: {exc}"
            self._safe_after(0, lambda message=error_message: self._broadcast_status_message(message, color=ERROR))

    def _apply_pool_snapshot(self, snapshot) -> None:
        self.pool_badge.set_snapshot(snapshot)
        self._refresh_header_summary()

    def start_process(self, slot_id: str) -> None:
        if self._is_closing:
            return
        slot = self._get_slot(slot_id)
        active_count = self._active_process_count()
        current_flow_engine = (self._current_config.flow_engine or "").strip().lower()
        if slot.thread is not None:
            self._set_slot_status(slot_id, "Este panel ya tiene un proceso en ejecución.", color=ERROR)
            return
        if active_count >= 2:
            self._set_slot_status(slot_id, "Ya hay 2 procesos activos.", color=ERROR)
            return
        if active_count >= 1 and current_flow_engine != "traditional":
            self._set_slot_status(
                slot_id,
                "Ya hay un proceso en ejecución. El modo paralelo aún no está habilitado.",
                color=ERROR,
            )
            return

        process_id = str(uuid4())
        try:
            request = self._build_process_request(slot_id, process_id=process_id)
        except Exception as exc:
            self._set_slot_status(slot_id, f"Formulario invalido: {exc}", color=ERROR)
            return

        self._process_service.register_process_slot(process_id, slot_id)
        slot.process_id = request.process_id
        slot.last_process_id = request.process_id
        slot.last_process_debug = None
        slot.execution_mode = (request.execution_mode or "").strip().lower()
        slot.panel.status_panel.clear_persistent_alert()
        slot.panel.status_panel.clear_retry_indicator()
        self._process_to_slot[process_id] = slot_id
        self._active_slot_id = slot_id
        self._latest_debug_slot_id = slot_id
        self._layout_slots(self._layout_mode or "wide")
        slot.thread = threading.Thread(
            target=self._run_process_worker,
            args=(slot_id, process_id, request),
            daemon=False,
        )
        BrowserManager.begin_new_run(flow_engine=self._current_config.flow_engine)
        self._start_process_timer(slot_id, process_id)
        self.refresh_extension_status()
        self._set_slot_status(
            slot_id,
            (
                f"Procesando solicitud... Motor: {self._flow_engine_label(self._current_config.flow_engine)}. "
                f"{self._slot_process_count_label()}"
            ),
        )
        self._sync_run_button_state()
        slot.thread.start()

    def _run_process_worker(self, slot_id: str, process_id: str, request: ProcessExecutionRequest) -> None:
        try:
            result = self._process_service.execute(
                request,
                progress_callback=lambda phase, message, current_slot_id=slot_id: self._schedule_process_progress(
                    current_slot_id,
                    phase,
                    message,
                ),
            )
            self._safe_after(
                0,
                lambda current_slot_id=slot_id, current_process_id=process_id, current_result=result: self._finish_process(
                    current_slot_id,
                    current_process_id,
                    current_result,
                ),
            )
        except Exception as exc:
            self._safe_after(
                0,
                lambda current_slot_id=slot_id, current_process_id=process_id, error=exc: self._handle_process_error(
                    current_slot_id,
                    current_process_id,
                    error,
                ),
            )

    def _finish_process(self, slot_id: str, process_id: str, result: ProcessExecutionResult) -> None:
        elapsed_seconds = self._finalize_process_tracking(slot_id, process_id)
        if self._is_closing:
            return
        slot = self._get_slot(slot_id)
        slot.last_process_debug = self._process_service.get_process_debug_export(process_id, slot_id=slot_id)
        slot.last_result = result
        timing_summary_text = self._build_status_timing_summary(process_id)
        slot.panel.current_result_panel.set_result(
            result,
            elapsed_text=self._format_elapsed_time(elapsed_seconds),
        )
        self._set_slot_status(
            slot_id,
            (
                f"{result.message} Tiempo final: {self._format_elapsed_time(elapsed_seconds)}. "
                f"{timing_summary_text} "
                f"{self._slot_process_count_label()}"
            ),
            color=SUCCESS if result.success else ERROR,
        )
        self._refresh_admin_diagnostics_if_open()
        self.refresh_extension_status()

    def _handle_process_error(self, slot_id: str, process_id: str, exc: Exception) -> None:
        elapsed_seconds = self._finalize_process_tracking(slot_id, process_id)
        if self._is_closing:
            return
        slot = self._get_slot(slot_id)
        slot.last_process_debug = self._process_service.get_process_debug_export(process_id, slot_id=slot_id)
        self._set_slot_status(
            slot_id,
            (
                f"Error en el proceso: {exc}. Tiempo final: {self._format_elapsed_time(elapsed_seconds)}. "
                f"{self._slot_process_count_label()}"
            ),
            color=ERROR,
        )
        self._refresh_admin_diagnostics_if_open()

    def _start_process_timer(self, slot_id: str, process_id: str) -> None:
        slot = self._get_slot(slot_id)
        slot.process_id = process_id
        slot.timer_started_at = monotonic()
        slot.timer_running = True
        slot.timer_generation += 1
        generation = slot.timer_generation
        slot.panel.process_timer_label.configure(text=f"Tiempo: 00:00 | {self._slot_process_count_label()}")
        self._update_process_timer(slot_id, generation)

    def _update_process_timer(self, slot_id: str, generation: int) -> None:
        if self._is_closing:
            return
        slot = self._get_slot(slot_id)
        if not slot.timer_running or generation != slot.timer_generation or slot.timer_started_at is None:
            return
        elapsed_seconds = int(monotonic() - slot.timer_started_at)
        slot.panel.process_timer_label.configure(
            text=f"Tiempo: {self._format_elapsed_time(elapsed_seconds)} | {self._slot_process_count_label()}"
        )
        self._safe_after(
            1000,
            lambda current_slot_id=slot_id, current_generation=generation: self._update_process_timer(
                current_slot_id,
                current_generation,
            ),
        )

    def _stop_process_timer(
        self,
        slot_id: str,
        *,
        prefix: str = "Tiempo final",
        elapsed_seconds: int | None = None,
    ) -> None:
        slot = self._get_slot(slot_id)
        slot.timer_running = False
        slot.timer_generation += 1
        started_at = slot.timer_started_at
        slot.timer_started_at = None
        if started_at is None:
            slot.panel.process_timer_label.configure(text=f"{prefix}: 00:00 | {self._slot_process_count_label()}")
            return
        final_elapsed_seconds = elapsed_seconds if elapsed_seconds is not None else int(monotonic() - started_at)
        slot.panel.process_timer_label.configure(
            text=f"{prefix}: {self._format_elapsed_time(final_elapsed_seconds)} | {self._slot_process_count_label()}"
        )

    def _finalize_process_tracking(self, slot_id: str, process_id: str) -> int:
        slot = self._get_slot(slot_id)
        started_at = slot.timer_started_at
        elapsed_seconds = max(int(monotonic() - started_at), 0) if started_at is not None else 0
        self._stop_process_timer(slot_id, elapsed_seconds=elapsed_seconds)
        slot.last_process_id = process_id
        slot.process_id = None
        slot.thread = None
        self._process_to_slot.pop(process_id, None)
        if self._latest_debug_slot_id == slot_id and self._active_process_count() == 0:
            self._latest_debug_slot_id = "slot_1"
        self._sync_run_button_state()
        self._layout_slots(self._layout_mode or "wide")
        return elapsed_seconds

    def _sync_run_button_state(self) -> None:
        if self._is_closing:
            return
        active_count = self._active_process_count()
        current_flow_engine = (self._current_config.flow_engine or "").strip().lower()
        for slot in self._slots.values():
            if slot.thread is not None:
                slot.panel.run_button.configure(state="disabled")
                continue
            disabled = active_count >= 2 or (active_count >= 1 and current_flow_engine != "traditional")
            slot.panel.run_button.configure(state="disabled" if disabled else "normal")
        self._refresh_header_summary()

    @staticmethod
    def _format_elapsed_time(elapsed_seconds: int) -> str:
        elapsed_seconds = max(elapsed_seconds, 0)
        minutes, seconds = divmod(elapsed_seconds, 60)
        hours, minutes = divmod(minutes, 60)
        if hours:
            return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
        return f"{minutes:02d}:{seconds:02d}"

    def clear_form(self, slot_id: str) -> None:
        slot = self._get_slot(slot_id)
        slot.panel.form_panel.clear()
        slot.panel.status_panel.clear_persistent_alert()
        slot.panel.status_panel.clear_retry_indicator()
        self._set_slot_status(slot_id, "Formulario limpiado manualmente.")

    def open_extension_test_browser(self, slot_id: str) -> None:
        if self._is_closing:
            return
        self._latest_debug_slot_id = slot_id
        self._set_slot_status(slot_id, "Abriendo Chromium con la extension y navegando a chrome://extensions...")
        thread = threading.Thread(target=self._open_extension_test_browser_worker, args=(slot_id,), daemon=True)
        thread.start()

    def open_manual_browser(self, slot_id: str) -> None:
        if self._is_closing:
            return
        self._latest_debug_slot_id = slot_id
        page_name = self._get_slot(slot_id).panel.form_panel.get_form_data()["page_name"]
        target_url = self._manual_browser_target_url(page_name)
        engine_label = self._flow_engine_label(self._current_config.flow_engine)
        self._set_slot_status(
            slot_id,
            f"Abriendo Chromium manualmente. Motor: {engine_label}. Destino: {target_url}",
        )
        thread = threading.Thread(
            target=self._open_manual_browser_worker,
            args=(slot_id, target_url),
            daemon=True,
        )
        thread.start()

    def export_extension_state(self, slot_id: str) -> None:
        if self._is_closing:
            return
        slot = self._get_slot(slot_id)
        page_name = slot.panel.form_panel.get_form_data().get("page_name") or "Paripe"
        process_id = slot.process_id or slot.last_process_id
        process_payload = dict(slot.last_process_debug or {})
        if not process_payload:
            process_payload = self._process_service.get_process_debug_export(process_id, slot_id=slot_id)
        if not isinstance(process_payload, dict):
            process_payload = {}
        process_payload = {
            **process_payload,
            "process_id": process_payload.get("process_id") or process_id,
            "page_name": process_payload.get("page_name") or page_name,
            "slot_id": process_payload.get("slot_id") or slot_id,
        }
        session = BrowserManager.get_latest_session() if slot_id == self._latest_debug_slot_id else None
        payload = None
        browser_export_warning = None
        if session is not None:
            try:
                payload = (
                    session.capture_extension_debug(page=session.page, note="manual_process_export")
                    or session.get_last_extension_debug()
                )
            except Exception as exc:
                browser_export_warning = str(exc)
                payload = session.get_last_extension_debug() or BrowserManager.get_latest_extension_debug()
        elif slot_id == self._latest_debug_slot_id:
            payload = BrowserManager.get_latest_extension_debug()
        else:
            payload = {
                "note": "Export parcial: BrowserManager latest_* solo refleja la sesion mas reciente.",
                "slot_id": slot_id,
            }
        body_text = ""
        current_url = ""
        frames_payload: dict | list = []
        if session is not None:
            with contextlib.suppress(Exception):
                current_url = session.page.url
            with contextlib.suppress(Exception):
                body_text = session.page.locator("body").first.inner_text(timeout=700).strip()
            try:
                frames_payload = session.debug_list_all_frames(page=session.page)
            except Exception as exc:
                if browser_export_warning is None:
                    browser_export_warning = str(exc)
                last_frame_report = {}
                if isinstance(payload, dict):
                    last_frame_report = dict(payload.get("frame_debug_report") or {})
                frames_payload = last_frame_report or {"total_frames": 0, "frames": [], "error": str(exc)}

        if not payload and not process_payload:
            self._set_slot_status(slot_id, "No hay estado del proceso disponible para exportar.", color=ERROR)
            return

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        default_dir = DEFAULT_LOCAL_DATA_DIR / "debug"
        default_dir.mkdir(parents=True, exist_ok=True)
        default_name = f"process_state_{page_name.lower()}_{slot_id}_{timestamp}.json"
        target = filedialog.asksaveasfilename(
            parent=self,
            title="Exportar estado del proceso",
            initialdir=str(default_dir),
            initialfile=default_name,
            defaultextension=".json",
            filetypes=[("JSON", "*.json")],
        )
        if not target:
            return

        export_payload = {
            "exportedAt": datetime.now().isoformat(),
            "slotId": slot_id,
            "processId": process_id,
            "flowEngine": self._current_config.flow_engine,
            "pageName": page_name,
            "browser_state": payload,
            "browser_export_warning": browser_export_warning,
            "current_url": current_url,
            "body_text": body_text,
            "frames": frames_payload,
            "phase_history": ((payload or {}).get("engine_phase_history") or []),
            "process_debug": process_payload,
            "timeline": process_payload.get("timeline", []) if isinstance(process_payload, dict) else [],
            "timing_summary": process_payload.get("timing_summary", {}) if isinstance(process_payload, dict) else {},
            "last_final_button_candidate": process_payload.get("last_final_button_candidate", {}) if isinstance(process_payload, dict) else {},
        }
        try:
            Path(target).write_text(json.dumps(export_payload, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception as exc:
            self._set_slot_status(slot_id, f"No se pudo exportar el estado del proceso: {exc}", color=ERROR)
            return

        self._set_slot_status(slot_id, f"Estado del proceso exportado a {target}", color=SUCCESS)

    def _handle_admin_export_debug(self, slot_name: str) -> None:
        slot_id = "slot_1" if slot_name == "Proceso 1" else "slot_2"
        self.export_extension_state(slot_id)

    def _refresh_admin_diagnostics_if_open(self) -> None:
        if self._admin_uploader_dialog is None or not self._admin_uploader_dialog.winfo_exists():
            return
        with contextlib.suppress(Exception):
            self._admin_uploader_dialog.mark_diagnostics_stale()

    def _build_admin_diagnostics_payload(self) -> dict[str, dict]:
        payload: dict[str, dict] = {}
        for slot_id, slot in self._slots.items():
            payload["Proceso 1" if slot_id == "slot_1" else "Proceso 2"] = self._build_slot_diagnostic_snapshot(slot_id)
        return payload

    def _build_slot_diagnostic_snapshot(self, slot_id: str) -> dict:
        slot = self._get_slot(slot_id)
        process_id = slot.process_id or slot.last_process_id
        process_debug = dict(slot.last_process_debug or {})
        if not process_debug:
            process_debug = self._process_service.get_process_debug_export(process_id, slot_id=slot_id)
        if not isinstance(process_debug, dict):
            process_debug = {}
        process_debug = {
            **process_debug,
            "process_id": process_debug.get("process_id") or process_id,
            "page_name": process_debug.get("page_name") or slot.panel.form_panel.get_form_data().get("page_name"),
            "slot_id": process_debug.get("slot_id") or slot_id,
        }
        session = BrowserManager.get_latest_session() if slot_id == self._latest_debug_slot_id else None
        latest_debug = BrowserManager.get_latest_extension_debug() or {}
        session_debug = latest_debug
        frames_payload: dict | list = []
        browser_export_warning = None
        session_active = session is not None
        if session is not None:
            session_debug = session.get_last_extension_debug() or latest_debug
            try:
                frames_payload = session.debug_list_all_frames(page=session.page)
            except Exception as exc:
                browser_export_warning = str(exc)
                frames_payload = dict(session_debug.get("frame_debug_report") or {}) or {"total_frames": 0, "frames": [], "error": str(exc)}
        elif not latest_debug:
            session_debug = {
                "note": "Diagnostico limitado: BrowserManager latest_* solo refleja la sesion mas reciente.",
            }

        result = slot.last_result
        elapsed_text = None
        if result is not None:
            status_text = "Exitoso" if result.success else result.final_status or result.phase or "Sin estado"
            elapsed_text = self._extract_elapsed_from_message(result.message)
        else:
            status_text = "En ejecucion" if slot.thread is not None else "Sin resultado"

        return {
            "process_id": process_id,
            "result": result,
            "elapsed_text": elapsed_text,
            "status_summary": status_text,
            "flow_engine": self._current_config.flow_engine,
            "extension_requested": self._current_config.flow_engine == "extension",
            "session_active": session_active,
            "session_debug": session_debug,
            "browser_export_warning": browser_export_warning,
            "process_debug": process_debug,
            "timeline": process_debug.get("timeline", []) if isinstance(process_debug, dict) else [],
            "timing_summary": process_debug.get("timing_summary", {}) if isinstance(process_debug, dict) else {},
            "last_final_button_candidate": (
                process_debug.get("last_final_button_candidate", {}) if isinstance(process_debug, dict) else {}
            ),
            "frames": frames_payload,
        }

    def _build_status_timing_summary(self, process_id: str | None) -> str:
        slot_id = self._process_to_slot.get(process_id or "")
        process_debug = self._process_service.get_process_debug_export(process_id, slot_id=slot_id)
        if not isinstance(process_debug, dict):
            return ""
        timing_summary = process_debug.get("timing_summary") or {}
        if not isinstance(timing_summary, dict):
            return str(process_debug.get("timing_summary_text") or "").strip()
        parts: list[str] = []
        label_map = {
            "login": "login",
            "selfie_validation": "selfie",
            "block_wait": "bloque",
            "final_click": "final",
            "total": "total",
        }
        for key in ("login", "selfie_validation", "block_wait", "final_click", "total"):
            value = str(timing_summary.get(key) or "").strip()
            if value:
                parts.append(f"{label_map[key]} {value}")
        return f"Resumen tiempos: {' | '.join(parts)}." if parts else ""

    @staticmethod
    def _extract_elapsed_from_message(message: str) -> str | None:
        match = re.search(r"Tiempo final:\s*([0-9:]+)", message or "")
        if match is None:
            return None
        return match.group(1)

    def _open_extension_test_browser_worker(self, slot_id: str) -> None:
        try:
            session = self._open_browser_with_extension_session(
                keep_open=True,
                extension_overlay=self._current_config.browser_extension_overlay,
            )
            session.page.goto("chrome://extensions", wait_until="load", timeout=30_000)
            self._safe_after(0, lambda: self._finish_open_extension_test_browser(slot_id, session))
        except Exception as exc:
            self._safe_after(
                0,
                lambda error=exc, current_slot_id=slot_id: self._set_slot_status(
                    current_slot_id,
                    f"No se pudo abrir chrome://extensions con la extension: {error}",
                    color=ERROR,
                ),
            )

    def _finish_open_extension_test_browser(self, slot_id: str, session) -> None:
        self.refresh_extension_status()
        debug = session.get_last_extension_debug() or BrowserManager.get_latest_extension_debug() or {}
        browser_channel = str(debug.get("browser_channel") or "chrome").strip() or "chrome"
        worker_url = session.extension_service_worker_url or "sin service worker"
        self._set_slot_status(
            slot_id,
            f"{browser_channel.title()} abierto en chrome://extensions. Service worker: {worker_url}",
            color=SUCCESS if session.extension_loaded else ERROR,
        )

    def _open_manual_browser_worker(self, slot_id: str, target_url: str) -> None:
        try:
            session = self._open_browser_with_extension_session(
                keep_open=True,
                extension_overlay=self._current_config.browser_extension_overlay,
            )
            session.page.goto(target_url, wait_until="load", timeout=30_000)
            self._safe_after(0, lambda: self._finish_open_manual_browser(slot_id, session, target_url))
        except Exception as exc:
            self._safe_after(
                0,
                lambda error=exc, current_slot_id=slot_id: self._set_slot_status(
                    current_slot_id,
                    f"No se pudo abrir el navegador manual: {error}",
                    color=ERROR,
                ),
            )

    def _finish_open_manual_browser(self, slot_id: str, session, target_url: str) -> None:
        self.refresh_extension_status()
        debug = session.get_last_extension_debug() or BrowserManager.get_latest_extension_debug() or {}
        browser_channel = str(debug.get("browser_channel") or "chrome").strip() or "chrome"
        worker_url = session.extension_service_worker_url or "sin service worker"
        self._set_slot_status(
            slot_id,
            f"{browser_channel.title()} abierto en {target_url}. Service worker: {worker_url}",
            color=SUCCESS,
        )

    @staticmethod
    def _open_browser_with_extension_session(
        *,
        keep_open: bool,
        extension_overlay: bool,
    ):
        return BrowserManager().open_extension_session(
            keep_open=keep_open,
            extension_overlay=extension_overlay,
        )

    def _schedule_process_progress(self, slot_id: str, phase: str, message: str) -> None:
        def apply_progress() -> None:
            if self._is_closing:
                return
            slot = self._get_slot(slot_id)
            lowered = message.lower()
            if "deepfakescore" in lowered:
                slot.panel.status_panel.set_persistent_alert("deepfakescore")
            retry_match = re.search(r"reintentos(?: de selfie)?:\s*(\d+)", lowered)
            if retry_match is not None:
                slot.panel.status_panel.set_retry_indicator(f"reintentos selfie: {retry_match.group(1)} [OK]")
            elif "marca de multiples selfies activada" in lowered or "selfie subida mas de una vez" in lowered:
                slot.panel.status_panel.set_retry_indicator("selfie reintentada [OK]")
            self._set_slot_status(slot_id, f"[{phase}] {message}")

        self._safe_after(0, apply_progress)

    def insert_test_log_from_admin(self) -> None:
        if self._admin_uploader_dialog is not None and self._admin_uploader_dialog.winfo_exists():
            self._admin_uploader_dialog.set_test_log_busy(True)
            self._admin_uploader_dialog.set_test_log_feedback("Insertando log de prueba en Supabase...")
        self._broadcast_status_message("Insertando log de prueba en Supabase...")
        thread = threading.Thread(target=self._insert_test_log_worker, daemon=True)
        thread.start()

    def _insert_test_log_worker(self) -> None:
        try:
            log_record = self._log_service.insert_test_log(
                agent_name=self._current_config.agent_name,
                device_name=self._get_local_device_name(),
            )
            self._safe_after(0, lambda: self._finish_test_log_insert(log_record.id))
        except Exception as exc:
            self._safe_after(0, lambda error=exc: self._handle_test_log_error(error))

    def _finish_test_log_insert(self, log_id: int) -> None:
        if self._admin_uploader_dialog is not None and self._admin_uploader_dialog.winfo_exists():
            self._admin_uploader_dialog.set_test_log_busy(False)
            self._admin_uploader_dialog.set_test_log_feedback(
                f"Log de prueba insertado correctamente. ID: {log_id}",
                color=SUCCESS,
            )
        self._broadcast_status_message(
            f"Log de prueba insertado correctamente en Supabase. ID: {log_id}",
            color=SUCCESS,
        )
        self.refresh_extension_status()

    def _handle_test_log_error(self, exc: Exception) -> None:
        if self._admin_uploader_dialog is not None and self._admin_uploader_dialog.winfo_exists():
            self._admin_uploader_dialog.set_test_log_busy(False)
            self._admin_uploader_dialog.set_test_log_feedback(
                f"Error al insertar log de prueba: {exc}",
                color=ERROR,
            )
        self._broadcast_status_message(f"Error al insertar log de prueba: {exc}", color=ERROR)

    def _set_extension_placeholder(self, slot_id: str, message: str) -> None:
        panel = self._get_slot(slot_id).panel.extension_status_panel
        panel.set_placeholder()
        panel.subline.configure(text=message)
        panel.message_label.configure(text=message)
        panel._detail_values["Motor"].configure(
            text="Extensión" if self._current_config.flow_engine == "extension" else "Tradicional"
        )

    def refresh_extension_status(self) -> None:
        if self._is_closing:
            return
        try:
            # TODO(parallelism): latest_* only reflects the most recent run and is not safe for true parallel execution.
            session = BrowserManager.get_latest_session()
            latest_debug = BrowserManager.get_latest_extension_debug() or {}
            session_debug = latest_debug
            if session is not None:
                session_debug = session.get_last_extension_debug() or {
                    "note": "browser_session_opened",
                    "extension_enabled": session.extension_enabled,
                    "extension_loaded": session.extension_loaded,
                    "extension_service_worker_url": session.extension_service_worker_url,
                    "extension_path": session.extension_path,
                    "extension_path_exists": bool(session.extension_path),
                    "manifest_path": f"{session.extension_path}\\manifest.json" if session.extension_path else None,
                    "manifest_exists": bool(session.extension_path),
                    "state": None,
                    "marker": None,
                    "overlayPresent": False,
                    "overlayFramePresent": False,
                }
                if latest_debug:
                    session_debug = {
                        **latest_debug,
                        **session_debug,
                        "browser_args": latest_debug.get("browser_args"),
                        "browser_channel": latest_debug.get("browser_channel"),
                        "browser_executable": latest_debug.get("browser_executable"),
                        "extension_dir": latest_debug.get("extension_dir"),
                        "extension_dir_is_absolute": latest_debug.get("extension_dir_is_absolute"),
                        "manifest_exists": latest_debug.get("manifest_exists"),
                        "manifest_path": latest_debug.get("manifest_path"),
                        "load_extension_arg_present": latest_debug.get("load_extension_arg_present"),
                        "disable_extensions_except_arg_present": latest_debug.get("disable_extensions_except_arg_present"),
                    }

            for slot_id, slot in self._slots.items():
                if slot_id == self._latest_debug_slot_id:
                    slot.panel.extension_status_panel.set_status(
                        session_active=session is not None,
                        extension_requested=self._current_config.flow_engine == "extension",
                        flow_engine=self._current_config.flow_engine,
                        session_debug=session_debug,
                    )
                else:
                    self._set_extension_placeholder(
                        slot_id,
                        "Diagnostico limitado: BrowserManager latest_* solo refleja la sesion mas reciente.",
                    )
            self._refresh_admin_diagnostics_if_open()
        except Exception as exc:
            for slot_id in self._slots:
                self._set_extension_placeholder(slot_id, "No se pudo actualizar el estado de extension.")
            self._broadcast_status_message(f"No se pudo actualizar el estado de extension: {exc}", color=ERROR)
        finally:
            self._safe_after(1000, self.refresh_extension_status)

    def _safe_after(self, delay_ms: int, callback, *, allow_during_close: bool = False) -> None:
        if self._is_closing and not allow_during_close:
            return
        try:
            self.after(delay_ms, callback)
        except Exception:
            return

    def _handle_app_close(self) -> None:
        if self._is_closing:
            return
        self._is_closing = True
        for slot_id, slot in self._slots.items():
            self._stop_process_timer(slot_id, prefix="Tiempo final")
            with contextlib.suppress(Exception):
                slot.panel.run_button.configure(state="disabled")
            with contextlib.suppress(Exception):
                slot.panel.clear_button.configure(state="disabled")
        with contextlib.suppress(Exception):
            self._broadcast_status_message("Cerrando Playwright y recursos activos...")
        threading.Thread(target=self._shutdown_and_destroy, daemon=True).start()

    def _shutdown_and_destroy(self) -> None:
        try:
            self._process_service.shutdown()
        except Exception:
            pass
        workers = [slot.thread for slot in self._slots.values() if slot.thread is not None]
        for worker in workers:
            if worker.is_alive():
                worker.join(timeout=5.0)
        self._safe_after(0, self._destroy_after_shutdown, allow_during_close=True)

    def _destroy_after_shutdown(self) -> None:
        with contextlib.suppress(Exception):
            if self._settings_dialog is not None and self._settings_dialog.winfo_exists():
                self._settings_dialog.destroy()
            if self._agent_name_dialog is not None and self._agent_name_dialog.winfo_exists():
                self._agent_name_dialog.destroy()
            if self._admin_password_dialog is not None and self._admin_password_dialog.winfo_exists():
                self._admin_password_dialog.destroy()
            if self._admin_uploader_dialog is not None and self._admin_uploader_dialog.winfo_exists():
                self._admin_uploader_dialog.destroy()
            self.destroy()

    def _build_process_request(self, slot_id: str, *, process_id: str) -> ProcessExecutionRequest:
        data = self._get_slot(slot_id).panel.form_panel.get_form_data()
        agent_name = validate_non_empty_string(self._current_config.agent_name, "agent_name")
        phone_number = sanitize_phone_number(data["phone_number"])
        validate_non_empty_string(data["password"], "password")
        return ProcessExecutionRequest(
            process_id=process_id,
            page_name=data["page_name"],
            action_name=data["action_name"],
            phone_number=phone_number,
            password=data["password"],
            agent_name=agent_name,
            execution_mode=self._current_config.flow_engine,
        )

    @staticmethod
    def _get_local_device_name() -> str:
        return os.getenv("COMPUTERNAME") or platform.node().strip() or "UNKNOWN_DEVICE"

    def _extract_local_config(self, data: dict[str, str] | None = None) -> LocalConfig:
        source = data or {}
        return LocalConfig(
            agent_name=validate_non_empty_string(source["agent_name"], "agent_name"),
            agent_name_confirmed=True,
            flow_engine="extension" if source.get("flow_engine", "Tradicional") == "Extension" else "traditional",
            keep_browser_open=source.get("keep_browser_open", "si") == "si",
            enable_browser_extension=True,
            browser_extension_overlay=source.get("browser_extension_overlay", "si") == "si",
            page_timeout_seconds=validate_positive_int(
                int(source["page_timeout_seconds"]),
                "page_timeout_seconds",
            ),
            action_timeout_seconds=validate_positive_int(
                int(source["action_timeout_seconds"]),
                "action_timeout_seconds",
            ),
            max_selfie_retries=self._parse_selfie_retry_limit(source["max_selfie_retries"]),
            last_result_filter=(
                "success_only"
                if source.get("last_result_filter", "general") == "solo exitoso"
                else source.get("last_result_filter", "general")
            ),
            theme_mode=source["theme_mode"],
        )

    @staticmethod
    def _parse_selfie_retry_limit(raw_value: str) -> int:
        normalized = validate_non_empty_string(raw_value, "max_selfie_retries").lower()
        if normalized in {"sin limite", "sin límite", "ilimitado", "unlimited"}:
            return 0
        value = int(normalized)
        if value < -1:
            raise ValueError("'max_selfie_retries' debe ser mayor o igual a -1.")
        if value == -1:
            return 0
        return value

    @staticmethod
    def _flow_engine_label(flow_engine: str) -> str:
        return "Extensión" if flow_engine == "extension" else "Tradicional"

    @staticmethod
    def _manual_browser_target_url(page_name: str) -> str:
        normalized = (page_name or "").strip().lower()
        if normalized == "paripe":
            return "https://paripe.io/login"
        if normalized == "ready4drive":
            return "https://ready4drive.com/login"
        return "https://compinche.io/login"
