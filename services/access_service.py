from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone

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


@dataclass(frozen=True)
class RegistrationResult:
    user_id: str
    email: str
    login_id: str
    display_name: str
    needs_email_confirmation: bool


@dataclass(frozen=True)
class VideoRequirementPolicy:
    enabled: bool
    days: int
    duration_based: bool = False
    long_video_days: int = 14
    long_video_min_duration_seconds: float = 25.0
    source: str = "local"

    @property
    def max_days(self) -> int:
        if not self.duration_based:
            return self.days
        return max(self.days, self.long_video_days)

    def days_for_duration(self, duration_seconds) -> int:
        if not self.duration_based:
            return self.days
        try:
            duration = float(duration_seconds or 0.0)
        except (TypeError, ValueError):
            duration = 0.0
        if duration >= max(float(self.long_video_min_duration_seconds), 0.0):
            return self.long_video_days
        return self.days


class AccessService:
    ACTIVE_BATCH_STATUSES = {"processing", "pending_review", "accepted", "reviewed"}
    _LOGIN_ID_PATTERN = re.compile(r"^[a-z0-9._-]{3,32}$")
    _DEFAULT_VIDEO_REQUIREMENT_DAYS = 7

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

    def register_member(
        self,
        *,
        login_id: str,
        email: str,
        password: str,
        display_name: str = "",
    ) -> RegistrationResult:
        normalized_login_id = self._normalize_identifier(login_id)
        normalized_email = email.strip().lower()
        clean_display_name = display_name.strip()
        if not self._LOGIN_ID_PATTERN.match(normalized_login_id):
            raise ValueError("El usuario debe tener 3 a 32 caracteres: letras, numeros, punto, guion o guion bajo.")
        if "@" not in normalized_email or "." not in normalized_email.rsplit("@", 1)[-1]:
            raise ValueError("Ingresa un email valido.")
        if len(password) < 6:
            raise ValueError("La contrasena debe tener al menos 6 caracteres.")
        if self._identifier_exists(normalized_login_id):
            raise RuntimeError("Ese usuario ya existe.")
        if self._identifier_exists(normalized_email):
            raise RuntimeError("Ese email ya esta registrado.")

        response = self._client_provider.client.auth.sign_up(
            {
                "email": normalized_email,
                "password": password,
                "options": {
                    "data": {
                        "login_id": normalized_login_id,
                        "display_name": clean_display_name,
                    }
                },
            }
        )
        user = getattr(response, "user", None)
        if user is None:
            raise RuntimeError("Supabase no devolvio el usuario creado.")
        user_id = str(getattr(user, "id", "") or "")
        if not user_id:
            raise RuntimeError("Supabase no devolvio un id de usuario valido.")
        return RegistrationResult(
            user_id=user_id,
            email=normalized_email,
            login_id=normalized_login_id,
            display_name=clean_display_name,
            needs_email_confirmation=getattr(response, "session", None) is None,
        )

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
        policy = self.get_video_requirement_policy()
        period_start = self.current_requirement_start(policy.max_days)
        if bool(profile.get("disabled")):
            return AccessSnapshot(
                can_use_app=False,
                needs_weekly_video=False,
                reason="Tu acceso esta deshabilitado.",
                week_start=period_start,
                profile=profile,
            )
        if not bool(profile.get("approved")):
            return AccessSnapshot(
                can_use_app=False,
                needs_weekly_video=False,
                reason="Tu usuario todavia no esta aprobado.",
                week_start=period_start,
                profile=profile,
            )
        if str(profile.get("role") or "").strip().lower() == "admin":
            return AccessSnapshot(
                can_use_app=True,
                needs_weekly_video=False,
                reason="Acceso admin aprobado.",
                week_start=period_start,
                profile=profile,
            )
        if not policy.enabled:
            return AccessSnapshot(
                can_use_app=True,
                needs_weekly_video=False,
                reason="Acceso aprobado. Video no requerido actualmente.",
                week_start=period_start,
                profile=profile,
            )

        latest_batch = self._latest_required_video_batch(session.user_id, period_start)
        latest_status = str((latest_batch or {}).get("status") or "").strip().lower()
        if latest_status == "rejected":
            return AccessSnapshot(
                can_use_app=False,
                needs_weekly_video=True,
                reason="Tu video requerido fue rechazado. Sube un video nuevo para activar el acceso.",
                week_start=period_start,
                profile=profile,
                latest_batch=latest_batch,
            )
        elif latest_status in self.ACTIVE_BATCH_STATUSES:
            effective_days = policy.days_for_duration((latest_batch or {}).get("video_duration_seconds"))
            if self._batch_is_within_days(latest_batch, effective_days):
                duration_text = self._duration_policy_text(policy, effective_days)
                return AccessSnapshot(
                    can_use_app=True,
                    needs_weekly_video=False,
                    reason=f"Acceso aprobado. Video recibido dentro de los ultimos {effective_days} dias{duration_text}.",
                    week_start=period_start,
                    profile=profile,
                    latest_batch=latest_batch,
                )
            return AccessSnapshot(
                can_use_app=False,
                needs_weekly_video=True,
                reason=f"Para usar la app debes subir un video cada {policy.days} dias.",
                week_start=period_start,
                profile=profile,
                latest_batch=latest_batch,
            )
        return AccessSnapshot(
            can_use_app=False,
            needs_weekly_video=True,
            reason=f"Para usar la app debes subir un video cada {policy.days} dias.",
            week_start=period_start,
            profile=profile,
            latest_batch=latest_batch,
        )

    def get_video_requirement_policy(self) -> VideoRequirementPolicy:
        try:
            rows = self._client_provider.execute(
                self._client_provider.client.rpc("get_video_requirement_policy", {})
            )
        except Exception:
            return VideoRequirementPolicy(
                enabled=True,
                days=self._normalize_requirement_days(
                    getattr(self._settings, "video_requirement_days", self._DEFAULT_VIDEO_REQUIREMENT_DAYS)
                ),
                source="local",
            )
        row = dict(rows[0]) if rows else {}
        enabled = bool(row.get("enabled", True))
        days = self._normalize_requirement_days(row.get("days"))
        duration_based = bool(row.get("duration_based", False))
        long_video_days = self._normalize_requirement_days(row.get("long_video_days") or row.get("long_days") or days)
        long_video_min_duration_seconds = self._normalize_duration_threshold(
            row.get("long_video_min_duration_seconds") or row.get("long_min_duration_seconds")
        )
        return VideoRequirementPolicy(
            enabled=enabled,
            days=days,
            duration_based=duration_based,
            long_video_days=long_video_days,
            long_video_min_duration_seconds=long_video_min_duration_seconds,
            source="supabase",
        )

    def _latest_required_video_batch(self, user_id: str, period_start: date) -> dict | None:
        cutoff = datetime.combine(period_start, time.min, tzinfo=timezone.utc).isoformat()
        rows = self._client_provider.execute(
            self._client_provider.client.table(self._settings.supabase_photo_batches_table)
            .select("*")
            .eq("user_id", user_id)
            .gte("created_at", cutoff)
            .order("created_at", desc=True)
            .limit(1)
        )
        return dict(rows[0]) if rows else None

    @staticmethod
    def current_week_start(now: datetime | None = None) -> date:
        current = now or datetime.now(timezone.utc)
        current_date = current.date()
        return current_date - timedelta(days=current_date.weekday())

    @classmethod
    def current_requirement_start(cls, days: int, now: datetime | None = None) -> date:
        current = now or datetime.now(timezone.utc)
        return current.date() - timedelta(days=cls._normalize_requirement_days(days))

    @classmethod
    def _normalize_requirement_days(cls, value) -> int:
        try:
            days = int(value)
        except (TypeError, ValueError):
            days = cls._DEFAULT_VIDEO_REQUIREMENT_DAYS
        return max(min(days, 365), 1)

    @staticmethod
    def _normalize_duration_threshold(value) -> float:
        try:
            threshold = float(value)
        except (TypeError, ValueError):
            threshold = 25.0
        return max(min(threshold, 3600.0), 0.0)

    @staticmethod
    def _batch_is_within_days(batch: dict | None, days: int) -> bool:
        if not batch:
            return False
        raw_created_at = batch.get("created_at")
        if not raw_created_at:
            return True
        try:
            created_at = datetime.fromisoformat(str(raw_created_at).replace("Z", "+00:00"))
        except ValueError:
            return True
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        return created_at >= datetime.now(timezone.utc) - timedelta(days=AccessService._normalize_requirement_days(days))

    @staticmethod
    def _duration_policy_text(policy: VideoRequirementPolicy, effective_days: int) -> str:
        if not policy.duration_based:
            return ""
        if effective_days != policy.long_video_days:
            return ""
        threshold = policy.long_video_min_duration_seconds
        threshold_text = f"{threshold:.0f}" if float(threshold).is_integer() else f"{threshold:.1f}"
        return f" por video de {threshold_text}s o mas"

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

    def _identifier_exists(self, identifier: str) -> bool:
        rows = self._client_provider.execute(
            self._client_provider.client.rpc(
                "resolve_login_identifier",
                {"p_identifier": identifier},
            )
        )
        return bool(rows)

    @staticmethod
    def _profile_identifier(profile: dict, fallback: str) -> str:
        login_id = str(profile.get("login_id") or "").strip()
        if login_id:
            return login_id
        email = str(profile.get("email") or "").strip()
        if "@" in email:
            return email
        return fallback or email
