from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timezone
from uuid import uuid4

from config.settings import Settings, get_settings
from services.access_service import AccessService, VideoRequirementPolicy
from services.photo_pool_policy_service import PhotoPoolPolicy, PhotoPoolPolicyService
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
    video_exempt: bool = False
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
        self._access_service = AccessService(client_provider=self._client_provider, settings=self._settings)
        self._pool_policy_service = PhotoPoolPolicyService(
            client_provider=self._client_provider,
            settings=self._settings,
        )
        self._table = self._settings.supabase_profiles_table
        self._batches_table = self._settings.supabase_photo_batches_table

    def list_users(self, *, limit: int = 100) -> list[UserAccessRecord]:
        policy = self.get_video_requirement_policy()
        cutoff_iso = self._policy_cutoff_iso(policy)
        rows = self._client_provider.execute(
            self._client_provider.client.table(self._table)
            .select("*")
            .order("created_at", desc=True)
            .limit(max(int(limit), 1))
        )
        weekly_videos = self._latest_weekly_videos(
            [str(row.get("id") or "") for row in rows],
            cutoff_iso=cutoff_iso,
        )
        return [
            self._record_from_row(
                row,
                weekly_video=weekly_videos.get(str(row.get("id") or "")),
            )
            for row in rows
        ]

    def get_video_requirement_policy(self) -> VideoRequirementPolicy:
        return self._access_service.get_video_requirement_policy()

    def update_video_requirement_policy(
        self,
        *,
        enabled: bool,
        days: int,
        duration_based: bool = False,
        long_video_days: int | None = None,
        long_video_min_duration_seconds: float | None = None,
    ) -> VideoRequirementPolicy:
        normalized_days = AccessService._normalize_requirement_days(days)  # noqa: SLF001
        normalized_long_days = AccessService._normalize_requirement_days(  # noqa: SLF001
            long_video_days if long_video_days is not None else normalized_days
        )
        normalized_threshold = AccessService._normalize_duration_threshold(  # noqa: SLF001
            long_video_min_duration_seconds
        )
        payload = {
            "key": "video_requirement",
            "value": {
                "enabled": bool(enabled),
                "days": normalized_days,
                "duration_based": bool(duration_based),
                "long_video_days": normalized_long_days,
                "long_video_min_duration_seconds": normalized_threshold,
            },
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        rows = self._client_provider.execute(
            self._client_provider.client.table("app_settings").upsert(payload)
        )
        if not rows:
            raise RuntimeError("No se actualizo la politica de video requerido.")
        return VideoRequirementPolicy(
            enabled=bool(enabled),
            days=normalized_days,
            duration_based=bool(duration_based),
            long_video_days=normalized_long_days,
            long_video_min_duration_seconds=normalized_threshold,
            source="supabase",
        )

    def get_photo_pool_policy(self) -> PhotoPoolPolicy:
        return self._pool_policy_service.get_policy()

    def list_photo_pool_buckets(self) -> list[str]:
        return self._pool_policy_service.list_buckets()

    def update_photo_pool_policy(self, *, bucket: str) -> PhotoPoolPolicy:
        return self._pool_policy_service.update_policy(bucket=bucket)

    def approve_user(self, user_id: str) -> UserAccessRecord:
        return self._update_user(user_id, {"approved": True, "disabled": False})

    def disable_user(self, user_id: str) -> UserAccessRecord:
        return self._update_user(user_id, {"disabled": True})

    def enable_user(self, user_id: str) -> UserAccessRecord:
        return self._update_user(user_id, {"disabled": False})

    def make_admin(self, user_id: str) -> UserAccessRecord:
        return self._update_user(user_id, {"role": "admin", "approved": True, "disabled": False})

    def set_video_exempt(self, user_id: str, exempt: bool) -> UserAccessRecord:
        if exempt:
            self._create_video_exemption_batch(user_id)
        else:
            self._revoke_video_exemption_batches(user_id)
        return self._update_user(user_id, {"video_exempt": bool(exempt)})

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
            raise RuntimeError("Este usuario no tiene video requerido cargado.")
        payload = dict(changes)
        payload["updated_at"] = datetime.now(timezone.utc).isoformat()
        rows = self._client_provider.execute(
            self._client_provider.client.table(self._batches_table)
            .update(payload)
            .eq("id", weekly_video.id)
        )
        if not rows:
            raise RuntimeError("No se actualizo el video requerido.")
        return self._weekly_video_from_row(rows[0])

    def _create_video_exemption_batch(self, user_id: str) -> None:
        if not user_id:
            return
        policy = self.get_video_requirement_policy()
        period_start = AccessService.current_requirement_start(policy.days)
        payload = {
            "id": str(uuid4()),
            "user_id": user_id,
            "week_start": period_start.isoformat(),
            "original_video_name": "exencion_admin_sin_video",
            "frames_extracted": 0,
            "candidates_uploaded": 0,
            "approved_count": 0,
            "rejected_count": 0,
            "status": "accepted",
            "error_message": "Exencion de video aplicada por admin.",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        self._client_provider.execute(
            self._client_provider.client.table(self._batches_table).insert(payload)
        )

    def _revoke_video_exemption_batches(self, user_id: str) -> None:
        if not user_id:
            return
        payload = {
            "status": "rejected",
            "error_message": "Exencion de video revocada por admin.",
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        self._client_provider.execute(
            self._client_provider.client.table(self._batches_table)
            .update(payload)
            .eq("user_id", user_id)
            .eq("original_video_name", "exencion_admin_sin_video")
            .in_("status", ["processing", "pending_review", "accepted", "reviewed"])
        )

    def _latest_weekly_video(self, user_id: str, *, cutoff_iso: str | None = None) -> WeeklyVideoRecord | None:
        if not user_id:
            return None
        cutoff = cutoff_iso or self._current_policy_cutoff_iso()
        rows = self._client_provider.execute(
            self._client_provider.client.table(self._batches_table)
            .select("*")
            .eq("user_id", user_id)
            .gte("created_at", cutoff)
            .order("created_at", desc=True)
            .limit(1)
        )
        return self._weekly_video_from_row(rows[0]) if rows else None

    def _latest_weekly_videos(
        self,
        user_ids: list[str],
        *,
        cutoff_iso: str,
    ) -> dict[str, WeeklyVideoRecord]:
        normalized_user_ids = [user_id for user_id in dict.fromkeys(user_ids) if user_id]
        if not normalized_user_ids:
            return {}
        try:
            query = (
                self._client_provider.client.table(self._batches_table)
                .select("*")
                .in_("user_id", normalized_user_ids)
                .gte("created_at", cutoff_iso)
                .order("created_at", desc=True)
                .limit(max(len(normalized_user_ids) * 3, 1))
            )
            rows = self._client_provider.execute(query)
        except Exception:
            return {
                user_id: weekly_video
                for user_id in normalized_user_ids
                if (weekly_video := self._latest_weekly_video(user_id, cutoff_iso=cutoff_iso)) is not None
            }
        latest_by_user: dict[str, WeeklyVideoRecord] = {}
        for row in rows:
            user_id = str(row.get("user_id") or "")
            if not user_id or user_id in latest_by_user:
                continue
            latest_by_user[user_id] = self._weekly_video_from_row(row)
        return latest_by_user

    def _current_policy_cutoff_iso(self) -> str:
        policy = self._access_service.get_video_requirement_policy()
        return self._policy_cutoff_iso(policy)

    @staticmethod
    def _policy_cutoff_iso(policy: VideoRequirementPolicy) -> str:
        period_start = AccessService.current_requirement_start(policy.max_days)
        return datetime.combine(period_start, time.min, tzinfo=timezone.utc).isoformat()

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
            video_exempt=bool(row.get("video_exempt")),
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
