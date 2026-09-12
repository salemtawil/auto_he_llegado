from __future__ import annotations

import threading
from pathlib import Path
import tkinter as tk
from tkinter import filedialog

import customtkinter as ctk

from services.access_service import AccessService, AccessSnapshot
from services.auth_context import AuthSession
from services.background_video_status import set_video_status
from services.login_credentials_store import LoginCredentialsStore
from services.video_contribution_service import VideoContributionProgress, VideoContributionService
from ui.theme import (
    ACCENT,
    ACCENT_HOVER,
    APP_BG,
    BORDER,
    CARD_BG,
    ERROR,
    INPUT_BG,
    NEUTRAL_BUTTON,
    NEUTRAL_BUTTON_HOVER,
    SUCCESS,
    TEXT_MUTED,
    TEXT_PRIMARY,
    WARNING,
)


class LoginWindow(ctk.CTk):
    def __init__(
        self,
        *,
        access_service: AccessService | None = None,
        credentials_store: LoginCredentialsStore | None = None,
        video_service: VideoContributionService | None = None,
    ) -> None:
        super().__init__()
        self._access_service = access_service or AccessService()
        self._credentials_store = credentials_store or LoginCredentialsStore()
        self._video_service = video_service or VideoContributionService()
        self._session: AuthSession | None = None
        self._snapshot: AccessSnapshot | None = None
        self._result: AuthSession | None = None
        self._selected_video: Path | None = None
        self._busy = False
        self._mode = "login"
        self._password_visible = False

        self.title("Auto He Llegado | Acceso")
        self.geometry("540x560")
        self.minsize(520, 540)
        self.resizable(False, False)
        self.configure(fg_color=APP_BG)
        self.protocol("WM_DELETE_WINDOW", self._cancel)

        self.container = ctk.CTkFrame(
            self,
            fg_color=CARD_BG,
            corner_radius=18,
            border_width=1,
            border_color=BORDER,
        )
        self.container.pack(fill="both", expand=True, padx=22, pady=22)
        self.container.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            self.container,
            text="Auto He Llegado",
            font=ctk.CTkFont(size=24, weight="bold"),
            text_color=TEXT_PRIMARY,
        ).grid(row=0, column=0, padx=24, pady=(24, 4), sticky="w")

        self.subtitle_label = ctk.CTkLabel(
            self.container,
            text="Inicia sesion para validar tu acceso y tu colaboracion requerida.",
            text_color=TEXT_MUTED,
            justify="left",
            wraplength=430,
        )
        self.subtitle_label.grid(row=1, column=0, padx=24, pady=(0, 18), sticky="ew")

        self.mode_selector = ctk.CTkFrame(
            self.container,
            fg_color=NEUTRAL_BUTTON,
            corner_radius=12,
            border_width=1,
            border_color=BORDER,
        )
        self.mode_selector.grid(row=2, column=0, padx=24, pady=(0, 16), sticky="ew")
        self.mode_selector.grid_columnconfigure((0, 1), weight=1, uniform="login_mode")
        self.login_mode_button = ctk.CTkButton(
            self.mode_selector,
            text="Entrar",
            command=lambda: self._set_mode("Entrar"),
            height=34,
            corner_radius=10,
        )
        self.login_mode_button.grid(row=0, column=0, padx=(3, 2), pady=3, sticky="ew")
        self.register_mode_button = ctk.CTkButton(
            self.mode_selector,
            text="Crear cuenta",
            command=lambda: self._set_mode("Crear cuenta"),
            height=34,
            corner_radius=10,
        )
        self.register_mode_button.grid(row=0, column=1, padx=(2, 3), pady=3, sticky="ew")

        self.email_entry = self._entry("Usuario o email", "usuario o correo@ejemplo.com", row=3)
        self.email_entry.bind("<Return>", lambda _event: self._handle_primary_action())

        self.register_panel = ctk.CTkFrame(self.container, fg_color="transparent")
        self.register_panel.grid(row=4, column=0, padx=24, pady=(0, 0), sticky="ew")
        self.register_panel.grid_columnconfigure(0, weight=1)
        self.register_email_entry = self._panel_entry(
            self.register_panel,
            "Correo",
            "correo@ejemplo.com",
            row=0,
        )
        self.register_panel.grid_remove()

        self.password_entry = self._entry("Contrasena", "Contrasena", row=5, show="*")
        self.password_entry.bind("<Return>", lambda _event: self._handle_primary_action())
        self.bind("<Return>", lambda _event: self._handle_primary_action())

        self.remember_var = tk.BooleanVar(value=False)
        self.remember_checkbox = ctk.CTkCheckBox(
            self.container,
            text="Recordar acceso en este equipo",
            variable=self.remember_var,
            checkbox_width=18,
            checkbox_height=18,
            text_color=TEXT_PRIMARY,
            fg_color=ACCENT,
            hover_color=ACCENT_HOVER,
        )
        self.remember_checkbox.grid(row=6, column=0, padx=24, pady=(0, 4), sticky="w")

        self.status_label = ctk.CTkLabel(
            self.container,
            text="",
            text_color=TEXT_MUTED,
            justify="left",
            wraplength=430,
        )
        self.status_label.grid(row=7, column=0, padx=24, pady=(8, 0), sticky="ew")

        self.login_button = ctk.CTkButton(
            self.container,
            text="Entrar",
            command=self._handle_primary_action,
            height=42,
            corner_radius=12,
            fg_color=ACCENT,
            hover_color=ACCENT_HOVER,
        )
        self.login_button.grid(row=8, column=0, padx=24, pady=(18, 10), sticky="ew")

        self.video_panel = ctk.CTkFrame(self.container, fg_color="transparent")
        self.video_panel.grid(row=9, column=0, padx=24, pady=(12, 0), sticky="ew")
        self.video_panel.grid_columnconfigure(0, weight=1)
        self.video_panel.grid_remove()

        self.video_status_label = ctk.CTkLabel(
            self.video_panel,
            text="",
            text_color=WARNING,
            justify="left",
            wraplength=430,
        )
        self.video_status_label.grid(row=0, column=0, columnspan=2, pady=(0, 10), sticky="ew")

        self.select_video_button = ctk.CTkButton(
            self.video_panel,
            text="Seleccionar video",
            command=self._select_video,
            height=38,
            corner_radius=12,
            fg_color=NEUTRAL_BUTTON,
            hover_color=NEUTRAL_BUTTON_HOVER,
            text_color=TEXT_PRIMARY,
        )
        self.select_video_button.grid(row=1, column=0, padx=(0, 8), sticky="ew")

        self.submit_video_button = ctk.CTkButton(
            self.video_panel,
            text="Procesar y enviar",
            command=self._submit_video,
            height=38,
            corner_radius=12,
            fg_color=ACCENT,
            hover_color=ACCENT_HOVER,
            state="disabled",
        )
        self.submit_video_button.grid(row=1, column=1, padx=(8, 0), sticky="ew")

        self.progress_bar = ctk.CTkProgressBar(self.video_panel, height=10, corner_radius=999)
        self.progress_bar.grid(row=2, column=0, columnspan=2, pady=(14, 0), sticky="ew")
        self.progress_bar.set(0.0)

        self._load_remembered_login()
        self._set_mode("Entrar")
        self.after(100, self._focus_initial_field)

    @property
    def result(self) -> AuthSession | None:
        return self._result

    def _entry(self, label: str, placeholder: str, *, row: int, show: str | None = None) -> ctk.CTkEntry:
        frame = ctk.CTkFrame(self.container, fg_color="transparent")
        frame.grid(row=row, column=0, padx=24, pady=(0, 10), sticky="ew")
        frame.grid_columnconfigure(0, weight=1)
        label_widget = ctk.CTkLabel(
            frame,
            text=label,
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=TEXT_PRIMARY,
        )
        label_widget.grid(row=0, column=0, pady=(0, 4), sticky="w")
        entry = ctk.CTkEntry(
            frame,
            placeholder_text=placeholder,
            show=show,
            fg_color=INPUT_BG,
            border_color=BORDER,
            border_width=1,
            corner_radius=12,
            height=40,
        )
        entry.grid(row=1, column=0, sticky="ew")
        if show is not None:
            self.password_toggle_button = ctk.CTkButton(
                frame,
                text="Ver",
                command=self._toggle_password_visibility,
                width=62,
                height=40,
                corner_radius=12,
                fg_color=NEUTRAL_BUTTON,
                hover_color=NEUTRAL_BUTTON_HOVER,
                text_color=TEXT_PRIMARY,
            )
            self.password_toggle_button.grid(row=1, column=1, padx=(8, 0), sticky="e")
        if row == 3:
            self.identifier_label = label_widget
        return entry

    def _panel_entry(
        self,
        parent: ctk.CTkFrame,
        label: str,
        placeholder: str,
        *,
        row: int,
        show: str | None = None,
    ) -> ctk.CTkEntry:
        frame = ctk.CTkFrame(parent, fg_color="transparent")
        frame.grid(row=row, column=0, pady=(0, 10), sticky="ew")
        frame.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            frame,
            text=label,
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=TEXT_PRIMARY,
        ).grid(row=0, column=0, pady=(0, 4), sticky="w")
        entry = ctk.CTkEntry(
            frame,
            placeholder_text=placeholder,
            show=show,
            fg_color=INPUT_BG,
            border_color=BORDER,
            border_width=1,
            corner_radius=12,
            height=40,
        )
        entry.grid(row=1, column=0, sticky="ew")
        return entry

    def _set_mode(self, selected: str) -> None:
        self._mode = "register" if selected == "Crear cuenta" else "login"
        is_register = self._mode == "register"
        self._render_mode_buttons()
        self.identifier_label.configure(text="Nombre de usuario" if is_register else "Usuario o email")
        self.email_entry.configure(
            placeholder_text="usuario" if is_register else "usuario o correo@ejemplo.com"
        )
        self.register_panel.grid() if is_register else self.register_panel.grid_remove()
        self.remember_checkbox.grid_remove() if is_register else self.remember_checkbox.grid()
        self.video_panel.grid_remove()
        self._selected_video = None
        self.submit_video_button.configure(state="disabled")
        self.login_button.configure(text="Crear cuenta" if is_register else "Entrar")
        self.status_label.configure(
            text=(
                "Crea tu usuario. Un admin debe aprobar la cuenta antes de usar la app."
                if is_register
                else ""
            ),
            text_color=TEXT_MUTED,
        )

    def _handle_login(self) -> None:
        if self._busy:
            return
        identifier = self.email_entry.get().strip()
        password = self.password_entry.get().strip()
        self._set_busy(True, "Validando acceso...")
        thread = threading.Thread(target=lambda: self._login_worker(identifier, password), daemon=True)
        thread.start()

    def _handle_primary_action(self) -> None:
        if self._mode == "register":
            self._handle_register()
        else:
            self._handle_login()

    def _handle_register(self) -> None:
        if self._busy:
            return
        login_id = self.email_entry.get().strip()
        email = self.register_email_entry.get().strip()
        password = self.password_entry.get().strip()
        self._set_busy(True, "Creando cuenta...")
        thread = threading.Thread(
            target=lambda: self._register_worker(login_id, email, password),
            daemon=True,
        )
        thread.start()

    def _login_worker(self, identifier: str, password: str) -> None:
        try:
            session = self._access_service.sign_in(
                identifier=identifier,
                password=password,
            )
            self._save_remembered_login(identifier, password)
            snapshot = self._access_service.get_access_snapshot(session)
            self.after(0, lambda: self._finish_login(session, snapshot))
        except Exception as exc:
            self.after(
                0,
                lambda error=exc: self._finish_error(
                    f"No se pudo iniciar sesion: {self._friendly_access_error(error)}"
                ),
            )

    def _render_mode_buttons(self) -> None:
        active_text = ("#FFFFFF", "#FFFFFF")
        inactive_text = TEXT_PRIMARY
        self.login_mode_button.configure(
            fg_color=ACCENT if self._mode == "login" else NEUTRAL_BUTTON,
            hover_color=ACCENT_HOVER if self._mode == "login" else NEUTRAL_BUTTON_HOVER,
            text_color=active_text if self._mode == "login" else inactive_text,
            border_width=0,
        )
        self.register_mode_button.configure(
            fg_color=ACCENT if self._mode == "register" else NEUTRAL_BUTTON,
            hover_color=ACCENT_HOVER if self._mode == "register" else NEUTRAL_BUTTON_HOVER,
            text_color=active_text if self._mode == "register" else inactive_text,
            border_width=0,
        )

    def _toggle_password_visibility(self) -> None:
        self._password_visible = not self._password_visible
        self.password_entry.configure(show="" if self._password_visible else "*")
        self.password_toggle_button.configure(text="Ocultar" if self._password_visible else "Ver")

    def _register_worker(self, login_id: str, email: str, password: str) -> None:
        try:
            result = self._access_service.register_member(
                login_id=login_id,
                email=email,
                password=password,
                display_name=login_id,
            )
            self.after(0, lambda current=result: self._finish_register(current.login_id, current.email))
        except Exception as exc:
            self.after(
                0,
                lambda error=exc: self._finish_error(
                    f"No se pudo crear la cuenta: {self._friendly_access_error(error)}"
                ),
            )

    def _finish_register(self, login_id: str, email: str) -> None:
        self._set_busy(False)
        self._set_mode("Entrar")
        self.email_entry.delete(0, "end")
        self.email_entry.insert(0, login_id or email)
        self.password_entry.delete(0, "end")
        self.register_email_entry.delete(0, "end")
        self.status_label.configure(
            text="Cuenta creada. Espera aprobacion del admin para poder usar la app.",
            text_color=SUCCESS,
        )

    def _finish_login(self, session: AuthSession, snapshot: AccessSnapshot) -> None:
        self._set_busy(False)
        self._session = session
        self._snapshot = snapshot
        if snapshot.can_use_app:
            self.status_label.configure(text=snapshot.reason, text_color=SUCCESS)
            self._result = session
            self.after(400, self.destroy)
            return
        if snapshot.needs_weekly_video:
            self.status_label.configure(text=snapshot.reason, text_color=WARNING)
            self._result = session
            self.after(400, self.destroy)
            return
        self.status_label.configure(text=snapshot.reason, text_color=ERROR)

    def _select_video(self) -> None:
        selected = filedialog.askopenfilename(
            title="Seleccionar video requerido",
            filetypes=[
                ("Videos", "*.mp4 *.mov *.m4v *.avi *.mkv"),
                ("Todos", "*.*"),
            ],
        )
        if not selected:
            return
        self._selected_video = Path(selected)
        self.video_status_label.configure(
            text=f"Video seleccionado: {self._selected_video.name}",
            text_color=TEXT_PRIMARY,
        )
        self.submit_video_button.configure(state="normal")

    def _submit_video(self) -> None:
        if self._busy or self._selected_video is None or self._session is None:
            return
        selected_video = self._selected_video
        session = self._session
        self._set_busy(True, "Enviando video en segundo plano...")
        self.progress_bar.set(0.0)
        thread = threading.Thread(
            target=lambda: self._submit_video_background_worker(selected_video, session),
            daemon=True,
        )
        thread.start()
        self.video_status_label.configure(
            text="Video recibido. Puedes empezar a usar la app mientras se envia al admin.",
            text_color=SUCCESS,
        )
        self.status_label.configure(
            text="La carga del video continua en segundo plano.",
            text_color=SUCCESS,
        )
        self._result = session
        self.after(500, self.destroy)

    def _submit_video_worker(self) -> None:
        try:
            self._video_service.submit_video(
                self._selected_video or "",
                session=self._session,
                progress_callback=lambda progress: self.after(
                    0,
                    lambda current=progress: self._apply_video_progress(current),
                ),
            )
            self.after(0, self._finish_video_submission)
        except Exception as exc:
            self.after(0, lambda error=exc: self._finish_error(f"No se pudo procesar el video: {error}"))

    def _submit_video_background_worker(self, video_path: Path, session: AuthSession) -> None:
        set_video_status(
            phase="queued",
            message="Video recibido. Preparando envio en segundo plano...",
            is_running=True,
        )
        try:
            result = self._video_service.submit_video(
                video_path,
                session=session,
                progress_callback=lambda progress: set_video_status(
                    phase=progress.phase,
                    message=progress.message,
                    current=progress.current,
                    total=progress.total,
                    is_running=True,
                ),
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
        except Exception as exc:
            set_video_status(
                phase="error",
                message=f"No se pudo completar el envio del video: {exc}",
                is_error=True,
            )
            return

    def _apply_video_progress(self, progress: VideoContributionProgress) -> None:
        self.video_status_label.configure(text=progress.message, text_color=TEXT_PRIMARY)
        if progress.total > 0:
            self.progress_bar.set(max(0.0, min(progress.current / progress.total, 1.0)))

    def _finish_video_submission(self) -> None:
        self._set_busy(False)
        self.video_status_label.configure(
            text="Video recibido. Acceso activo mientras no sea rechazado por admin.",
            text_color=SUCCESS,
        )
        self.progress_bar.set(1.0)
        if self._session is not None:
            self._result = self._session
            self.after(700, self.destroy)

    def _finish_error(self, message: str) -> None:
        self._set_busy(False)
        self.status_label.configure(text=message, text_color=ERROR)
        if self.video_panel.winfo_manager():
            self.video_status_label.configure(text=message, text_color=ERROR)

    @staticmethod
    def _friendly_access_error(exc: Exception) -> str:
        message = str(exc).strip()
        normalized = message.lower()
        if (
            "nodename nor servname provided" in normalized
            or "name or service not known" in normalized
            or "failed to resolve" in normalized
            or "getaddrinfo failed" in normalized
            or "[errno 8]" in normalized
            or "[errno 11001]" in normalized
        ):
            return (
                "No se pudo conectar con Supabase. Revisa la conexion a internet y que "
                "SUPABASE_URL este configurado correctamente en esta instalacion."
            )
        return message or exc.__class__.__name__

    def _set_busy(self, busy: bool, message: str | None = None) -> None:
        self._busy = busy
        state = "disabled" if busy else "normal"
        self.login_button.configure(state=state)
        self.login_mode_button.configure(state=state)
        self.register_mode_button.configure(state=state)
        self.email_entry.configure(state=state)
        self.password_entry.configure(state=state)
        self.register_email_entry.configure(state=state)
        self.password_toggle_button.configure(state=state)
        self.remember_checkbox.configure(state=state)
        self.select_video_button.configure(state=state)
        self.submit_video_button.configure(state="disabled" if busy or self._selected_video is None else "normal")
        if message:
            self.status_label.configure(text=message, text_color=TEXT_MUTED)

    def _load_remembered_login(self) -> None:
        remembered = self._credentials_store.load()
        if remembered.identifier:
            self.email_entry.insert(0, remembered.identifier)
            self.remember_var.set(True)
        if remembered.password:
            self.password_entry.insert(0, remembered.password)
            self.remember_var.set(True)

    def _save_remembered_login(self, identifier: str, password: str) -> None:
        if self.remember_var.get():
            self._credentials_store.save(identifier=identifier, password=password)
        else:
            self._credentials_store.clear()

    def _focus_initial_field(self) -> None:
        if not self.email_entry.get():
            self.email_entry.focus()
        elif not self.password_entry.get():
            self.password_entry.focus()
        else:
            self.login_button.focus()

    def _cancel(self) -> None:
        self._result = None
        self.destroy()


def request_app_access() -> AuthSession | None:
    window = LoginWindow()
    window.mainloop()
    return window.result
