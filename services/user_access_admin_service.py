from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

from config.settings import Settings, get_settings
from storage.supabase_client import SupabaseClientProvider


@dataclass(frozen=True)
class WeeklyVideoRecord:
    id: str
    week_start: str
    original_video_name: str
    frames_extracted: int
    candidates_uploaded: int
    approved_count: int
    rejected_count: int
    status: str
    error_message: str | None = None
    created_at: str | None = None


@dataclass(frozen=True)
class UserAccessRecord:
    id: str
    email: str
    login_id: str
    display_name: str
    role: str
    approved: bool
    disabled: bool
    weekly_video: WeeklyVideoRecord | None = None
    created_at: str | None = None


class UserAccessAdminService:
    def __init__(
        self,
        client_provider: SupabaseClientProvider | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._client_provider = client_provider or SupabaseClientProvider(self._settings)
        self._table = self._settings.supabase_profiles_table
        self._batches_table = self._settings.supabase_photo_batches_table

    def list_users(self, *, limit: int = 100) -> list[UserAccessRecord]:
        rows = self._client_provider.execute(
            self._client_provider.client.table(self._table)
            .select("*")
            .order("created_at", desc=True)
            .limit(max(int(limit), 1))
        )
        return [
            self._record_from_row(
                row,
                weekly_video=self._latest_weekly_video(str(row.get("id") or "")),
            )
            for row in rows
        ]

    def approve_user(self, user_id: str) -> UserAccessRecord:
        return self._update_user(user_id, {"approved": True, "disabled": False})

    def disable_user(self, user_id: str) -> UserAccessRecord:
        return self._update_user(user_id, {"disabled": True})

    def enable_user(self, user_id: str) -> UserAccessRecord:
        return self._update_user(user_id, {"disabled": False})

    def make_admin(self, user_id: str) -> UserAccessRecord:
        return self._update_user(user_id, {"role": "admin", "approved": True, "disabled": False})

    def update_login_id(self, user_id: str, login_id: str) -> UserAccessRecord:
        normalized_login_id = login_id.strip().lower()
        return self._update_user(user_id, {"login_id": normalized_login_id or None})

    def approve_weekly_video(self, user_id: str) -> WeeklyVideoRecord:
        return self._update_latest_weekly_video(user_id, {"status": "accepted", "error_message": None})

    def reject_weekly_video(self, user_id: str) -> WeeklyVideoRecord:
        return self._update_latest_weekly_video(user_id, {"status": "rejected"})

    def _update_user(self, user_id: str, changes: dict) -> UserAccessRecord:
        payload = dict(changes)
        payload["updated_at"] = datetime.now(timezone.utc).isoformat()
        rows = self._client_provider.execute(
            self._client_provider.client.table(self._table)
            .update(payload)
            .eq("id", user_id)
        )
        if not rows:
            raise RuntimeError("No se actualizo el usuario.")
        return self._record_from_row(
            rows[0],
            weekly_video=self._latest_weekly_video(user_id),
        )

    def _update_latest_weekly_video(self, user_id: str, changes: dict) -> WeeklyVideoRecord:
        weekly_video = self._latest_weekly_video(user_id)
        if weekly_video is None:
            raise RuntimeError("Este usuario no tiene video semanal cargado.")
        payload = dict(changes)
        payload["updated_at"] = datetime.now(timezone.utc).isoformat()
        rows = self._client_provider.execute(
            self._client_provider.client.table(self._batches_table)
            .update(payload)
            .eq("id", weekly_video.id)
        )
        if not rows:
            raise RuntimeError("No se actualizo el video semanal.")
        return self._weekly_video_from_row(rows[0])

    def _latest_weekly_video(self, user_id: str) -> WeeklyVideoRecord | None:
        if not user_id:
            return None
        rows = self._client_provider.execute(
            self._client_provider.client.table(self._batches_table)
            .select("*")
            .eq("user_id", user_id)
            .eq("week_start", self._current_week_start().isoformat())
            .order("created_at", desc=True)
            .limit(1)
        )
        return self._weekly_video_from_row(rows[0]) if rows else None

    @staticmethod
    def _record_from_row(row: dict, *, weekly_video: WeeklyVideoRecord | None = None) -> UserAccessRecord:
        return UserAccessRecord(
            id=str(row.get("id") or ""),
            email=str(row.get("email") or ""),
            login_id=str(row.get("login_id") or ""),
            display_name=str(row.get("display_name") or ""),
            role=str(row.get("role") or "member"),
            approved=bool(row.get("approved")),
            disabled=bool(row.get("disabled")),
            weekly_video=weekly_video,
            created_at=str(row.get("created_at") or "") or None,
        )

    @staticmethod
    def _weekly_video_from_row(row: dict) -> WeeklyVideoRecord:
        return WeeklyVideoRecord(
            id=str(row.get("id") or ""),
            week_start=str(row.get("week_start") or ""),
            original_video_name=str(row.get("original_video_name") or ""),
            frames_extracted=int(row.get("frames_extracted") or 0),
            candidates_uploaded=int(row.get("candidates_uploaded") or 0),
            approved_count=int(row.get("approved_count") or 0),
            rejected_count=int(row.get("rejected_count") or 0),
            status=str(row.get("status") or ""),
            error_message=row.get("error_message"),
            created_at=str(row.get("created_at") or "") or None,
        )

    @staticmethod
    def _current_week_start(now: datetime | None = None) -> date:
        current = now or datetime.now(timezone.utc)
        current_date = current.date()
        return current_date - timedelta(days=current_date.weekday())
