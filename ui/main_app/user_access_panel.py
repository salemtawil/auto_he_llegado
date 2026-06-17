from __future__ import annotations

import threading

import customtkinter as ctk

from services.user_access_admin_service import UserAccessAdminService, UserAccessRecord
from ui.theme import (
    ACCENT,
    ACCENT_HOVER,
    BORDER,
    CARD_ALT_BG,
    CARD_BG,
    ERROR,
    NEUTRAL_BUTTON,
    NEUTRAL_BUTTON_HOVER,
    SUCCESS,
    TEXT_MUTED,
    TEXT_PRIMARY,
    WARNING,
)


class UserAccessPanel(ctk.CTkFrame):
    def __init__(
        self,
        master,
        *,
        access_admin_service: UserAccessAdminService | None = None,
        **kwargs,
    ) -> None:
        super().__init__(master, fg_color="transparent", **kwargs)
        self._service = access_admin_service or UserAccessAdminService()
        self._is_loading = False
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)
        self._build_header()
        self._build_list()
        self.refresh()

    def _build_header(self) -> None:
        header = ctk.CTkFrame(
            self,
            fg_color=CARD_BG,
            corner_radius=18,
            border_width=1,
            border_color=BORDER,
        )
        header.grid(row=0, column=0, pady=(0, 12), sticky="ew")
        header.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            header,
            text="Usuarios",
            font=ctk.CTkFont(size=20, weight="bold"),
            text_color=TEXT_PRIMARY,
        ).grid(row=0, column=0, padx=16, pady=(14, 4), sticky="w")

        self.status_label = ctk.CTkLabel(
            header,
            text="Cargando usuarios...",
            text_color=TEXT_MUTED,
            justify="left",
        )
        self.status_label.grid(row=1, column=0, padx=16, pady=(0, 14), sticky="w")

        self.refresh_button = ctk.CTkButton(
            header,
            text="Refrescar",
            command=self.refresh,
            height=36,
            width=110,
            corner_radius=12,
            fg_color=NEUTRAL_BUTTON,
            hover_color=NEUTRAL_BUTTON_HOVER,
            text_color=TEXT_PRIMARY,
        )
        self.refresh_button.grid(row=0, column=1, rowspan=2, padx=16, pady=14, sticky="e")

    def _build_list(self) -> None:
        self.scroll = ctk.CTkScrollableFrame(
            self,
            fg_color=CARD_ALT_BG,
            corner_radius=14,
            border_width=1,
            border_color=BORDER,
        )
        self.scroll.grid(row=1, column=0, sticky="nsew")
        self.scroll.grid_columnconfigure(0, weight=1)

    def refresh(self) -> None:
        if self._is_loading:
            return
        self._is_loading = True
        self.refresh_button.configure(state="disabled", text="Cargando...")
        threading.Thread(target=self._refresh_worker, daemon=True).start()

    def _refresh_worker(self) -> None:
        try:
            users = self._service.list_users()
            self.after(0, lambda: self._apply_users(users))
        except Exception as exc:
            self.after(0, lambda error=exc: self._show_error(error))

    def _apply_users(self, users: list[UserAccessRecord]) -> None:
        self._is_loading = False
        self.refresh_button.configure(state="normal", text="Refrescar")
        approved = sum(1 for user in users if user.approved and not user.disabled)
        pending = sum(1 for user in users if not user.approved and not user.disabled)
        disabled = sum(1 for user in users if user.disabled)
        self.status_label.configure(
            text=f"Aprobados {approved} | Pendientes {pending} | Deshabilitados {disabled}",
            text_color=TEXT_MUTED,
        )
        for child in self.scroll.winfo_children():
            child.destroy()
        if not users:
            ctk.CTkLabel(self.scroll, text="No hay perfiles registrados.", text_color=TEXT_MUTED).grid(
                row=0,
                column=0,
                padx=16,
                pady=16,
                sticky="w",
            )
            return
        for row, user in enumerate(users):
            self._user_row(user).grid(row=row, column=0, padx=8, pady=6, sticky="ew")

    def _user_row(self, user: UserAccessRecord) -> ctk.CTkFrame:
        row = ctk.CTkFrame(
            self.scroll,
            fg_color=CARD_BG,
            corner_radius=12,
            border_width=1,
            border_color=BORDER,
        )
        row.grid_columnconfigure(0, weight=1)
        state = "deshabilitado" if user.disabled else ("aprobado" if user.approved else "pendiente")
        state_color = ERROR if user.disabled else (SUCCESS if user.approved else WARNING)
        identifier = user.email if "@" in user.email else ""
        if user.login_id:
            identifier = f"{identifier} | usuario: {user.login_id}" if identifier else f"usuario: {user.login_id}"
        title = identifier or user.email or user.id
        if user.display_name:
            title = f"{user.display_name} | {title}"
        ctk.CTkLabel(
            row,
            text=title,
            text_color=TEXT_PRIMARY,
            font=ctk.CTkFont(size=13, weight="bold"),
            anchor="w",
        ).grid(row=0, column=0, padx=12, pady=(10, 2), sticky="ew")
        ctk.CTkLabel(
            row,
            text=f"{state} | rol {user.role}",
            text_color=state_color,
            anchor="w",
        ).grid(row=1, column=0, padx=12, pady=(0, 10), sticky="ew")

        video_text, video_color = self._weekly_video_text(user)
        ctk.CTkLabel(
            row,
            text=video_text,
            text_color=video_color,
            anchor="w",
            justify="left",
        ).grid(row=2, column=0, padx=12, pady=(0, 10), sticky="ew")

        login_frame = ctk.CTkFrame(row, fg_color="transparent")
        login_frame.grid(row=3, column=0, padx=12, pady=(0, 10), sticky="ew")
        login_frame.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(
            login_frame,
            text="Usuario",
            text_color=TEXT_MUTED,
            font=ctk.CTkFont(size=11, weight="bold"),
        ).grid(row=0, column=0, padx=(0, 8), sticky="w")
        login_entry = ctk.CTkEntry(
            login_frame,
            height=30,
            corner_radius=8,
            placeholder_text="ej: salem",
        )
        login_entry.insert(0, user.login_id)
        login_entry.grid(row=0, column=1, sticky="ew")
        ctk.CTkButton(
            login_frame,
            text="Guardar",
            command=lambda current=user, entry=login_entry: self._run_login_id_update(current, entry.get()),
            height=30,
            width=78,
            corner_radius=8,
            fg_color=NEUTRAL_BUTTON,
            hover_color=NEUTRAL_BUTTON_HOVER,
            text_color=TEXT_PRIMARY,
        ).grid(row=0, column=2, padx=(8, 0), sticky="e")

        actions = ctk.CTkFrame(row, fg_color="transparent")
        actions.grid(row=0, column=1, rowspan=4, padx=12, pady=10, sticky="e")

        ctk.CTkButton(
            actions,
            text="Aprobar",
            command=lambda current=user: self._run_action("approve", current),
            height=32,
            width=86,
            corner_radius=10,
            fg_color=ACCENT,
            hover_color=ACCENT_HOVER,
            state="disabled" if user.approved and not user.disabled else "normal",
        ).grid(row=0, column=0, padx=(0, 8))
        ctk.CTkButton(
            actions,
            text="Deshabilitar" if not user.disabled else "Habilitar",
            command=lambda current=user: self._run_action("disable" if not user.disabled else "enable", current),
            height=32,
            width=104,
            corner_radius=10,
            fg_color=NEUTRAL_BUTTON,
            hover_color=NEUTRAL_BUTTON_HOVER,
            text_color=TEXT_PRIMARY,
        ).grid(row=0, column=1, padx=(0, 0))
        has_video = user.weekly_video is not None
        video_accepted = has_video and user.weekly_video.status == "accepted"
        video_rejected = has_video and user.weekly_video.status == "rejected"
        ctk.CTkButton(
            actions,
            text="Aprobar video",
            command=lambda current=user: self._run_action("approve_video", current),
            height=32,
            width=104,
            corner_radius=10,
            fg_color=ACCENT,
            hover_color=ACCENT_HOVER,
            state="disabled" if not has_video or video_accepted else "normal",
        ).grid(row=1, column=0, padx=(0, 8), pady=(8, 0))
        ctk.CTkButton(
            actions,
            text="Rechazar video",
            command=lambda current=user: self._run_action("reject_video", current),
            height=32,
            width=104,
            corner_radius=10,
            fg_color=NEUTRAL_BUTTON,
            hover_color=NEUTRAL_BUTTON_HOVER,
            text_color=TEXT_PRIMARY,
            state="disabled" if not has_video or video_rejected else "normal",
        ).grid(row=1, column=1, pady=(8, 0))
        return row

    def _run_login_id_update(self, user: UserAccessRecord, login_id: str) -> None:
        self.status_label.configure(text="Guardando usuario...", text_color=TEXT_MUTED)
        threading.Thread(
            target=lambda: self._login_id_worker(user, login_id),
            daemon=True,
        ).start()

    def _login_id_worker(self, user: UserAccessRecord, login_id: str) -> None:
        try:
            self._service.update_login_id(user.id, login_id)
            self.after(0, self.refresh)
        except Exception as exc:
            self.after(0, lambda error=exc: self._show_error(error))

    def _run_action(self, action: str, user: UserAccessRecord) -> None:
        self.status_label.configure(text="Actualizando usuario...", text_color=TEXT_MUTED)
        threading.Thread(target=lambda: self._action_worker(action, user), daemon=True).start()

    def _action_worker(self, action: str, user: UserAccessRecord) -> None:
        try:
            if action == "approve":
                self._service.approve_user(user.id)
            elif action == "disable":
                self._service.disable_user(user.id)
            elif action == "approve_video":
                self._service.approve_weekly_video(user.id)
            elif action == "reject_video":
                self._service.reject_weekly_video(user.id)
            else:
                self._service.enable_user(user.id)
            self.after(0, self.refresh)
        except Exception as exc:
            self.after(0, lambda error=exc: self._show_error(error))

    def _show_error(self, exc: Exception) -> None:
        self._is_loading = False
        self.refresh_button.configure(state="normal", text="Refrescar")
        self.status_label.configure(text=f"No se pudo cargar usuarios: {exc}", text_color=ERROR)

    @staticmethod
    def _weekly_video_text(user: UserAccessRecord) -> tuple[str, object]:
        video = user.weekly_video
        if video is None:
            return "Video semanal: no cargado | fotos extraidas: 0", WARNING
        color = SUCCESS if video.status == "accepted" else (ERROR if video.status == "rejected" else WARNING)
        text = (
            f"Video semanal: {video.status} | "
            f"extraidas {video.frames_extracted} | "
            f"candidatas {video.candidates_uploaded} | "
            f"fotos aprobadas {video.approved_count} | "
            f"rechazadas {video.rejected_count}"
        )
        if video.original_video_name:
            text = f"{text} | {video.original_video_name}"
        return text, color
