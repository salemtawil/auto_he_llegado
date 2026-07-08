from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

from config.settings import Settings, get_settings
from services.auth_context import AuthSession, set_current_session
from storage.supabase_client import SupabaseClientProvider


@dataclass(frozen=True)
class AccessSnapshot:
    can_use_app: bool
    needs_weekly_video: bool
    reason: str
    week_start: date
    profile: dict
    latest_batch: dict | None = None


class AccessService:
    ACTIVE_BATCH_STATUSES = {"processing", "pending_review", "accepted", "reviewed"}

    def __init__(
        self,
        client_provider: SupabaseClientProvider | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._client_provider = client_provider or SupabaseClientProvider(self._settings)

    def sign_in(self, *, identifier: str | None = None, email: str | None = None, password: str) -> AuthSession:
        normalized_identifier = self._normalize_identifier(identifier or email or "")
        if not normalized_identifier or not password:
            raise ValueError("Ingresa usuario/email y contrasena.")
        login_email = self._resolve_login_email(normalized_identifier)
        response = self._client_provider.client.auth.sign_in_with_password(
            {"email": login_email, "password": password}
        )
        user = getattr(response, "user", None)
        session = getattr(response, "session", None)
        if user is None or session is None:
            raise RuntimeError("Supabase no devolvio una sesion valida.")

        user_id = str(getattr(user, "id", "") or "")
        access_token = str(getattr(session, "access_token", "") or "")
        refresh_token = str(getattr(session, "refresh_token", "") or "")
        profile = self.get_profile(user_id=user_id)
        auth_session = AuthSession(
            user_id=user_id,
            email=self._profile_identifier(profile, normalized_identifier),
            display_name=str(profile.get("display_name") or ""),
            role=str(profile.get("role") or "member"),
            approved=bool(profile.get("approved")),
            disabled=bool(profile.get("disabled")),
            access_token=access_token,
            refresh_token=refresh_token,
        )
        set_current_session(auth_session)
        return auth_session

    def sign_out(self) -> None:
        try:
            self._client_provider.client.auth.sign_out()
        finally:
            set_current_session(None)

    def get_profile(self, *, user_id: str) -> dict:
        rows = self._client_provider.execute(
            self._client_provider.client.table(self._settings.supabase_profiles_table)
            .select("*")
            .eq("id", user_id)
            .limit(1)
        )
        if not rows:
            raise RuntimeError("Tu usuario no tiene perfil de acceso. Pide aprobacion al admin.")
        return dict(rows[0])

    def get_access_snapshot(self, session: AuthSession) -> AccessSnapshot:
        profile = self.get_profile(user_id=session.user_id)
        week_start = self.current_week_start()
        if bool(profile.get("disabled")):
            return AccessSnapshot(
                can_use_app=False,
                needs_weekly_video=False,
                reason="Tu acceso esta deshabilitado.",
                week_start=week_start,
                profile=profile,
            )
        if not bool(profile.get("approved")):
            return AccessSnapshot(
                can_use_app=False,
                needs_weekly_video=False,
                reason="Tu usuario todavia no esta aprobado.",
                week_start=week_start,
                profile=profile,
            )
        if str(profile.get("role") or "").strip().lower() == "admin":
            return AccessSnapshot(
                can_use_app=True,
                needs_weekly_video=False,
                reason="Acceso admin aprobado.",
                week_start=week_start,
                profile=profile,
            )

        latest_batch = self._latest_weekly_batch(session.user_id, week_start)
        latest_status = str((latest_batch or {}).get("status") or "").strip().lower()
        if latest_status == "rejected":
            reason = "Acceso aprobado. Puedes subir un video nuevo cuando quieras."
        elif latest_status in self.ACTIVE_BATCH_STATUSES:
            reason = "Acceso aprobado. Video semanal recibido."
        else:
            reason = "Acceso aprobado. Puedes subir tu video cuando quieras."
        return AccessSnapshot(
            can_use_app=True,
            needs_weekly_video=False,
            reason=reason,
            week_start=week_start,
            profile=profile,
            latest_batch=latest_batch,
        )

    def _latest_weekly_batch(self, user_id: str, week_start: date) -> dict | None:
        rows = self._client_provider.execute(
            self._client_provider.client.table(self._settings.supabase_photo_batches_table)
            .select("*")
            .eq("user_id", user_id)
            .eq("week_start", week_start.isoformat())
            .order("created_at", desc=True)
            .limit(1)
        )
        return dict(rows[0]) if rows else None

    @staticmethod
    def current_week_start(now: datetime | None = None) -> date:
        current = now or datetime.now(timezone.utc)
        current_date = current.date()
        return current_date - timedelta(days=current_date.weekday())

    @staticmethod
    def _normalize_identifier(identifier: str) -> str:
        value = identifier.strip()
        if "@" in value:
            return value.lower()
        return value.lower()

    def _resolve_login_email(self, identifier: str) -> str:
        if "@" in identifier:
            return identifier.lower()
        rows = self._client_provider.execute(
            self._client_provider.client.rpc(
                "resolve_login_identifier",
                {"p_identifier": identifier},
            )
        )
        if not rows:
            raise RuntimeError("Usuario no encontrado.")
        email = str(rows[0].get("email") or "").strip().lower()
        if not email:
            raise RuntimeError("Este usuario no tiene email de login configurado.")
        return email

    @staticmethod
    def _profile_identifier(profile: dict, fallback: str) -> str:
        login_id = str(profile.get("login_id") or "").strip()
        if login_id:
            return login_id
        email = str(profile.get("email") or "").strip()
        if "@" in email:
            return email
        return fallback or email
