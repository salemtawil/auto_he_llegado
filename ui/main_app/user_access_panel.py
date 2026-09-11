from __future__ import annotations

import threading
import tkinter as tk

import customtkinter as ctk

from services.user_access_admin_service import UserAccessAdminService, UserAccessRecord
from services.access_service import VideoRequirementPolicy
from services.photo_pool_policy_service import PhotoPoolPolicy
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
        self._pool_bucket_values: list[str] = []
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)
        self._build_header()
        self._build_controls()
        self._build_list()
        self.refresh()

    def _build_header(self) -> None:
        header = ctk.CTkFrame(
            self,
            fg_color=CARD_BG,
            corner_radius=12,
            border_width=1,
            border_color=BORDER,
        )
        header.grid(row=0, column=0, pady=(0, 8), sticky="ew")
        header.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            header,
            text="Usuarios",
            font=ctk.CTkFont(size=18, weight="bold"),
            text_color=TEXT_PRIMARY,
        ).grid(row=0, column=0, padx=14, pady=(12, 2), sticky="w")

        self.status_label = ctk.CTkLabel(
            header,
            text="Cargando usuarios...",
            text_color=TEXT_MUTED,
            font=ctk.CTkFont(size=12),
            justify="left",
        )
        self.status_label.grid(row=1, column=0, padx=14, pady=(0, 12), sticky="w")

        self.refresh_button = ctk.CTkButton(
            header,
            text="Refrescar",
            command=self.refresh,
            height=34,
            width=104,
            corner_radius=10,
            font=ctk.CTkFont(size=12),
            fg_color=NEUTRAL_BUTTON,
            hover_color=NEUTRAL_BUTTON_HOVER,
            text_color=TEXT_PRIMARY,
        )
        self.refresh_button.grid(row=0, column=1, rowspan=2, padx=14, pady=12, sticky="e")

    def _build_controls(self) -> None:
        self.controls_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.controls_frame.grid(row=1, column=0, pady=(0, 8), sticky="ew")
        self.controls_frame.grid_columnconfigure(0, weight=1, uniform="settings")
        self.controls_frame.grid_columnconfigure(1, weight=1, uniform="settings")
        self._build_policy_panel()
        self._build_pool_policy_panel()

    def _build_policy_panel(self) -> None:
        panel = ctk.CTkFrame(
            self.controls_frame,
            fg_color=CARD_BG,
            corner_radius=12,
            border_width=1,
            border_color=BORDER,
        )
        panel.grid(row=0, column=0, padx=(0, 6), sticky="nsew")
        panel.grid_columnconfigure(3, weight=1)
        ctk.CTkLabel(
            panel,
            text="Politica de video",
            font=ctk.CTkFont(size=15, weight="bold"),
            text_color=TEXT_PRIMARY,
        ).grid(row=0, column=0, padx=14, pady=(10, 2), sticky="w")
        self.policy_status_label = ctk.CTkLabel(
            panel,
            text="Cargando politica...",
            text_color=TEXT_MUTED,
            font=ctk.CTkFont(size=12),
            anchor="w",
        )
        self.policy_status_label.grid(row=1, column=0, columnspan=5, padx=14, pady=(0, 8), sticky="ew")
        self.video_required_var = tk.BooleanVar(value=True)
        self.video_required_switch = ctk.CTkSwitch(
            panel,
            text="Exigir video",
            variable=self.video_required_var,
            progress_color=ACCENT,
            button_color=ACCENT,
            button_hover_color=ACCENT_HOVER,
            text_color=TEXT_PRIMARY,
            font=ctk.CTkFont(size=12),
        )
        self.video_required_switch.grid(row=2, column=0, padx=14, pady=(0, 12), sticky="w")
        self.video_duration_based_var = tk.BooleanVar(value=False)
        self.video_duration_based_switch = ctk.CTkSwitch(
            panel,
            text="Por duracion",
            variable=self.video_duration_based_var,
            command=self._sync_duration_policy_controls,
            progress_color=ACCENT,
            button_color=ACCENT,
            button_hover_color=ACCENT_HOVER,
            text_color=TEXT_PRIMARY,
            font=ctk.CTkFont(size=12),
        )
        self.video_duration_based_switch.grid(row=3, column=0, padx=14, pady=(0, 12), sticky="w")
        ctk.CTkLabel(
            panel,
            text="Menor a",
            text_color=TEXT_MUTED,
            font=ctk.CTkFont(size=12),
        ).grid(row=2, column=1, padx=(6, 5), pady=(0, 6), sticky="e")
        self.video_threshold_entry = ctk.CTkEntry(
            panel,
            height=30,
            width=58,
            corner_radius=9,
            font=ctk.CTkFont(size=12),
            placeholder_text="25",
        )
        self.video_threshold_entry.grid(row=2, column=2, pady=(0, 6), sticky="w")
        ctk.CTkLabel(
            panel,
            text="s: cada",
            text_color=TEXT_MUTED,
            font=ctk.CTkFont(size=12),
        ).grid(row=2, column=3, padx=(5, 5), pady=(0, 6), sticky="w")
        self.video_days_entry = ctk.CTkEntry(
            panel,
            height=30,
            width=58,
            corner_radius=9,
            font=ctk.CTkFont(size=12),
            placeholder_text="7",
        )
        self.video_days_entry.grid(row=2, column=4, pady=(0, 6), sticky="w")
        ctk.CTkLabel(
            panel,
            text="dias",
            text_color=TEXT_MUTED,
            font=ctk.CTkFont(size=12),
        ).grid(row=2, column=5, padx=(5, 8), pady=(0, 6), sticky="w")
        ctk.CTkLabel(
            panel,
            text="Desde ese tiempo: cada",
            text_color=TEXT_MUTED,
            font=ctk.CTkFont(size=12),
        ).grid(row=3, column=1, columnspan=3, padx=(6, 5), pady=(0, 12), sticky="e")
        self.video_long_days_entry = ctk.CTkEntry(
            panel,
            height=30,
            width=58,
            corner_radius=9,
            font=ctk.CTkFont(size=12),
            placeholder_text="14",
        )
        self.video_long_days_entry.grid(row=3, column=4, pady=(0, 12), sticky="w")
        ctk.CTkLabel(
            panel,
            text="dias",
            text_color=TEXT_MUTED,
            font=ctk.CTkFont(size=12),
        ).grid(row=3, column=5, padx=(5, 8), pady=(0, 12), sticky="w")
        self.save_policy_button = ctk.CTkButton(
            panel,
            text="Guardar",
            command=self._save_video_policy,
            height=32,
            width=96,
            corner_radius=9,
            font=ctk.CTkFont(size=12),
            fg_color=ACCENT,
            hover_color=ACCENT_HOVER,
        )
        self.save_policy_button.grid(row=2, column=6, rowspan=2, padx=14, pady=(0, 12), sticky="e")

    def _build_pool_policy_panel(self) -> None:
        panel = ctk.CTkFrame(
            self.controls_frame,
            fg_color=CARD_BG,
            corner_radius=14,
            border_width=1,
            border_color=BORDER,
        )
        panel.grid(row=0, column=1, padx=(6, 0), sticky="nsew")
        panel.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(
            panel,
            text="Pool activo",
            font=ctk.CTkFont(size=15, weight="bold"),
            text_color=TEXT_PRIMARY,
        ).grid(row=0, column=0, padx=14, pady=(10, 2), sticky="w")
        self.pool_policy_status_label = ctk.CTkLabel(
            panel,
            text="Cargando pool activo...",
            text_color=TEXT_MUTED,
            font=ctk.CTkFont(size=12),
            anchor="w",
        )
        self.pool_policy_status_label.grid(row=1, column=0, columnspan=3, padx=14, pady=(0, 8), sticky="ew")
        ctk.CTkLabel(
            panel,
            text="Bucket",
            text_color=TEXT_MUTED,
            font=ctk.CTkFont(size=12),
        ).grid(row=2, column=0, padx=14, pady=(0, 12), sticky="w")
        self.pool_bucket_var = tk.StringVar(value="")
        self.pool_bucket_menu = ctk.CTkOptionMenu(
            panel,
            values=["Cargando..."],
            variable=self.pool_bucket_var,
            height=32,
            corner_radius=9,
            font=ctk.CTkFont(size=12),
            dropdown_font=ctk.CTkFont(size=12),
            fg_color=NEUTRAL_BUTTON,
            button_color=ACCENT,
            button_hover_color=ACCENT_HOVER,
            dropdown_fg_color=CARD_BG,
            dropdown_hover_color=NEUTRAL_BUTTON_HOVER,
            text_color=TEXT_PRIMARY,
        )
        self.pool_bucket_menu.grid(row=2, column=1, padx=(0, 10), pady=(0, 12), sticky="ew")
        self.save_pool_policy_button = ctk.CTkButton(
            panel,
            text="Guardar",
            command=self._save_pool_policy,
            height=32,
            width=96,
            corner_radius=9,
            font=ctk.CTkFont(size=12),
            fg_color=ACCENT,
            hover_color=ACCENT_HOVER,
        )
        self.save_pool_policy_button.grid(row=2, column=2, padx=14, pady=(0, 12), sticky="e")

    def _build_list(self) -> None:
        self.scroll = ctk.CTkScrollableFrame(
            self,
            fg_color=CARD_ALT_BG,
            corner_radius=12,
            border_width=1,
            border_color=BORDER,
        )
        self.scroll.grid(row=2, column=0, sticky="nsew")
        self.scroll.grid_columnconfigure(0, weight=1)

    def refresh(self) -> None:
        if self._is_loading:
            return
        self._is_loading = True
        self.refresh_button.configure(state="disabled", text="Cargando...")
        threading.Thread(target=self._refresh_worker, daemon=True).start()

    def _refresh_worker(self) -> None:
        try:
            policy = self._service.get_video_requirement_policy()
            pool_policy = self._service.get_photo_pool_policy()
            pool_buckets = self._service.list_photo_pool_buckets()
            users = self._service.list_users()
            self.after(0, lambda: self._apply_refresh(users, policy, pool_policy, pool_buckets))
        except Exception as exc:
            self.after(0, lambda error=exc: self._show_error(error))

    def _apply_refresh(
        self,
        users: list[UserAccessRecord],
        policy: VideoRequirementPolicy,
        pool_policy: PhotoPoolPolicy,
        pool_buckets: list[str],
    ) -> None:
        self._apply_policy(policy)
        self._apply_pool_policy(pool_policy, pool_buckets)
        self._apply_users(users)

    def _apply_policy(self, policy: VideoRequirementPolicy) -> None:
        self.video_required_var.set(policy.enabled)
        self.video_duration_based_var.set(policy.duration_based)
        self.video_days_entry.delete(0, "end")
        self.video_days_entry.insert(0, str(policy.days))
        self.video_long_days_entry.delete(0, "end")
        self.video_long_days_entry.insert(0, str(policy.long_video_days))
        self.video_threshold_entry.delete(0, "end")
        threshold = policy.long_video_min_duration_seconds
        threshold_text = f"{threshold:.0f}" if float(threshold).is_integer() else f"{threshold:.1f}"
        self.video_threshold_entry.insert(0, threshold_text)
        state_text = "activo" if policy.enabled else "desactivado"
        mode_text = (
            f"Videos cortos cada {policy.days} dia(s); videos de {threshold_text}s o mas cada {policy.long_video_days}."
            if policy.duration_based
            else f"Frecuencia fija: cada {policy.days} dia(s), sin importar la duracion."
        )
        self.policy_status_label.configure(
            text=f"Requisito {state_text}. {mode_text}",
            text_color=SUCCESS if policy.enabled else WARNING,
        )
        self._sync_duration_policy_controls()

    def _apply_pool_policy(self, policy: PhotoPoolPolicy, buckets: list[str] | None = None) -> None:
        values = self._bucket_menu_values(policy.bucket, buckets or self._pool_bucket_values)
        self._pool_bucket_values = values
        self.pool_bucket_menu.configure(values=values)
        self.pool_bucket_var.set(policy.bucket)
        self.pool_policy_status_label.configure(
            text=f"Activo: {policy.bucket}",
            text_color=SUCCESS if policy.source == "supabase" else WARNING,
        )

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
            ctk.CTkLabel(
                self.scroll,
                text="No hay perfiles registrados.",
                text_color=TEXT_MUTED,
                font=ctk.CTkFont(size=12),
            ).grid(
                row=0,
                column=0,
                padx=12,
                pady=12,
                sticky="w",
            )
            return
        for row, user in enumerate(users):
            self._user_row(user).grid(row=row, column=0, padx=6, pady=5, sticky="ew")

    def _user_row(self, user: UserAccessRecord) -> ctk.CTkFrame:
        row = ctk.CTkFrame(
            self.scroll,
            fg_color=CARD_BG,
            corner_radius=10,
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
            font=ctk.CTkFont(size=12, weight="bold"),
            anchor="w",
        ).grid(row=0, column=0, padx=10, pady=(8, 1), sticky="ew")
        ctk.CTkLabel(
            row,
            text=f"{state} | rol {user.role}",
            text_color=state_color,
            font=ctk.CTkFont(size=12),
            anchor="w",
        ).grid(row=1, column=0, padx=10, pady=(0, 7), sticky="ew")

        video_text, video_color = self._weekly_video_text(user)
        ctk.CTkLabel(
            row,
            text=video_text,
            text_color=video_color,
            font=ctk.CTkFont(size=12),
            anchor="w",
            justify="left",
        ).grid(row=2, column=0, padx=10, pady=(0, 7), sticky="ew")

        login_frame = ctk.CTkFrame(row, fg_color="transparent")
        login_frame.grid(row=3, column=0, padx=10, pady=(0, 8), sticky="ew")
        login_frame.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(
            login_frame,
            text="Usuario",
            text_color=TEXT_MUTED,
            font=ctk.CTkFont(size=11, weight="bold"),
        ).grid(row=0, column=0, padx=(0, 7), sticky="w")
        login_entry = ctk.CTkEntry(
            login_frame,
            height=28,
            corner_radius=8,
            font=ctk.CTkFont(size=12),
            placeholder_text="ej: salem",
        )
        login_entry.insert(0, user.login_id)
        login_entry.grid(row=0, column=1, sticky="ew")
        ctk.CTkButton(
            login_frame,
            text="Guardar",
            command=lambda current=user, entry=login_entry: self._run_login_id_update(current, entry.get()),
            height=28,
            width=72,
            corner_radius=8,
            font=ctk.CTkFont(size=12),
            fg_color=NEUTRAL_BUTTON,
            hover_color=NEUTRAL_BUTTON_HOVER,
            text_color=TEXT_PRIMARY,
        ).grid(row=0, column=2, padx=(7, 0), sticky="e")

        actions = ctk.CTkFrame(row, fg_color="transparent")
        actions.grid(row=0, column=1, rowspan=4, padx=10, pady=8, sticky="e")

        ctk.CTkButton(
            actions,
            text="Aprobar",
            command=lambda current=user: self._run_action("approve", current),
            height=30,
            width=82,
            corner_radius=9,
            font=ctk.CTkFont(size=12),
            fg_color=ACCENT,
            hover_color=ACCENT_HOVER,
            state="disabled" if user.approved and not user.disabled else "normal",
        ).grid(row=0, column=0, padx=(0, 8))
        ctk.CTkButton(
            actions,
            text="Deshabilitar" if not user.disabled else "Habilitar",
            command=lambda current=user: self._run_action("disable" if not user.disabled else "enable", current),
            height=30,
            width=98,
            corner_radius=9,
            font=ctk.CTkFont(size=12),
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
            height=30,
            width=98,
            corner_radius=9,
            font=ctk.CTkFont(size=12),
            fg_color=ACCENT,
            hover_color=ACCENT_HOVER,
            state="disabled" if not has_video or video_accepted else "normal",
        ).grid(row=1, column=0, padx=(0, 8), pady=(8, 0))
        ctk.CTkButton(
            actions,
            text="Rechazar video",
            command=lambda current=user: self._run_action("reject_video", current),
            height=30,
            width=98,
            corner_radius=9,
            font=ctk.CTkFont(size=12),
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

    def _save_video_policy(self) -> None:
        raw_days = self.video_days_entry.get().strip()
        raw_long_days = self.video_long_days_entry.get().strip()
        raw_threshold = self.video_threshold_entry.get().strip()
        try:
            days = int(raw_days)
            long_days = int(raw_long_days)
            threshold = float(raw_threshold.replace(",", "."))
        except ValueError:
            self.policy_status_label.configure(text="Ingresa dias y segundos validos.", text_color=ERROR)
            return
        enabled = bool(self.video_required_var.get())
        duration_based = bool(self.video_duration_based_var.get())
        self.save_policy_button.configure(state="disabled", text="Guardando...")
        self.policy_status_label.configure(text="Guardando politica en Supabase...", text_color=TEXT_MUTED)
        threading.Thread(
            target=lambda: self._save_video_policy_worker(enabled, days, duration_based, long_days, threshold),
            daemon=True,
        ).start()

    def _save_video_policy_worker(
        self,
        enabled: bool,
        days: int,
        duration_based: bool,
        long_days: int,
        threshold: float,
    ) -> None:
        try:
            policy = self._service.update_video_requirement_policy(
                enabled=enabled,
                days=days,
                duration_based=duration_based,
                long_video_days=long_days,
                long_video_min_duration_seconds=threshold,
            )
            self.after(0, lambda current=policy: self._finish_video_policy_save(current))
        except Exception as exc:
            self.after(0, lambda error=exc: self._finish_video_policy_error(error))

    def _finish_video_policy_save(self, policy: VideoRequirementPolicy) -> None:
        self.save_policy_button.configure(state="normal", text="Guardar")
        self._apply_policy(policy)
        self.refresh()

    def _finish_video_policy_error(self, exc: Exception) -> None:
        self.save_policy_button.configure(state="normal", text="Guardar")
        self.policy_status_label.configure(text=f"No se pudo guardar la politica: {exc}", text_color=ERROR)

    def _sync_duration_policy_controls(self) -> None:
        state = "normal" if bool(self.video_duration_based_var.get()) else "disabled"
        for widget in (self.video_threshold_entry, self.video_long_days_entry):
            widget.configure(state=state)

    def _save_pool_policy(self) -> None:
        bucket = self.pool_bucket_var.get().strip()
        if not bucket:
            self.pool_policy_status_label.configure(text="Selecciona un bucket valido.", text_color=ERROR)
            return
        self.save_pool_policy_button.configure(state="disabled", text="Guardando...")
        self.pool_policy_status_label.configure(text="Guardando pool activo en Supabase...", text_color=TEXT_MUTED)
        threading.Thread(target=lambda: self._save_pool_policy_worker(bucket), daemon=True).start()

    def _save_pool_policy_worker(self, bucket: str) -> None:
        try:
            policy = self._service.update_photo_pool_policy(bucket=bucket)
            self.after(0, lambda current=policy: self._finish_pool_policy_save(current))
        except Exception as exc:
            self.after(0, lambda error=exc: self._finish_pool_policy_error(error))

    def _finish_pool_policy_save(self, policy: PhotoPoolPolicy) -> None:
        self.save_pool_policy_button.configure(state="normal", text="Guardar")
        self._apply_pool_policy(policy)
        self.refresh()

    def _finish_pool_policy_error(self, exc: Exception) -> None:
        self.save_pool_policy_button.configure(state="normal", text="Guardar")
        self.pool_policy_status_label.configure(text=f"No se pudo guardar el pool: {exc}", text_color=ERROR)

    def _show_error(self, exc: Exception) -> None:
        self._is_loading = False
        self.refresh_button.configure(state="normal", text="Refrescar")
        self.status_label.configure(text=f"No se pudo cargar usuarios: {exc}", text_color=ERROR)

    @staticmethod
    def _bucket_menu_values(active_bucket: str, buckets: list[str]) -> list[str]:
        values: list[str] = []
        for bucket in [active_bucket, *buckets]:
            normalized = str(bucket or "").strip()
            if normalized and normalized not in values:
                values.append(normalized)
        return values or ["photo-pool"]

    @staticmethod
    def _weekly_video_text(user: UserAccessRecord) -> tuple[str, object]:
        video = user.weekly_video
        if video is None:
            return "Video requerido: no cargado | fotos extraidas: 0", WARNING
        color = SUCCESS if video.status == "accepted" else (ERROR if video.status == "rejected" else WARNING)
        text = (
            f"Video requerido: {video.status} | "
            f"extraidas {video.frames_extracted} | "
            f"candidatas {video.candidates_uploaded} | "
            f"fotos aprobadas {video.approved_count} | "
            f"rechazadas {video.rejected_count}"
        )
        if video.original_video_name:
            text = f"{text} | {video.original_video_name}"
        return text, color
