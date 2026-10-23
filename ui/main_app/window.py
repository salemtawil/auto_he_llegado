from __future__ import annotations

import contextlib
import json
import logging
import os
import platform
import re
import shutil
import subprocess
import sys
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from time import monotonic
from tkinter import filedialog, messagebox
from uuid import uuid4

import customtkinter as ctk

from automation.browser_manager import BrowserManager
from config.paths import DEFAULT_LOCAL_DATA_DIR, PROJECT_ROOT
from config.settings import get_settings
from core.models import LocalConfig, ProcessExecutionRequest, ProcessExecutionResult
from core.validators import sanitize_phone_number, validate_non_empty_string, validate_positive_int
from services.last_result_service import LastResultService
from services.local_config_service import LocalConfigService
from services.machine_tuning_service import MachineTuningService
from services.log_service import LogService
from services.auth_context import get_current_session
from services.access_service import AccessService, AccessSnapshot
from services.background_video_status import get_video_status, set_video_status
from services.photo_pool_service import PhotoPoolService
from services.process_service import ProcessService
from services.video_contribution_service import VideoContributionProgress, VideoContributionService
from updater.release_update_client import ReleaseUpdateError, prepare_release_update
from updater.installed_revision import read_installed_revision
from ui.main_app.admin_dialogs import AdminPasswordDialog, AdminUploaderDialog
from ui.main_app.agent_name_dialog import AgentNameDialog
from ui.main_app.pool_badge import PoolBadge
from ui.main_app.process_slot_panel import ProcessSlotPanel
from ui.main_app.settings_dialog import SettingsDialog
from ui.admin_auth import is_admin_password_valid
from ui.shared.dialogs import confirm_destructive_action
from ui.shared.errors import safe_error_summary
from ui.theme import (
    SECONDARY_BUTTON,
    SECONDARY_BUTTON_HOVER,
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
    WARNING,
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


_LOGGER = logging.getLogger(__name__)

class MainAppWindow(ctk.CTk):
    def __init__(
        self,
        config_service: LocalConfigService | None = None,
        photo_pool_service: PhotoPoolService | None = None,
        process_service: ProcessService | None = None,
        log_service: LogService | None = None,
        last_result_service: LastResultService | None = None,
        access_service: AccessService | None = None,
    ) -> None:
        super().__init__()
        self._config_service = config_service or LocalConfigService()
        self._photo_pool_service = photo_pool_service or PhotoPoolService()
        self._process_service = process_service or ProcessService()
        self._access_service = access_service or AccessService()
        self._video_contribution_service = VideoContributionService()
        self._log_service = log_service or LogService()
        self._last_result_service = last_result_service or LastResultService()
        self._settings = get_settings()
        self._current_config = self._config_service.load()
        # El equipo manda: si cambio de maquina (o es la primera vez), los
        # limites se recalculan antes de armar la interfaz, porque de ellos
        # depende cuantos paneles pueden correr a la vez.
        try:
            self._machine_tuning = MachineTuningService(self._config_service)
            self._current_config = self._machine_tuning.ajustar(self._current_config).config
        except Exception:  # noqa: BLE001 - medir el equipo nunca impide abrir
            _LOGGER.exception("No se pudo ajustar la app al equipo.")
        self._settings_dialog: SettingsDialog | None = None
        self._agent_name_dialog: AgentNameDialog | None = None
        self._admin_password_dialog: AdminPasswordDialog | None = None
        self._admin_uploader_dialog: AdminUploaderDialog | None = None
        self._layout_mode = ""
        self._is_closing = False
        self._slots: dict[str, ProcessSlotRuntime] = {}
        self._process_to_slot: dict[str, str] = {}
        self._active_slot_id = self.SLOT_IDS[0]
        self._latest_debug_slot_id = self.SLOT_IDS[0]
        self._pending_admin_tab: str | None = None
        self._auth_session = get_current_session()
        self._access_snapshot: AccessSnapshot | None = None
        self._process_access_block_reason = "Validando acceso por video..."
        self._video_upload_running = False

        apply_theme_mode(self._current_config.theme_mode)
        self.title("Auto He Llegado")
        self.geometry("1280x760")
        # Minimo mas permisivo: el contenido ya no se recorta por debajo de el,
        # porque el area de procesos se desplaza cuando no cabe.
        self.minsize(820, 560)
        self.configure(fg_color=APP_BG)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        self._build_header()
        self._build_content()
        self._cleanup_owner_selfie_temp_files()
        self.bind("<Configure>", self._handle_window_resize)
        self.protocol("WM_DELETE_WINDOW", self._handle_app_close)
        self._safe_after(150, self.refresh_pool_count)
        self._safe_after(200, self.refresh_extension_status)
        self._safe_after(220, self._prompt_agent_name_if_needed)
        self._safe_after(500, self.refresh_background_video_status)
        self._safe_after(550, self.refresh_process_access_state)
        # La purga de local_data va la ultima y en segundo plano: es I/O de
        # disco sobre miles de archivos y no debe competir con el arranque.
        self._safe_after(3000, self._start_local_data_cleanup)
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
        # sticky="ew": la celda del titulo puede encogerse cuando la ventana estrecha,
        # en vez de empujar la insignia del pool fuera del borde derecho.
        self.title_wrap.grid(row=0, column=0, padx=(12, 12), pady=7, sticky="ew")
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
            text=f"Motor: Tradicional | {self._slot_process_count_label()}",
            font=ctk.CTkFont(size=10, weight="bold"),
            text_color=TEXT_MUTED,
            anchor="w",
            justify="left",
        )
        self.header_meta_label.grid(row=1, column=0, pady=(2, 0), sticky="ew")
        # Texto completo del resumen; lo que se pinta se acorta segun el ancho real.
        self._header_meta_parts: list[str] = []

        self.header_status_label = ctk.CTkLabel(
            self.title_wrap,
            text="",
            font=ctk.CTkFont(size=9, weight="bold"),
            text_color=TEXT_MUTED,
        )
        self.header_status_label.grid_forget()

        self.header_video_progress = ctk.CTkProgressBar(self.title_wrap, height=8, corner_radius=999)
        self._header_progress_indeterminate = False
        self.header_video_progress.grid(row=3, column=0, pady=(4, 0), sticky="ew")
        self.header_video_progress.set(0)
        self.header_video_progress.grid_remove()

        self.pool_badge = PoolBadge(self.header, refresh_callback=self.refresh_pool_count)
        self.pool_badge.grid(row=0, column=1, padx=(0, 16), pady=6, sticky="nsew")

        self.header_actions = ctk.CTkFrame(self.header, fg_color="transparent")
        self.header_actions.grid(row=0, column=2, padx=(0, 12), pady=6, sticky="nsew")
        self.header_actions.grid_rowconfigure(0, weight=1)
        for column in range(8):
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

        self.video_button = self._create_header_tile(
            self.header_actions,
            icon="↑",
            text="Subir video",
            command=self.open_video_uploader,
        )
        self.video_button.grid(row=0, column=4, padx=(0, 6), sticky="nsew")

        self.close_browsers_button = self._create_header_tile(
            self.header_actions,
            icon="⏻",
            text="Navegadores",
            command=self.close_all_browsers,
        )
        self.close_browsers_button.grid(row=0, column=5, padx=(0, 6), sticky="nsew")

        self.theme_toggle_button = self._create_header_tile(
            self.header_actions,
            icon="",
            text="Claro",
            command=self.toggle_theme_mode,
        )
        self.theme_toggle_button.grid(row=0, column=6, padx=(0, 6), sticky="nsew")

        self.settings_button = self._create_header_tile(
            self.header_actions,
            icon="⚙",
            text="Configuracion",
            command=self.open_settings_dialog,
            highlighted=True,
        )
        self.settings_button.grid(row=0, column=7, sticky="nsew")
        self._layout_header_actions()
        self._sync_theme_toggle_button()
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
        tile._icon_label = icon_label
        tile._text_label = text_label

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

    @staticmethod
    def _set_header_tile_text(tile, text: str) -> None:
        text_label = getattr(tile, "_text_label", None)
        if text_label is not None:
            text_label.configure(text=text)

    @staticmethod
    def _set_header_tile_icon(tile, icon: str) -> None:
        icon_label = getattr(tile, "_icon_label", None)
        if icon_label is not None:
            icon_label.configure(text=icon)

    @staticmethod
    def _get_theme_toggle_visuals(theme_mode: str) -> tuple[str, str]:
        if theme_mode == "dark":
            return ("◐", "Oscuro")
        return ("☼", "Claro")

    def _layout_header_actions(self) -> None:
        visible_actions = [
            self.refresh_button,
            self.video_button,
            self.close_browsers_button,
            self.theme_toggle_button,
            self.settings_button,
        ]
        if self._current_user_is_admin():
            visible_actions = [
                self.refresh_button,
                self.admin_button,
                self.uploader_button,
                self.cleanup_button,
                self.video_button,
                self.close_browsers_button,
                self.theme_toggle_button,
                self.settings_button,
            ]

        all_actions = [
            self.refresh_button,
            self.admin_button,
            self.uploader_button,
            self.cleanup_button,
            self.video_button,
            self.close_browsers_button,
            self.theme_toggle_button,
            self.settings_button,
        ]
        for tile in all_actions:
            tile.grid_forget()

        for index, tile in enumerate(visible_actions):
            tile.grid(row=0, column=index, padx=(0, 0 if index == len(visible_actions) - 1 else 6), sticky="nsew")

    def _current_user_is_admin(self) -> bool:
        session = getattr(self, "_auth_session", None) or get_current_session()
        return bool(session and session.is_admin)

    def _build_content(self) -> None:
        self.content = ctk.CTkFrame(self, fg_color="transparent")
        self.content.grid(row=1, column=0, padx=10, pady=(0, 10), sticky="nsew")
        self.content.grid_columnconfigure(0, weight=1)
        self.content.grid_rowconfigure(0, weight=1)

        # Los dos procesos viven dentro de un contenedor desplazable: cuando la
        # ventana no da para las dos tarjetas completas, se desplaza en vez de
        # recortarlas. La barra solo aparece cuando hace falta (_sync_slots_scrollbar).
        self.slots_scroll = ctk.CTkScrollableFrame(
            self.content,
            fg_color="transparent",
            corner_radius=0,
            scrollbar_button_color=SECONDARY_BUTTON,
            scrollbar_button_hover_color=SECONDARY_BUTTON_HOVER,
        )
        self.slots_scroll.grid(row=0, column=0, sticky="nsew")
        self.slots_scroll.grid_columnconfigure(0, weight=1)

        self.main_column = self.slots_scroll
        self.main_column.grid_columnconfigure(0, weight=1)

        # Cuatro paneles, en una rejilla de 2x2. Antes eran dos construcciones
        # escritas a mano y treinta y dos referencias literales a "slot_1" y
        # "slot_2" repartidas por el archivo: anadir uno era tocar todo eso.
        self._slots = {}
        for slot_id in self.SLOT_IDS:
            panel = ProcessSlotPanel(
                self.main_column,
                title=self.slot_title(slot_id),
                on_start=lambda sid=slot_id: self._handle_run_button(sid),
                on_clear=lambda sid=slot_id: self.clear_form(sid),
                on_export_state=lambda sid=slot_id: self.export_extension_state(sid),
                on_open_diagnostics=self._open_diagnostics_panel,
                on_open_extensions=lambda sid=slot_id: self.open_extension_test_browser(sid),
                on_open_browser=lambda sid=slot_id: self.open_manual_browser(sid),
                on_owner_selfie_toggle=lambda enabled, sid=slot_id: self._handle_owner_selfie_toggle(sid, enabled),
                on_owner_selfie_select=lambda sid=slot_id: self._handle_owner_selfie_select(sid),
                on_owner_selfie_remove=lambda sid=slot_id: self._handle_owner_selfie_remove(sid),
            )
            self._slots[slot_id] = ProcessSlotRuntime(slot_id=slot_id, panel=panel)

        self._sync_primary_slot_refs()

    def open_video_uploader(self) -> None:
        if self._video_upload_running:
            messagebox.showinfo(
                "Subir video",
                "Ya hay un video procesandose en segundo plano.",
                parent=self,
            )
            return
        session = self._auth_session or get_current_session()
        if session is None:
            messagebox.showerror("Subir video", "No hay una sesion activa.", parent=self)
            return
        selected = filedialog.askopenfilename(
            title="Seleccionar video",
            filetypes=[
                ("Videos", "*.mp4 *.mov *.m4v *.avi *.mkv"),
                ("Todos", "*.*"),
            ],
            parent=self,
        )
        if not selected:
            return
        video_path = Path(selected)
        self._video_upload_running = True
        set_video_status(
            phase="queued",
            message=f"Video recibido: {video_path.name}. Preparando envio...",
            is_running=True,
        )
        self._broadcast_status_message(
            "Video recibido. La carga a Drive continua en segundo plano.",
            color=SUCCESS,
        )
        thread = threading.Thread(
            target=lambda: self._submit_optional_video_background_worker(video_path, session),
            daemon=True,
        )
        thread.start()

    def _submit_optional_video_background_worker(self, video_path: Path, session) -> None:
        try:
            result = self._video_contribution_service.submit_video(
                video_path,
                session=session,
                progress_callback=self._apply_optional_video_progress,
            )
            photo_count = result.candidates_uploaded
            message = (
                f"Video procesado. {photo_count} fotos candidatas listas para revision."
                if photo_count > 0
                else "Video enviado a Drive. Admin notificado por Telegram."
            )
            set_video_status(
                phase="done",
                message=message,
                current=photo_count,
                total=max(photo_count, 1),
                is_complete=True,
            )
            self._safe_after(
                0,
                lambda: (
                    self._broadcast_status_message(message, color=SUCCESS),
                    self.refresh_process_access_state(),
                ),
            )
        except Exception as exc:
            error_message = f"No se pudo enviar el video. Revisa tu conexión y vuelve a intentar. ({safe_error_summary(exc, context='envio de video')})"
            set_video_status(
                phase="error",
                message=error_message,
                is_error=True,
            )
            self._safe_after(
                0,
                lambda message=error_message: (
                    self._broadcast_status_message(message, color=ERROR),
                    self.refresh_process_access_state(),
                ),
            )
        finally:
            self._video_upload_running = False

    def _apply_optional_video_progress(self, progress: VideoContributionProgress) -> None:
        set_video_status(
            phase=progress.phase,
            message=progress.message,
            current=progress.current,
            total=progress.total,
            is_running=True,
        )
        if progress.phase == "received":
            session = self._auth_session or get_current_session()
            if session is not None and not session.is_admin:
                self._safe_after(
                    0,
                    lambda current_session=session, reason=progress.message: self._grant_temporary_video_access(
                        current_session,
                        reason=reason,
                    ),
                )

    def _grant_temporary_video_access(self, session, *, reason: str) -> None:
        if self._is_closing or session.is_admin:
            return
        self._access_snapshot = AccessSnapshot(
            can_use_app=True,
            needs_weekly_video=False,
            reason=reason,
            week_start=AccessService.current_week_start(),
            profile={
                "id": session.user_id,
                "role": session.role,
                "approved": session.approved,
                "disabled": session.disabled,
            },
            latest_batch={"status": "processing"},
        )
        self._process_access_block_reason = ""
        self._sync_run_button_state()
        self._broadcast_status_message(reason, color=SUCCESS)

    def open_settings_dialog(self) -> None:
        if self._settings_dialog is not None and self._settings_dialog.winfo_exists():
            self._settings_dialog.focus()
            return
        self._settings_dialog = SettingsDialog(
            self,
            config=self._current_config,
            on_save=self.save_local_config,
            on_launch_updater=self.request_external_update,
        )
        self._settings_dialog.focus()

    def request_external_update(self) -> None:
        error_message = self._validate_updater_ready()
        if error_message:
            messagebox.showerror("Actualizar app", error_message, parent=self)
            return
        with contextlib.suppress(Exception):
            self._broadcast_status_message("Preparando actualizacion en segundo plano...", color=SUCCESS)
        threading.Thread(target=self._request_external_update_worker, daemon=True).start()

    def _request_external_update_worker(self) -> None:
        try:
            downloaded_update = self._download_update_package_from_github()
        except ReleaseUpdateError as exc:
            self._safe_after(0, lambda error=exc: messagebox.showerror("Actualizar app", str(error), parent=self))
            return
        if downloaded_update is None:
            self._safe_after(
                0,
                lambda: messagebox.showinfo(
                    "Actualizar app",
                    "Ya tienes la ultima version instalada.",
                    parent=self,
                ),
            )
            return
        self._safe_after(0, lambda current=downloaded_update: self._finish_external_update_request(current))

    def _finish_external_update_request(self, downloaded_update) -> None:
        if self._is_closing:
            return
        if not self._launch_integrated_updater(
            downloaded_update.path,
            revision=downloaded_update.asset.revision,
        ):
            return

        with contextlib.suppress(Exception):
            self._broadcast_status_message(
                f"Actualizando a {downloaded_update.asset.revision}, la app se reiniciara.",
                color=SUCCESS,
            )
        self._handle_app_close(confirm=False)

    def _validate_updater_ready(self) -> str | None:
        if self._active_process_count() > 0:
            return "Hay procesos activos. Espera a que terminen o cancelalos antes de actualizar."

        helper_source = self._resolve_update_helper_source()
        updater_config = self._resolve_updater_config_path()
        update_config = self._resolve_release_update_config_path()

        if helper_source is None:
            return "No se encontro el helper de actualizacion."
        if not updater_config.is_file():
            return "No se encontro updater/updater_config.json. Configura el updater antes de actualizar."
        if not self._is_updater_config_valid(updater_config):
            return "El updater_config.json no esta configurado con owner/repo reales."
        if not update_config.is_file():
            return "No se encontro updater/update_config.json. Configura la URL de actualizacion de GitHub."
        return None

    @staticmethod
    def _is_updater_config_valid(config_path: Path) -> bool:
        try:
            raw_config = json.loads(config_path.read_text(encoding="utf-8-sig"))
        except Exception:
            return False
        if not isinstance(raw_config, dict):
            return False

        owner = raw_config.get("owner")
        repo = raw_config.get("repo")
        branch = raw_config.get("branch")
        invalid_values = {"", None, "TU_USUARIO", "TU_REPO"}

        if owner in invalid_values or repo in invalid_values:
            return False
        if not isinstance(branch, str) or not branch.strip():
            return False
        return True

    @staticmethod
    def _resolve_updater_config_path() -> Path:
        root_updater_dir = PROJECT_ROOT / "updater"
        if (root_updater_dir / "updater_config.json").is_file():
            return root_updater_dir / "updater_config.json"
        internal_updater_dir = PROJECT_ROOT / "_internal" / "updater"
        return internal_updater_dir / "updater_config.json"

    @staticmethod
    def _resolve_update_package_dir() -> Path:
        return PROJECT_ROOT / "updates" / "staging" / "latest_build"

    @staticmethod
    def _resolve_release_update_config_path() -> Path:
        root_update_config = PROJECT_ROOT / "updater" / "update_config.json"
        if root_update_config.is_file():
            return root_update_config
        internal_update_config = PROJECT_ROOT / "_internal" / "updater" / "update_config.json"
        return internal_update_config

    @staticmethod
    def _resolve_downloaded_update_dir() -> Path:
        return PROJECT_ROOT / "updates" / "staging" / "downloaded"

    @staticmethod
    def _resolve_update_helper_source() -> Path | None:
        root_helper_exe = PROJECT_ROOT / "AutoHeLlegadoUpdateHelper.exe"
        if root_helper_exe.is_file():
            return root_helper_exe

        root_helper_script = PROJECT_ROOT / "updater" / "apply_update_helper.py"
        if root_helper_script.is_file():
            return root_helper_script

        internal_helper_script = PROJECT_ROOT / "_internal" / "updater" / "apply_update_helper.py"
        if internal_helper_script.is_file():
            return internal_helper_script

        return None

    @staticmethod
    def _resolve_app_executable_path() -> Path:
        if sys.platform == "darwin":
            executable_path = Path(sys.executable).resolve()
            for parent in (executable_path, *executable_path.parents):
                if parent.suffix.lower() == ".app" and parent.is_dir():
                    return parent
            portable_app = PROJECT_ROOT / "AutoHeLlegado.app"
            if portable_app.is_dir():
                return portable_app

        portable_exe = PROJECT_ROOT / "AutoHeLlegado.exe"
        if portable_exe.is_file():
            return portable_exe
        return PROJECT_ROOT / "app_main.py"

    @staticmethod
    def _prepare_helper_runtime_copy(helper_source: Path) -> Path:
        if helper_source.suffix.lower() == ".exe":
            return helper_source

        runtime_dir = PROJECT_ROOT / "updates" / "runtime_helper"
        runtime_dir.mkdir(parents=True, exist_ok=True)
        runtime_copy = runtime_dir / helper_source.name
        shutil.copy2(helper_source, runtime_copy)
        return runtime_copy

    @staticmethod
    def _resolve_helper_python_command() -> str:
        if not getattr(sys, "frozen", False):
            return sys.executable
        if sys.platform == "darwin":
            return "python3"
        return "python"

    def _download_update_package_from_github(self):
        with contextlib.suppress(Exception):
            self._broadcast_status_message("Buscando actualizacion en GitHub...", color=SUCCESS)
        downloaded_update = prepare_release_update(
            config_path=self._resolve_release_update_config_path(),
            staging_dir=self._resolve_downloaded_update_dir(),
            current_revision=read_installed_revision(PROJECT_ROOT),
        )
        if downloaded_update is None:
            # Ya se esta en la ultima revision: ni descarga ni reinicio.
            return None
        with contextlib.suppress(Exception):
            self._broadcast_status_message(
                f"Actualizacion descargada: {downloaded_update.asset.revision}. Preparando reinicio...",
                color=SUCCESS,
            )
        return downloaded_update

    def _launch_integrated_updater(
        self,
        package_zip: Path | None = None,
        *,
        revision: str | None = None,
    ) -> bool:
        helper_source = self._resolve_update_helper_source()
        if helper_source is None:
            messagebox.showerror("Actualizar app", "No se encontro el helper de actualizacion.", parent=self)
            return False

        helper_runtime = self._prepare_helper_runtime_copy(helper_source)
        package_zip = package_zip or (self._resolve_update_package_dir() / "update.zip")
        app_exe = self._resolve_app_executable_path()
        log_dir = PROJECT_ROOT / "updates" / "update_logs"

        command = [
            str(helper_runtime),
            "--install-dir",
            str(PROJECT_ROOT),
            "--package-zip",
            str(package_zip),
            "--app-exe",
            str(app_exe),
            "--wait-pid",
            str(os.getpid()),
            "--restart",
            "--log-dir",
            str(log_dir),
        ]
        if revision:
            # El helper la escribe SOLO si la actualizacion se aplica de verdad.
            command.extend(["--revision", str(revision)])
        if helper_runtime.suffix.lower() != ".exe":
            command.insert(0, self._resolve_helper_python_command())

        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        popen_kwargs: dict[str, object] = {"cwd": str(PROJECT_ROOT)}
        if creationflags:
            popen_kwargs["creationflags"] = creationflags

        try:
            subprocess.Popen(command, **popen_kwargs)
        except Exception as exc:
            messagebox.showerror(
                "Actualizar app",
                f"No se pudo iniciar el helper de actualización. Cierra la app y vuelve a intentarlo. ({safe_error_summary(exc, context='helper de actualizacion')})",
                parent=self,
            )
            return False
        return True

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
        self._open_admin_tool("Diagnostico")

    def _validate_admin_access(self, password: str) -> None:
        if not self._settings.admin_access_password:
            message = (
                "El panel Admin esta bloqueado: falta definir ADMIN_ACCESS_PASSWORD "
                "en el archivo .env de esta instalacion."
            )
            if self._admin_password_dialog is not None and self._admin_password_dialog.winfo_exists():
                self._admin_password_dialog.set_error(message)
            self._broadcast_status_message(message, color=ERROR)
            return
        if not is_admin_password_valid(password, self._settings):
            if self._admin_password_dialog is not None and self._admin_password_dialog.winfo_exists():
                self._admin_password_dialog.set_error("Contrasena incorrecta. Acceso Admin denegado.")
            self._broadcast_status_message("Acceso Admin denegado por contrasena incorrecta.", color=ERROR)
            return
        current_session = get_current_session()
        if current_session is None or not current_session.is_admin:
            if self._admin_password_dialog is not None and self._admin_password_dialog.winfo_exists():
                self._admin_password_dialog.set_error("Tu usuario no tiene rol admin.")
            self._broadcast_status_message("Acceso Admin denegado por rol de usuario.", color=ERROR)
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
            self._broadcast_status_message(f"No se pudo guardar la configuración local. Revisa los permisos de la carpeta de datos y vuelve a intentar. ({safe_error_summary(exc, context='guardar configuracion local')})", color=ERROR)

    def close_all_browsers(self) -> None:
        """Libera ahora todos los navegadores abiertos por la app.

        Playwright es el dueno del proceso del navegador y lo mantiene vivo
        aunque el agente cierre la ventana, asi que sin esto los navegadores
        que se dejan abiertos para ver el resultado no liberan la RAM hasta
        cerrar la app.

        Si hay una automatizacion trabajando se pide confirmacion: cerrarle el
        navegador la interrumpe.
        """

        activos = self._active_process_count()
        if activos > 0 and not messagebox.askyesno(
            "Cerrar navegadores",
            f"Hay {activos} proceso(s) en ejecucion.\n\n"
            "Al cerrar los navegadores se interrumpiran.\n\n"
            "Cerrar de todas formas?",
            parent=self,
            default=messagebox.NO,
        ):
            return
        try:
            liberados = BrowserManager.close_all_browsers()
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror(
                "Cerrar navegadores",
                f"No se pudieron cerrar los navegadores. ({safe_error_summary(exc, context='cierre de navegadores')})",
                parent=self,
            )
            return
        if liberados:
            mensaje = f"Se cerraron {liberados} navegador(es) y sus procesos."
        else:
            mensaje = "No habia navegadores abiertos por la app."
        self._broadcast_status_message(mensaje, color=SUCCESS)

    def toggle_theme_mode(self) -> None:
        next_mode = "dark" if self._current_config.theme_mode == "light" else "light"
        try:
            self._persist_theme_mode_only(next_mode)
        except Exception as exc:
            self._broadcast_status_message(f"No se pudo cambiar el tema. ({safe_error_summary(exc, context='tema')})", color=ERROR)

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

    def _persist_theme_mode_only(self, theme_mode: str) -> None:
        normalized = apply_theme_mode(theme_mode)
        previous_theme_mode = self._current_config.theme_mode
        updated_config = self._current_config.model_copy(update={"theme_mode": normalized})
        self._current_config = updated_config
        self._sync_theme_toggle_button()
        if previous_theme_mode != normalized:
            self._refresh_theme_widgets()
        self._current_config = self._config_service.save(updated_config)
        self._sync_theme_toggle_button()

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
        button = getattr(self, "theme_toggle_button", None)
        if button is not None:
            icon, label = self._get_theme_toggle_visuals(self._current_config.theme_mode)
            self._set_header_tile_icon(button, icon)
            self._set_header_tile_text(button, label)
        if self._settings_dialog is not None and self._settings_dialog.winfo_exists():
            with contextlib.suppress(Exception):
                self._settings_dialog.theme_menu.set(self._current_config.theme_mode)
            with contextlib.suppress(Exception):
                self._settings_dialog._sync_save_button_state()

    def _handle_window_resize(self, event) -> None:
        if event.widget is not self:
            return
        self._apply_responsive_layout(event.width)
        self._apply_header_width(event.width)
        self._apply_slot_widths()
        self._sync_slots_scrollbar()

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
        # Con mas de dos tarjetas van en rejilla y cada una ocupa media
        # ventana: ahi tienen que ir apretadas o no caben las dos filas.
        apretadas = len(self.SLOT_IDS) > 2
        for slot in self._slots.values():
            slot.panel.grid_forget()
            slot.panel.set_secondary_visual(False)
            slot.panel.set_compact_layout(apretadas)

        self._sync_primary_slot_refs()

        # Rejilla de SLOT_COLUMNS columnas. Con 4 paneles y 2 columnas quedan
        # 2x2: simetrico y sin barra de desplazamiento, que es lo que se pidio.
        #
        # sticky="ew" y filas sin weight: cada tarjeta ocupa su altura natural.
        # Antes se repartia el alto a partes iguales ("uniform") y en una
        # ventana baja ninguna recibia lo que su contenido necesita, con lo que
        # la fila de botones quedaba cortada.
        columnas = max(1, self.SLOT_COLUMNS)
        for columna in range(columnas):
            # uniform: las columnas miden lo mismo, si no la primera tarjeta se
            # queda con todo el ancho y la de al lado sale espachurrada.
            self.main_column.grid_columnconfigure(
                columna, weight=1, uniform="slots"
            )
        total_filas = (len(self.SLOT_IDS) + columnas - 1) // columnas
        for fila in range(total_filas):
            self.main_column.grid_rowconfigure(fila, weight=0)

        for indice, slot_id in enumerate(self.SLOT_IDS):
            fila, columna = divmod(indice, columnas)
            ultima_fila = fila == total_filas - 1
            self._slots[slot_id].panel.grid(
                row=fila,
                column=columna,
                padx=(0, 10) if columna < columnas - 1 else 0,
                pady=(0, 4) if ultima_fila else (0, 10),
                sticky="ew",
            )

        self._refresh_header_summary()
        self._safe_after(0, self._apply_slot_widths)
        self._safe_after(0, self._sync_slots_scrollbar)

    # Anchos por debajo de los cuales el resumen de cabecera se recorta por partes.
    _HEADER_PART_BREAKPOINTS = (1180, 1000, 860)

    # Los paneles de proceso. Para anadir o quitar uno basta con tocar esto:
    # la construccion, la rejilla, el tope de procesos y los diagnosticos
    # salen todos de aqui.
    SLOT_IDS = ("slot_1", "slot_2", "slot_3", "slot_4")
    # Columnas de la rejilla. Con 2 columnas y 4 paneles quedan 2x2, que es
    # simetrico y cabe sin barra de desplazamiento.
    SLOT_COLUMNS = 2

    @classmethod
    def slot_title(cls, slot_id: str) -> str:
        """"slot_3" -> "Proceso 3". Un solo sitio donde se decide el nombre."""

        try:
            return f"Proceso {cls.SLOT_IDS.index(slot_id) + 1}"
        except ValueError:
            return str(slot_id)

    @classmethod
    def slot_id_por_titulo(cls, titulo: str) -> str:
        """El camino de vuelta, para los diagnosticos que vienen por nombre."""

        for slot_id in cls.SLOT_IDS:
            if cls.slot_title(slot_id) == titulo:
                return slot_id
        return cls.SLOT_IDS[0]

    @staticmethod
    def build_header_summary(parts: list[str], width: int) -> str:
        """Resumen de cabecera adaptado al ancho disponible.

        Devuelve una sola linea legible: va soltando las partes menos importantes
        a medida que la ventana estrecha, en vez de dejar que el texto se salga de
        su celda y se corte por los dos lados.
        """

        if not parts:
            return ""
        keep = len(parts)
        for index, breakpoint_width in enumerate(MainAppWindow._HEADER_PART_BREAKPOINTS):
            if width and width < breakpoint_width:
                keep = len(parts) - index - 1
        # Nunca por debajo de motor + procesos activos: es el minimo util.
        keep = max(keep, 2)
        return " | ".join(parts[:keep])

    def _apply_header_width(self, width: int) -> None:
        """Ajusta el resumen y el ajuste de linea de la cabecera al ancho actual."""

        label = getattr(self, "header_meta_label", None)
        if label is None:
            return
        parts = getattr(self, "_header_meta_parts", None) or []
        with contextlib.suppress(Exception):
            if parts:
                label.configure(text=self.build_header_summary(parts, width))
            # wraplength deja que el texto envuelva dentro de la cabecera en vez de
            # desbordarla; se reserva el sitio de la insignia del pool y los margenes.
            available = max(int(width) - 320, 220) if width else 220
            label.configure(wraplength=available)
            status_label = getattr(self, "header_status_label", None)
            if status_label is not None:
                status_label.configure(wraplength=available, anchor="w", justify="left")

    def _apply_slot_widths(self) -> None:
        """Propaga el ancho real a cada tarjeta de proceso."""

        for slot in self._slots.values():
            panel = getattr(slot, "panel", None)
            apply_width = getattr(panel, "apply_width_layout", None)
            if callable(apply_width):
                with contextlib.suppress(Exception):
                    apply_width(panel.winfo_width())

    def _sync_slots_scrollbar(self) -> None:
        """Muestra la barra de desplazamiento solo si el contenido no cabe.

        Mantiene el aspecto compacto: en una ventana normal no se ve ninguna barra,
        y en cuanto el contenido excede el alto disponible aparece, de modo que los
        botones nunca quedan inalcanzables.
        """

        scroll = getattr(self, "slots_scroll", None)
        if scroll is None:
            return
        try:
            scroll.update_idletasks()
            needed = self.main_column.winfo_reqheight()
            available = scroll.winfo_height()
            scrollbar = scroll._scrollbar  # noqa: SLF001 - CTkScrollableFrame no lo expone
            if needed > available + 2:
                scrollbar.grid()
            else:
                scrollbar.grid_remove()
        except Exception:  # noqa: BLE001 - nunca romper el redibujado por esto
            return

    def _sync_primary_slot_refs(self) -> None:
        primary_panel = (
            self._slots[self._active_slot_id].panel
            if self._active_slot_id in self._slots
            else self._slots[self.SLOT_IDS[0]].panel
        )
        self.form_panel = primary_panel.form_panel
        self.status_panel = primary_panel.status_panel
        self.current_result_panel = primary_panel.current_result_panel
        self.run_button = primary_panel.run_button
        self.clear_button = primary_panel.clear_button

    def _apply_pending_admin_tab(self) -> None:
        if self._pending_admin_tab is None:
            return
        if self._admin_uploader_dialog is None or not self._admin_uploader_dialog.winfo_exists():
            return
        with contextlib.suppress(Exception):
            self._admin_uploader_dialog.tabs.set(self._pending_admin_tab)
        with contextlib.suppress(Exception):
            self._admin_uploader_dialog._handle_tab_selected()
        self._pending_admin_tab = None

    def _refresh_header_summary(self) -> None:
        if not hasattr(self, "header_meta_label") or not self._slots:
            return
        primary_slot_id = self._active_slot_id if self._active_slot_id in self._slots else self.SLOT_IDS[0]
        primary_slot = self._get_slot(primary_slot_id)
        page_name = primary_slot.panel.form_panel.page_menu.get() or "N/A"
        slot_title = self.slot_title(primary_slot_id)
        engine_label = self._flow_engine_label(self._current_config.flow_engine)
        self._header_meta_parts = [
            f"Motor: {engine_label}",
            f"Activos: {self._active_process_count()}/{self._max_concurrent_processes()}",
            f"Principal: {slot_title}",
            f"Página: {page_name}",
        ]
        self._apply_header_width(self.winfo_width())

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

    def _set_header_progress_determinate(self, fraction: float) -> None:
        if self._header_progress_indeterminate:
            with contextlib.suppress(Exception):
                self.header_video_progress.stop()
            with contextlib.suppress(Exception):
                self.header_video_progress.configure(mode="determinate")
            self._header_progress_indeterminate = False
        self.header_video_progress.set(fraction)

    def _set_header_progress_indeterminate(self) -> None:
        if self._header_progress_indeterminate:
            return
        try:
            self.header_video_progress.configure(mode="indeterminate")
            self.header_video_progress.start()
        except Exception:  # noqa: BLE001 - keep the bar usable if CTk refuses
            return
        self._header_progress_indeterminate = True

    def _active_process_count(self) -> int:
        return sum(1 for slot in self._slots.values() if slot.thread is not None)

    def _max_concurrent_processes(self) -> int:
        try:
            tope = int(self._current_config.max_concurrent_processes)
        except (TypeError, ValueError):
            return 1
        return max(1, min(len(self.SLOT_IDS), tope))

    def _slot_process_count_label(self) -> str:
        return (
            f"Procesos activos: {self._active_process_count()}"
            f"/{self._max_concurrent_processes()}"
        )

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

    def refresh_background_video_status(self) -> None:
        if self._is_closing:
            return
        status = get_video_status()
        try:
            if status.phase == "idle":
                self.header_status_label.grid_forget()
                self._set_header_progress_determinate(0.0)
                self.header_video_progress.grid_remove()
            else:
                color = ERROR if status.is_error else (SUCCESS if status.is_complete else TEXT_MUTED)
                self.header_status_label.configure(text=status.message, text_color=color)
                self.header_status_label.grid(row=2, column=0, pady=(2, 0), sticky="w")
                self.header_video_progress.grid(row=3, column=0, pady=(4, 0), sticky="ew")
                if status.total > 0:
                    self._set_header_progress_determinate(status.fraction)
                elif status.is_running:
                    # Total unknown: an indeterminate bar, not a fake 8%.
                    self._set_header_progress_indeterminate()
                elif status.is_complete:
                    self._set_header_progress_determinate(1.0)
                else:
                    self._set_header_progress_determinate(0.0)
        except Exception:
            pass
        finally:
            self._safe_after(1000, self.refresh_background_video_status)

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
            error_message = f"No se pudo consultar el pool de fotos. Revisa tu conexión y pulsa Refrescar. ({safe_error_summary(exc, context='contador del pool')})"
            self._safe_after(0, lambda message=error_message: self._broadcast_status_message(message, color=ERROR))

    def _apply_pool_snapshot(self, snapshot) -> None:
        self.pool_badge.set_snapshot(snapshot)
        self._refresh_header_summary()

    def refresh_process_access_state(self) -> None:
        if self._is_closing:
            return
        session = self._auth_session or get_current_session()
        if session is None or session.is_admin:
            self._access_snapshot = None
            self._process_access_block_reason = ""
            self._sync_run_button_state()
            return
        self._process_access_block_reason = "Validando acceso por video..."
        self._sync_run_button_state()
        threading.Thread(target=lambda: self._refresh_process_access_worker(session), daemon=True).start()

    def _refresh_process_access_worker(self, session) -> None:
        try:
            snapshot = self._access_service.get_access_snapshot(session)
            self._safe_after(0, lambda current=snapshot: self._apply_process_access_snapshot(current))
        except Exception as exc:
            self._safe_after(0, lambda error=exc: self._apply_process_access_error(error))

    def _apply_process_access_snapshot(self, snapshot: AccessSnapshot) -> None:
        self._access_snapshot = snapshot
        self._process_access_block_reason = "" if snapshot.can_use_app else snapshot.reason
        self._sync_run_button_state()
        if not snapshot.can_use_app:
            self._broadcast_status_message(snapshot.reason, color=WARNING)

    def _apply_process_access_error(self, exc: Exception) -> None:
        self._access_snapshot = None
        self._process_access_block_reason = f"No se pudo validar el acceso por video. Revisa tu conexión y vuelve a intentar. ({safe_error_summary(exc, context='acceso por video')})"
        self._sync_run_button_state()
        self._broadcast_status_message(self._process_access_block_reason, color=ERROR)

    def _process_access_allows_start(self) -> bool:
        session = self._auth_session or get_current_session()
        if session is None:
            self._process_access_block_reason = "No hay una sesion activa."
            return False
        if session.is_admin:
            return True
        if self._access_snapshot is None:
            self._process_access_block_reason = "Validando acceso por video..."
            self.refresh_process_access_state()
            return False
        snapshot = self._access_snapshot
        self._access_snapshot = snapshot
        self._process_access_block_reason = "" if snapshot.can_use_app else snapshot.reason
        return snapshot.can_use_app

    def start_process(self, slot_id: str) -> None:
        if self._is_closing:
            return
        slot = self._get_slot(slot_id)
        active_count = self._active_process_count()
        current_flow_engine = (self._current_config.flow_engine or "").strip().lower()
        if not self._process_access_allows_start():
            self._set_slot_status(slot_id, self._process_access_block_reason, color=WARNING)
            self._sync_run_button_state()
            return
        if slot.thread is not None:
            self._set_slot_status(slot_id, "Este panel ya tiene un proceso en ejecución. Espera a que termine antes de iniciar otro.", color=ERROR)
            return
        tope = self._max_concurrent_processes()
        if active_count >= tope:
            self._set_slot_status(
                slot_id,
                f"Ya hay {tope} proceso(s) activo(s) para este equipo."
                " Espera a que termine uno para iniciar otro.",
                color=ERROR,
            )
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
            error_message = str(exc)
            if error_message == "Selecciona una foto valida del titular o desactiva la opcion.":
                self._set_slot_status(slot_id, error_message, color=ERROR)
            else:
                self._set_slot_status(slot_id, "Revisa el formulario antes de iniciar: el teléfono debe tener 10 dígitos y la contraseña no puede estar vacía.", color=ERROR)
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
            # Daemon as a last resort only: _shutdown_and_destroy first cancels the
            # run and waits SHUTDOWN_GRACE_SECONDS for its own finally block to
            # release the photo, delete temp files, persist the result and close
            # Playwright. Daemon just guarantees the frozen build can still exit if
            # a worker never answers -- and in that case the UI says so.
            daemon=True,
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
        # Entrada y salida explicitas en el log: sin esto no habia forma de
        # distinguir "el proceso sigue trabajando" de "el proceso termino y el
        # aviso a la interfaz se perdio". Las dos cosas se ven igual en
        # pantalla, y la segunda deja la app esperando para siempre.
        _LOGGER.info("Worker iniciado (slot=%s, proceso=%s).", slot_id, process_id)
        try:
            result = self._process_service.execute(
                request,
                progress_callback=lambda phase, message, current_slot_id=slot_id: self._schedule_process_progress(
                    current_slot_id,
                    phase,
                    message,
                ),
            )
            _LOGGER.info(
                "Worker terminado (slot=%s, proceso=%s, exito=%s). Avisando a la interfaz.",
                slot_id,
                process_id,
                getattr(result, "success", "?"),
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
            _LOGGER.exception(
                "Worker terminado con error (slot=%s, proceso=%s).", slot_id, process_id
            )
            self._safe_after(
                0,
                lambda current_slot_id=slot_id, current_process_id=process_id, error=exc: self._handle_process_error(
                    current_slot_id,
                    current_process_id,
                    error,
                ),
            )

    def _registrar_huella_de_tk(self) -> None:
        """Cuantos objetos tiene vivos Tcl. Nunca lanza.

        Por que: tracemalloc dice que la memoria de Python apenas crece (53 a 57
        MB entre corridas) mientras el proceso sube cientos de MB. Esa diferencia
        solo puede estar en bibliotecas de C, y la candidata obvia es Tcl/Tk, que
        reserva por su cuenta y es invisible para tracemalloc.

        Si este numero sube corrida tras corrida, se estan creando widgets u
        objetos de Tk que nadie destruye. Si se mantiene, la memoria viene de
        otro sitio y hay que seguir buscando.
        """

        try:
            comandos = len(self.tk.call("info", "commands"))
        except Exception:  # noqa: BLE001
            comandos = -1
        try:
            imagenes = len(self.tk.call("image", "names"))
        except Exception:  # noqa: BLE001
            imagenes = -1
        try:
            fuentes = len(self.tk.call("font", "names"))
        except Exception:  # noqa: BLE001
            fuentes = -1
        _LOGGER.info(
            "Tk: comandos=%s | imagenes=%s | fuentes=%s",
            comandos,
            imagenes,
            fuentes,
        )

    def _finish_process(self, slot_id: str, process_id: str, result: ProcessExecutionResult) -> None:
        _LOGGER.info("La interfaz recibio el fin del proceso %s.", process_id)
        self._registrar_huella_de_tk()
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
                "El proceso falló y no se completó. Revisa la conexión y los datos del "
                "formulario, luego vuelve a intentar; usa 'Exportar debug' si se repite. "
                f"({safe_error_summary(exc, context='proceso')}) "
                f"Tiempo final: {self._format_elapsed_time(elapsed_seconds)}. "
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
            self._latest_debug_slot_id = self.SLOT_IDS[0]
        self._sync_run_button_state()
        self._layout_slots(self._layout_mode or "wide")
        return elapsed_seconds

    # ------------------------------------------------------------------
    # Purga automatica de local_data
    # ------------------------------------------------------------------
    #
    # MaintenanceService ya sabia limpiar por antiguedad, pero NADIE lo llamaba
    # desde la app: solo existia scripts/run_maintenance.py, que nadie ejecuta.
    # El resultado eran cientos de MB acumulados en el disco de cada agente.

    _LOCAL_CLEANUP_MIN_BYTES_TO_REPORT = 20 * 1024 * 1024

    def _start_local_data_cleanup(self) -> None:
        if self._is_closing:
            return
        threading.Thread(
            target=self._local_data_cleanup_worker,
            name="local-data-cleanup",
            daemon=True,
        ).start()

    def _local_data_cleanup_worker(self) -> None:
        """Corre en un hilo aparte. No toca Tk: solo disco y log."""

        try:
            from services.maintenance_service import MaintenanceService

            report = MaintenanceService(settings=self._settings).cleanup_local_data(
                dry_run=False,
                collect_items=False,
                # Mas conservador que el script manual: una corrida larga puede
                # seguir usando sus temporales horas despues de empezar.
                temp_photos_hours=24,
                failed_uploads_days=30,
                screenshots_days=14,
                debug_days=7,
                browser_profiles_days=3,
                review_thumbnails_days=30,
            )
        except Exception as exc:  # noqa: BLE001 - nunca debe tumbar la app
            _LOGGER.warning("No se pudo purgar local_data: %s", exc)
            return

        liberado = sum(
            int((seccion or {}).get("bytes_freed") or 0)
            for clave, seccion in report.items()
            if isinstance(seccion, dict)
        )
        borrados = sum(
            int((seccion or {}).get("removed") or 0)
            for clave, seccion in report.items()
            if isinstance(seccion, dict)
        )
        if not borrados:
            return
        _LOGGER.info(
            "Purga de local_data: %s elementos, %.1f MB liberados.",
            borrados,
            liberado / (1024 * 1024),
        )
        # Solo se molesta al operador si el ahorro fue notable.
        if liberado >= self._LOCAL_CLEANUP_MIN_BYTES_TO_REPORT:
            self._safe_after(
                0,
                lambda mb=liberado / (1024 * 1024): self._broadcast_status_message(
                    f"Limpieza automática: se liberaron {mb:.0f} MB de archivos antiguos.",
                    color=TEXT_MUTED,
                ),
            )

    def _handle_run_button(self, slot_id: str) -> None:
        """El boton principal inicia o detiene segun el estado del panel."""

        if self._get_slot(slot_id).thread is not None:
            self.stop_process(slot_id)
            return
        self.start_process(slot_id)

    def stop_process(self, slot_id: str) -> None:
        slot = self._get_slot(slot_id)
        if slot.thread is None:
            return
        if self._process_service.is_cancel_requested(slot_id):
            self._set_slot_status(
                slot_id,
                "Ya se pidio detener este proceso. Esperando al siguiente punto de control...",
                color=WARNING,
            )
            return
        if not confirm_destructive_action(
            title="Detener proceso",
            what="Se detendra este proceso en el siguiente punto de control.",
            scope=(
                "Si el proceso ya pulso el boton final en la pagina, el bloque puede "
                "haber quedado tomado aunque la corrida se detenga: compruebalo en la "
                "pagina antes de volver a intentarlo. El otro panel no se ve afectado."
            ),
            parent=self,
        ):
            return
        notified = self._process_service.request_cancel(slot_id)
        if not notified:
            self._set_slot_status(
                slot_id,
                "No se encontro una corrida activa que detener.",
                color=ERROR,
            )
            return
        self._set_slot_status(
            slot_id,
            "Deteniendo proceso... se cerrara en el siguiente punto de control.",
            color=WARNING,
        )
        self._sync_run_button_state()

    def _sync_run_button_state(self) -> None:
        if self._is_closing:
            return
        active_count = self._active_process_count()
        current_flow_engine = (self._current_config.flow_engine or "").strip().lower()
        access_blocked = bool(
            not self._current_user_is_admin()
            and (self._access_snapshot is None or not self._access_snapshot.can_use_app)
        )
        for slot_id, slot in self._slots.items():
            if slot.thread is not None:
                # Mientras corre, el boton principal pasa a "Detener" y sigue
                # activo: antes quedaba gris y no habia forma de parar nada.
                slot.panel.set_run_button_mode("stop")
                already_cancelling = self._process_service.is_cancel_requested(slot_id)
                slot.panel.run_button.configure(
                    state="disabled" if already_cancelling else "normal"
                )
                continue
            slot.panel.set_run_button_mode("start")
            disabled = (
                access_blocked
                or active_count >= 2
                or (active_count >= 1 and current_flow_engine != "traditional")
            )
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
        self._clear_owner_selfie_state(slot_id, remove_file=True)
        slot.panel.form_panel.clear()
        slot.panel.status_panel.clear_persistent_alert()
        slot.panel.status_panel.clear_retry_indicator()
        self._set_slot_status(slot_id, "Formulario limpiado manualmente.")

    @staticmethod
    def _allowed_owner_selfie_suffixes() -> tuple[str, ...]:
        return (".jpg", ".jpeg", ".png")

    def _owner_selfie_dir(self) -> Path:
        settings = self.__dict__.get("_settings")
        if settings is None:
            settings = get_settings()
        directory = settings.local_data_dir / "account_selfies"
        directory.mkdir(parents=True, exist_ok=True)
        return directory

    def _copy_owner_selfie_file(self, slot_id: str, source_path: Path) -> Path:
        suffix = source_path.suffix.lower()
        if suffix not in self._allowed_owner_selfie_suffixes():
            raise ValueError("Solo se permiten archivos JPG, JPEG o PNG.")
        if not source_path.is_file():
            raise ValueError("Selecciona una foto valida del titular o desactiva la opcion.")
        target_dir = self._owner_selfie_dir()
        for existing_suffix in self._allowed_owner_selfie_suffixes():
            existing = target_dir / f"{slot_id}_owner_selfie{existing_suffix}"
            if existing.exists():
                existing.unlink()
        target_path = target_dir / f"{slot_id}_owner_selfie{suffix}"
        shutil.copy2(source_path, target_path)
        return target_path

    def _owner_selfie_file_candidates(self, slot_id: str) -> list[Path]:
        target_dir = self._owner_selfie_dir()
        return [target_dir / f"{slot_id}_owner_selfie{suffix}" for suffix in self._allowed_owner_selfie_suffixes()]

    def _cleanup_owner_selfie_temp_files(self) -> None:
        for slot_id in self._slots:
            self._delete_owner_selfie_file(slot_id)
            form_panel = self._get_slot(slot_id).panel.form_panel
            set_owner_selfie_state = getattr(form_panel, "set_owner_selfie_state", None)
            if callable(set_owner_selfie_state):
                set_owner_selfie_state(enabled=False, path=None)

    def _delete_owner_selfie_file(self, slot_id: str) -> None:
        for candidate in self._owner_selfie_file_candidates(slot_id):
            with contextlib.suppress(FileNotFoundError):
                candidate.unlink()

    def _clear_owner_selfie_state(self, slot_id: str, *, remove_file: bool = True) -> None:
        if remove_file:
            self._delete_owner_selfie_file(slot_id)
        self._get_slot(slot_id).panel.form_panel.set_owner_selfie_state(enabled=False, path=None)

    def _handle_owner_selfie_toggle(self, slot_id: str, enabled: bool) -> None:
        form_panel = self._get_slot(slot_id).panel.form_panel
        current_path = form_panel.get_owner_selfie_data().get("owner_selfie_path")
        form_panel.set_owner_selfie_state(enabled=enabled, path=str(current_path) if current_path else None)

    def _handle_owner_selfie_select(self, slot_id: str) -> None:
        selected_path = filedialog.askopenfilename(
            parent=self,
            title="Seleccionar foto del titular",
            filetypes=[("Imagenes", "*.jpg *.jpeg *.png")],
        )
        if not selected_path:
            return
        try:
            copied = self._copy_owner_selfie_file(slot_id, Path(selected_path))
            self._get_slot(slot_id).panel.form_panel.set_owner_selfie_state(enabled=True, path=str(copied))
            self._set_slot_status(slot_id, f"Foto del titular guardada: {copied.name}", color=SUCCESS)
        except Exception as exc:
            self._set_slot_status(slot_id, str(exc), color=ERROR)

    def _handle_owner_selfie_remove(self, slot_id: str) -> None:
        self._clear_owner_selfie_state(slot_id, remove_file=True)
        self._set_slot_status(slot_id, "Foto del titular eliminada.", color=SUCCESS)

    def open_extension_test_browser(self, slot_id: str) -> None:
        if self._is_closing:
            return
        self._latest_debug_slot_id = slot_id
        self._set_slot_status(slot_id, "Abriendo Google Chrome con la extension y navegando a chrome://extensions...")
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
            f"Abriendo Google Chrome manualmente. Motor: {engine_label}. Destino: {target_url}",
        )
        thread = threading.Thread(
            target=self._open_manual_browser_worker,
            args=(slot_id, target_url),
            daemon=True,
        )
        thread.start()

    @staticmethod
    def _session_is_usable_here(session) -> bool:
        """Playwright's sync API may only be driven from the thread that created it.

        The UI thread is never that thread (sessions are created on the run
        worker), so a live capture from here used to be both a freeze and a
        cross-thread Playwright call. When the session is not ours we fall back to
        the snapshot the run itself captured.
        """

        checker = getattr(session, "is_owned_by_current_thread", None)
        if not callable(checker):
            return False
        try:
            return bool(checker())
        except Exception:  # noqa: BLE001
            return False

    @staticmethod
    def _last_known_frame_report(payload, *, error: str | None = None) -> dict:
        report = {}
        if isinstance(payload, dict):
            report = dict(payload.get("frame_debug_report") or {})
        if report:
            return report
        fallback: dict = {"total_frames": 0, "frames": []}
        if error:
            fallback["error"] = error
        else:
            fallback["note"] = (
                "Sin captura en vivo: el navegador pertenece al hilo del proceso. "
                "Se usa el ultimo estado capturado durante la corrida."
            )
        return fallback

    def _collect_session_debug_payload(self, session) -> tuple[dict | None, str | None]:
        """Extension debug for a session, never driving Playwright from the UI thread."""

        if not self._session_is_usable_here(session):
            payload = session.get_last_extension_debug() or BrowserManager.get_latest_extension_debug()
            note = (
                "Estado tomado del ultimo snapshot de la corrida: no se puede consultar "
                "el navegador en vivo desde la interfaz (Playwright es de un solo hilo)."
            )
            if isinstance(payload, dict):
                payload = {**payload, "live_capture": False, "live_capture_note": note}
            return payload, None
        try:
            payload = (
                session.capture_extension_debug(page=session.page, note="manual_process_export")
                or session.get_last_extension_debug()
            )
            return payload, None
        except Exception as exc:  # noqa: BLE001
            fallback = session.get_last_extension_debug() or BrowserManager.get_latest_extension_debug()
            return fallback, str(exc)

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
            payload, browser_export_warning = self._collect_session_debug_payload(session)
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
            live = self._session_is_usable_here(session)
            if live:
                with contextlib.suppress(Exception):
                    current_url = session.page.url
                with contextlib.suppress(Exception):
                    body_text = session.page.locator("body").first.inner_text(timeout=700).strip()
                try:
                    frames_payload = session.debug_list_all_frames(page=session.page)
                except Exception as exc:
                    if browser_export_warning is None:
                        browser_export_warning = str(exc)
                    frames_payload = self._last_known_frame_report(payload, error=str(exc))
            else:
                frames_payload = self._last_known_frame_report(payload)

        if not payload and not process_payload:
            self._set_slot_status(slot_id, "No hay estado del proceso para exportar. Ejecuta un proceso y vuelve a pulsar 'Exportar debug'.", color=ERROR)
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
            self._set_slot_status(slot_id, f"No se pudo exportar el estado del proceso. Revisa que la carpeta de destino sea escribible. ({safe_error_summary(exc, context='export de estado')})", color=ERROR)
            return

        self._set_slot_status(slot_id, f"Estado del proceso exportado a {target}", color=SUCCESS)

    def _handle_admin_export_debug(self, slot_name: str) -> None:
        slot_id = self.slot_id_por_titulo(slot_name)
        self.export_extension_state(slot_id)

    def _refresh_admin_diagnostics_if_open(self) -> None:
        if self._admin_uploader_dialog is None or not self._admin_uploader_dialog.winfo_exists():
            return
        with contextlib.suppress(Exception):
            self._admin_uploader_dialog.mark_diagnostics_stale()

    def _build_admin_diagnostics_payload(self) -> dict[str, dict]:
        payload: dict[str, dict] = {}
        for slot_id, slot in self._slots.items():
            payload[self.slot_title(slot_id)] = self._build_slot_diagnostic_snapshot(slot_id)
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
            if self._session_is_usable_here(session):
                try:
                    frames_payload = session.debug_list_all_frames(page=session.page)
                except Exception as exc:
                    browser_export_warning = str(exc)
                    frames_payload = self._last_known_frame_report(session_debug, error=str(exc))
            else:
                # Called from the Tk thread: the session belongs to the run worker.
                frames_payload = self._last_known_frame_report(session_debug)
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
            # Lo abre el agente desde la interfaz: el vigilante no debe
            # cerrarselo a los 15 minutos por parecer una corrida abandonada.
            operator_owned=keep_open,
        )

    def _schedule_process_progress(self, slot_id: str, phase: str, message: str) -> None:
        def apply_progress() -> None:
            if self._is_closing:
                return
            slot = self._get_slot(slot_id)
            lowered = message.lower()
            retry_match = re.search(r"reintentos(?: de selfie)?:\s*(\d+)", lowered)
            if "deepfakescore" in lowered:
                # El numero va DENTRO del aviso. Estaba solo en el otro chip, y
                # el agente mira este: veia "deepfakescore" a secas y no sabia
                # si llevaba un reintento o siete.
                intentos = retry_match.group(1) if retry_match is not None else None
                slot.panel.status_panel.set_persistent_alert(
                    f"deepfakescore x{intentos}" if intentos else "deepfakescore"
                )
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
                f"No se pudo insertar el log de prueba en Supabase. Revisa la conexión y las credenciales, luego reintenta. ({safe_error_summary(exc, context='log de prueba')})",
                color=ERROR,
            )
        self._broadcast_status_message(f"No se pudo insertar el log de prueba en Supabase. Revisa la conexión y las credenciales, luego reintenta. ({safe_error_summary(exc, context='log de prueba')})", color=ERROR)

    def refresh_extension_status(self) -> None:
        """Marca el diagnostico del panel de administracion como desactualizado.

        Antes esto construia un diccionario de debug completo y repintaba dos
        ExtensionStatusPanel, y se reprogramaba a si misma cada segundo para
        siempre. Pero esos dos paneles nunca se mostraban en pantalla ni los
        leia nadie, asi que eran ~45 llamadas a configure() por segundo tiradas
        a la basura, de forma permanente, hubiera o no una corrida activa.

        El diagnostico que el operador si ve es el de admin_dialogs.py:948, que
        se alimenta bajo demanda con su boton "Refrescar". Lo unico que esta
        funcion aportaba era avisarle de que hay cambios, y para eso basta con
        llamarla desde los eventos reales (inicio y fin de proceso, cambio de
        configuracion, apertura de navegador), que es como se la llama ya.
        """

        if self._is_closing:
            return
        self._refresh_admin_diagnostics_if_open()

    def _safe_after(self, delay_ms: int, callback, *, allow_during_close: bool = False) -> None:
        if self._is_closing and not allow_during_close:
            _LOGGER.debug("_safe_after descartado: la app se esta cerrando.")
            return
        try:
            self.after(delay_ms, callback)
        except Exception:
            # Tragarse esto en silencio deja al usuario con un proceso que
            # parece colgado para siempre: el trabajo termino y el aviso a la
            # interfaz se perdio sin dejar rastro. Que al menos quede escrito.
            _LOGGER.exception("No se pudo programar un callback en la interfaz.")
            return

    # How long a cooperative close waits for the running automations to finish
    # their own cleanup (release the photo, delete temp files, persist the result,
    # close Playwright) before giving up and saying so.
    SHUTDOWN_GRACE_SECONDS = 30.0

    # Class-level default: Tk's __getattr__ recurses on a widget whose __init__ has
    # not run, so this must resolve without falling through to it.
    _close_prompt_open = False

    # Mismo motivo: _layout_header_actions nombra este boton, y si no existe
    # como atributo de clase, leerlo en una ventana a medio construir cae en el
    # __getattr__ de Tk y revienta con RecursionError en vez de con un
    # AttributeError legible.
    close_browsers_button = None

    # Igual: si medir el equipo falla, el atributo no llega a asignarse y
    # cualquier lectura posterior caeria en el __getattr__ de Tk.
    _machine_tuning = None

    def _handle_app_close(self, *, confirm: bool = True) -> None:
        if self._is_closing or self._close_prompt_open:
            return
        active = self._active_process_count()
        # askyesno pumps the Tk event loop, so a second WM_DELETE while it is open
        # would re-enter here and stack another dialog.
        self._close_prompt_open = True
        try:
            confirmed = not (confirm and active > 0) or messagebox.askyesno(
                "Cerrar aplicación",
                f"Hay {active} proceso(s) en ejecución.\n\n"
                "Al cerrar se les pedirá que se detengan y se esperará hasta "
                f"{int(self.SHUTDOWN_GRACE_SECONDS)} s a que liberen la foto reservada, "
                "borren sus archivos temporales y cierren el navegador.\n\n"
                "¿Cerrar la aplicación?",
                parent=self,
                default=messagebox.NO,
            )
        finally:
            self._close_prompt_open = False
        if not confirmed:
            return
        self._is_closing = True
        self._cleanup_owner_selfie_temp_files()
        # 1) no new runs, and the ones in flight are asked to stop.
        cancelled = 0
        with contextlib.suppress(Exception):
            cancelled = self._process_service.begin_shutdown()
        for slot_id, slot in self._slots.items():
            self._stop_process_timer(slot_id, prefix="Tiempo final")
            with contextlib.suppress(Exception):
                slot.panel.run_button.configure(state="disabled")
            with contextlib.suppress(Exception):
                slot.panel.clear_button.configure(state="disabled")
        with contextlib.suppress(Exception):
            if cancelled:
                self._broadcast_status_message(
                    f"Cerrando: esperando a que {cancelled} proceso(s) liberen sus "
                    f"recursos (hasta {int(self.SHUTDOWN_GRACE_SECONDS)} s)...",
                    color=WARNING,
                )
            else:
                self._broadcast_status_message("Cerrando Playwright y recursos activos...")
        threading.Thread(
            target=self._shutdown_and_destroy,
            name="app-shutdown",
            daemon=True,
        ).start()

    def _shutdown_and_destroy(self) -> None:
        """Cooperative, bounded close.

        Order matters: the run threads own their Playwright sessions, so they must
        finish their own finally blocks *first*. Tearing the browsers down before
        joining them (the old order) guaranteed that every in-flight cleanup failed.
        """

        workers = [slot.thread for slot in self._slots.values() if slot.thread is not None]
        deadline = monotonic() + self.SHUTDOWN_GRACE_SECONDS
        for worker in workers:
            remaining = deadline - monotonic()
            if remaining <= 0:
                break
            if worker.is_alive():
                worker.join(timeout=remaining)
        pending = [worker for worker in workers if worker.is_alive()]
        if pending:
            # Say so instead of pretending the cleanup completed.
            with contextlib.suppress(Exception):
                self._safe_after(
                    0,
                    lambda count=len(pending): self._broadcast_status_message(
                        f"{count} proceso(s) no respondieron a tiempo. Se cierra igualmente: "
                        "puede quedar una foto reservada y un Chrome abierto.",
                        color=ERROR,
                    ),
                    allow_during_close=True,
                )
        # Only now tear down whatever is left open.
        try:
            self._process_service.shutdown()
        except Exception:
            pass
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
        form_panel = self._get_slot(slot_id).panel.form_panel
        data = form_panel.get_form_data()
        owner_selfie_data = form_panel.get_owner_selfie_data()
        agent_name = validate_non_empty_string(self._current_config.agent_name, "agent_name")
        phone_number = sanitize_phone_number(data["phone_number"])
        validate_non_empty_string(data["password"], "password")
        owner_selfie_enabled = bool(owner_selfie_data.get("owner_selfie_enabled"))
        owner_selfie_path = str(owner_selfie_data.get("owner_selfie_path") or "").strip() or None
        if owner_selfie_enabled:
            suffix = Path(owner_selfie_path or "").suffix.lower()
            if not owner_selfie_path or not Path(owner_selfie_path).is_file() or suffix not in self._allowed_owner_selfie_suffixes():
                raise ValueError("Selecciona una foto valida del titular o desactiva la opcion.")
        return ProcessExecutionRequest(
            process_id=process_id,
            slot_id=slot_id,
            page_name=data["page_name"],
            action_name=data["action_name"],
            phone_number=phone_number,
            password=data["password"],
            agent_name=agent_name,
            execution_mode=self._current_config.flow_engine,
            owner_selfie_enabled=owner_selfie_enabled,
            owner_selfie_path=owner_selfie_path,
        )

    @staticmethod
    def _get_local_device_name() -> str:
        return os.getenv("COMPUTERNAME") or platform.node().strip() or "UNKNOWN_DEVICE"

    @staticmethod
    def _parse_browser_window(raw_value: str, actual: tuple[int, int]) -> tuple[int, int]:
        """Lee "1440x960". Si no se entiende, se queda lo que habia.

        Un tamano a medio escribir no puede dejar al agente con un navegador
        de 3 pixeles, asi que tambien se aplica un suelo: por debajo de
        900x600 los sitios cambian a su diseno movil, que es otro HTML y
        romperia todos los selectores.
        """

        texto = str(raw_value or "").lower().replace(" ", "")
        for separador in ("x", "*", ","):
            if separador in texto:
                ancho_txt, _, alto_txt = texto.partition(separador)
                try:
                    return max(int(ancho_txt), 900), max(int(alto_txt), 600)
                except ValueError:
                    return actual
        return actual

    @staticmethod
    def _parse_zoom(raw_value: str) -> int:
        texto = str(raw_value or "").replace("%", "").strip()
        try:
            porcentaje = int(texto)
        except ValueError:
            return 100
        return porcentaje if 25 <= porcentaje <= 200 else 100

    def _extract_local_config(self, data: dict[str, str] | None = None) -> LocalConfig:
        source = data or {}
        ancho_navegador, alto_navegador = self._parse_browser_window(
            source.get("browser_window", ""),
            (
                self._current_config.browser_window_width,
                self._current_config.browser_window_height,
            ),
        )
        return LocalConfig(
            agent_name=validate_non_empty_string(source["agent_name"], "agent_name"),
            agent_name_confirmed=True,
            # El selector de motor ya no existe en Ajustes: el motor de
            # extension esta muerto. Se fija aqui en vez de leerlo del
            # formulario para que no dependa de una clave que ya nadie envia.
            flow_engine="traditional",
            automation_version=(
                "v2"
                if str(source.get("automation_version", "")).strip().lower().startswith("v2")
                else "v1"
            ),
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
            # La ventana de ajustes no muestra estos campos. Si no se arrastran
            # desde la configuracion actual, guardar ajustes los devolveria a
            # su valor de fabrica y la app volveria a medir el equipo en el
            # siguiente arranque, pisando lo que el agente acaba de elegir.
            paripe_block_wait_seconds=self._current_config.paripe_block_wait_seconds,
            browser_window_width=ancho_navegador,
            browser_window_height=alto_navegador,
            browser_zoom_percent=self._parse_zoom(source.get("browser_zoom", "100%")),
            max_concurrent_processes=self._current_config.max_concurrent_processes,
            hardware_signature=self._current_config.hardware_signature,
            hardware_profile=self._current_config.hardware_profile,
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
