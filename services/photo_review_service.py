from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from uuid import uuid4

from config.settings import Settings, get_settings
from core.enums import PhotoStatus
from core.models import PhotoCreate
from services.auth_context import AuthSession, require_current_session
from storage.photos_repository import PhotosRepository
from storage.supabase_client import SupabaseClientProvider


@dataclass(frozen=True)
class PhotoBatchRecord:
    id: str
    user_id: str
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
class PhotoCandidateRecord:
    id: str
    batch_id: str
    user_id: str
    storage_path: str
    original_name: str
    frame_index: int
    timestamp_seconds: float
    blur_score: float | None
    brightness_score: float | None
    status: str
    reviewed_by: str | None = None
    reviewed_at: str | None = None
    rejection_reason: str | None = None
    approved_photo_id: str | None = None
    created_at: str | None = None


@dataclass(frozen=True)
class PhotoReviewSnapshot:
    pending_count: int
    approved_count: int
    rejected_count: int
    batches: list[PhotoBatchRecord]
    candidates: list[PhotoCandidateRecord]


class PhotoReviewService:
    _BULK_ACTION_CHUNK_SIZE = 100

    def __init__(
        self,
        client_provider: SupabaseClientProvider | None = None,
        photos_repository: PhotosRepository | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._client_provider = client_provider or SupabaseClientProvider(self._settings)
        self._photos_repository = photos_repository or PhotosRepository(
            client_provider=self._client_provider,
            settings=self._settings,
        )
        self._batches_table = self._settings.supabase_photo_batches_table
        self._candidates_table = self._settings.supabase_photo_candidates_table
        self._thumbnail_dir = self._settings.local_data_dir / "review_thumbnails"
        self._thumbnail_dir.mkdir(parents=True, exist_ok=True)

    def create_batch(
        self,
        *,
        user_id: str,
        week_start: date,
        original_video_name: str,
    ) -> PhotoBatchRecord:
        batch_id = str(uuid4())
        rows = self._client_provider.execute(
            self._client_provider.client.table(self._batches_table).insert(
                {
                    "id": batch_id,
                    "user_id": user_id,
                    "week_start": week_start.isoformat(),
                    "original_video_name": original_video_name,
                    "status": "processing",
                }
            )
        )
        return self._batch_from_row(self._single(rows, "No se creo el lote de fotos."))

    def mark_batch_failed(self, batch_id: str, message: str) -> None:
        self._client_provider.execute(
            self._client_provider.client.table(self._batches_table)
            .update(
                {
                    "status": "rejected",
                    "error_message": message[:1000],
                    "updated_at": self._utcnow(),
                }
            )
            .eq("id", batch_id)
        )

    def create_candidate(
        self,
        *,
        batch_id: str,
        user_id: str,
        storage_path: str,
        original_name: str,
        frame_index: int,
        timestamp_seconds: float,
        blur_score: float,
        brightness_score: float,
    ) -> PhotoCandidateRecord:
        return self.create_candidates(
            [
                {
                    "batch_id": batch_id,
                    "user_id": user_id,
                    "storage_path": storage_path,
                    "original_name": original_name,
                    "frame_index": frame_index,
                    "timestamp_seconds": timestamp_seconds,
                    "blur_score": blur_score,
                    "brightness_score": brightness_score,
                }
            ]
        )[0]

    def create_candidates(self, candidates: list[dict]) -> list[PhotoCandidateRecord]:
        payload = []
        for candidate in candidates:
            payload.append(
                {
                    "id": str(uuid4()),
                    "batch_id": candidate["batch_id"],
                    "user_id": candidate["user_id"],
                    "storage_path": candidate["storage_path"],
                    "original_name": candidate["original_name"],
                    "frame_index": candidate["frame_index"],
                    "timestamp_seconds": candidate["timestamp_seconds"],
                    "blur_score": candidate["blur_score"],
                    "brightness_score": candidate["brightness_score"],
                    "status": "pending",
                }
            )
        if not payload:
            return []
        rows = self._client_provider.execute(
            self._client_provider.client.table(self._candidates_table).insert(payload)
        )
        return [self._candidate_from_row(row) for row in rows]

    def upload_candidate_binary(self, *, storage_path: str, content: bytes) -> None:
        self._client_provider.upload_binary(
            bucket_name=self._settings.supabase_storage_bucket,
            storage_path=storage_path,
            content=content,
            content_type="image/jpeg",
        )

    def finish_batch(
        self,
        *,
        batch_id: str,
        frames_extracted: int,
        candidates_uploaded: int,
    ) -> PhotoBatchRecord:
        rows = self._client_provider.execute(
            self._client_provider.client.table(self._batches_table)
            .update(
                {
                    "frames_extracted": frames_extracted,
                    "candidates_uploaded": candidates_uploaded,
                    "status": "pending_review",
                    "updated_at": self._utcnow(),
                }
            )
            .eq("id", batch_id)
        )
        return self._batch_from_row(self._single(rows, "No se actualizo el lote."))

    def list_review_snapshot(
        self,
        *,
        status: str = "pending",
        limit: int | None = 300,
    ) -> PhotoReviewSnapshot:
        normalized_status = (status or "pending").strip().lower()
        candidates = self._list_candidates(normalized_status, limit=limit)
        batches = self._list_recent_batches()
        return PhotoReviewSnapshot(
            pending_count=self._count_candidates("pending"),
            approved_count=self._count_candidates("approved"),
            rejected_count=self._count_candidates("rejected") + self._count_candidates("deleted"),
            batches=batches,
            candidates=candidates,
        )

    def _list_candidates(
        self,
        normalized_status: str,
        *,
        limit: int | None,
    ) -> list[PhotoCandidateRecord]:
        page_size = 1000
        if limit is not None:
            limit = max(int(limit), 1)
            page_size = min(page_size, limit)

        candidates: list[PhotoCandidateRecord] = []
        offset = 0
        while True:
            end = offset + page_size - 1
            if limit is not None:
                remaining = limit - len(candidates)
                if remaining <= 0:
                    break
                end = offset + min(page_size, remaining) - 1

            query = (
                self._client_provider.client.table(self._candidates_table)
                .select("*")
                .order("created_at", desc=True)
            )
            if normalized_status != "all":
                query = query.eq("status", normalized_status)
            query = query.range(offset, end)

            rows = self._client_provider.execute(query)
            candidates.extend(self._candidate_from_row(row) for row in rows)
            if len(rows) < page_size:
                break
            offset += page_size
        return candidates

    def approve_candidate(
        self,
        candidate_id: str,
        *,
        reviewer: AuthSession | None = None,
    ) -> PhotoCandidateRecord:
        reviewer = reviewer or require_current_session()
        candidate = self.get_candidate(candidate_id)
        if candidate.status == "approved":
            return candidate
        content = self._client_provider.download_binary(
            bucket_name=self._settings.supabase_storage_bucket,
            storage_path=candidate.storage_path,
        )
        photo_id = str(uuid4())
        storage_path = f"available/{photo_id}.jpg"
        self._client_provider.upload_binary(
            bucket_name=self._settings.supabase_storage_bucket,
            storage_path=storage_path,
            content=content,
            content_type="image/jpeg",
        )
        self._photos_repository.create(
            PhotoCreate(
                id=photo_id,
                original_filename=candidate.original_name,
                storage_path=storage_path,
                storage_bucket=self._settings.supabase_storage_bucket,
                status=PhotoStatus.AVAILABLE,
                source="reviewed_video_frame",
            )
        )
        updated = self._update_candidate(
            candidate.id,
            {
                "status": "approved",
                "reviewed_by": reviewer.user_id,
                "reviewed_at": self._utcnow(),
                "approved_photo_id": photo_id,
                "rejection_reason": None,
            },
        )
        self._remove_candidate_storage(candidate)
        self._refresh_batch_counts(candidate.batch_id)
        return updated

    def approve_candidates(
        self,
        candidate_ids: list[str],
        *,
        reviewer: AuthSession | None = None,
        progress_callback=None,
    ) -> list[PhotoCandidateRecord]:
        reviewer = reviewer or require_current_session()
        candidates = self._get_candidates_by_ids(candidate_ids)
        pending_candidates = [candidate for candidate in candidates if candidate.status == "pending"]
        total = len(pending_candidates)
        if total <= 0:
            return []

        approved_photos: list[PhotoCreate] = []
        candidate_updates: list[dict] = []
        batch_ids: set[str] = set()
        updated_count = 0
        reviewed_at = self._utcnow()
        for candidate in pending_candidates:
            photo_id = str(uuid4())
            available_path = f"available/{photo_id}.jpg"
            self._client_provider.move_file(
                bucket_name=self._settings.supabase_storage_bucket,
                from_path=self._normalize_storage_path(candidate.storage_path),
                to_path=available_path,
            )
            approved_photos.append(
                PhotoCreate(
                    id=photo_id,
                    original_filename=candidate.original_name,
                    storage_path=available_path,
                    storage_bucket=self._settings.supabase_storage_bucket,
                    status=PhotoStatus.AVAILABLE,
                    source="reviewed_video_frame",
                )
            )
            candidate_updates.append(
                {
                    "id": candidate.id,
                    "status": "approved",
                    "reviewed_by": reviewer.user_id,
                    "reviewed_at": reviewed_at,
                    "approved_photo_id": photo_id,
                    "rejection_reason": None,
                    "updated_at": reviewed_at,
                }
            )
            batch_ids.add(candidate.batch_id)
            updated_count += 1
            if callable(progress_callback):
                progress_callback(updated_count, total)

        for chunk in self._chunks(approved_photos, self._BULK_ACTION_CHUNK_SIZE):
            self._photos_repository.bulk_create(chunk)
        updated_candidates: list[PhotoCandidateRecord] = []
        for chunk in self._chunks(candidate_updates, self._BULK_ACTION_CHUNK_SIZE):
            updated_candidates.extend(self._bulk_upsert_candidates(chunk))
        self._refresh_many_batch_counts(batch_ids)
        return updated_candidates

    def reject_candidate(
        self,
        candidate_id: str,
        *,
        reason: str = "",
        delete_remote: bool = True,
        reviewer: AuthSession | None = None,
    ) -> PhotoCandidateRecord:
        reviewer = reviewer or require_current_session()
        candidate = self.get_candidate(candidate_id)
        if delete_remote:
            self._remove_candidate_storage(candidate)
        updated = self._update_candidate(
            candidate.id,
            {
                "status": "deleted" if delete_remote else "rejected",
                "reviewed_by": reviewer.user_id,
                "reviewed_at": self._utcnow(),
                "rejection_reason": reason.strip() or "rechazada por revision",
            },
        )
        self._refresh_batch_counts(candidate.batch_id)
        return updated

    def reject_candidates(
        self,
        candidate_ids: list[str],
        *,
        reason: str = "",
        delete_remote: bool = True,
        reviewer: AuthSession | None = None,
        progress_callback=None,
    ) -> list[PhotoCandidateRecord]:
        reviewer = reviewer or require_current_session()
        candidates = self._get_candidates_by_ids(candidate_ids)
        pending_candidates = [candidate for candidate in candidates if candidate.status == "pending"]
        total = len(pending_candidates)
        if total <= 0:
            return []

        reviewed_at = self._utcnow()
        if delete_remote:
            storage_paths = [
                self._normalize_storage_path(candidate.storage_path)
                for candidate in pending_candidates
                if candidate.storage_path
            ]
            for chunk in self._chunks(storage_paths, self._BULK_ACTION_CHUNK_SIZE):
                self._client_provider.remove_files(
                    bucket_name=self._settings.supabase_storage_bucket,
                    storage_paths=chunk,
                )

        updates = []
        batch_ids: set[str] = set()
        for index, candidate in enumerate(pending_candidates, start=1):
            updates.append(
                {
                    "id": candidate.id,
                    "status": "deleted" if delete_remote else "rejected",
                    "reviewed_by": reviewer.user_id,
                    "reviewed_at": reviewed_at,
                    "rejection_reason": reason.strip() or "rechazada por revision",
                    "updated_at": reviewed_at,
                }
            )
            batch_ids.add(candidate.batch_id)
            if callable(progress_callback):
                progress_callback(index, total)

        updated_candidates: list[PhotoCandidateRecord] = []
        for chunk in self._chunks(updates, self._BULK_ACTION_CHUNK_SIZE):
            updated_candidates.extend(self._bulk_upsert_candidates(chunk))
        self._refresh_many_batch_counts(batch_ids)
        return updated_candidates

    def _remove_candidate_storage(self, candidate: PhotoCandidateRecord) -> None:
        if not candidate.storage_path:
            return
        try:
            self._client_provider.remove_file(
                bucket_name=self._settings.supabase_storage_bucket,
                storage_path=self._normalize_storage_path(candidate.storage_path),
            )
        except Exception:
            pass

    def get_candidate(self, candidate_id: str) -> PhotoCandidateRecord:
        rows = self._client_provider.execute(
            self._client_provider.client.table(self._candidates_table)
            .select("*")
            .eq("id", candidate_id)
            .limit(1)
        )
        return self._candidate_from_row(self._single(rows, "Foto candidata no encontrada."))

    def _get_candidates_by_ids(self, candidate_ids: list[str]) -> list[PhotoCandidateRecord]:
        normalized_ids = []
        seen = set()
        for candidate_id in candidate_ids:
            normalized = str(candidate_id or "").strip()
            if normalized and normalized not in seen:
                normalized_ids.append(normalized)
                seen.add(normalized)
        if not normalized_ids:
            return []
        rows = self._client_provider.execute(
            self._client_provider.client.table(self._candidates_table)
            .select("*")
            .in_("id", normalized_ids)
        )
        records_by_id = {str(row.get("id") or ""): self._candidate_from_row(row) for row in rows}
        return [records_by_id[candidate_id] for candidate_id in normalized_ids if candidate_id in records_by_id]

    def get_thumbnail_path(self, candidate: PhotoCandidateRecord, *, max_size: int = 220) -> Path:
        thumbnail_path = self._thumbnail_dir / f"{candidate.id}.png"
        if thumbnail_path.exists():
            return thumbnail_path
        content = self._client_provider.download_binary(
            bucket_name=self._settings.supabase_storage_bucket,
            storage_path=candidate.storage_path,
        )
        try:
            import cv2
            import numpy as np
        except Exception as exc:
            raise RuntimeError("OpenCV no esta instalado para crear miniaturas.") from exc
        image = cv2.imdecode(np.frombuffer(content, dtype=np.uint8), cv2.IMREAD_COLOR)
        if image is None:
            raise ValueError("No se pudo leer la foto candidata.")
        height, width = image.shape[:2]
        scale = min(max_size / max(width, 1), max_size / max(height, 1), 1.0)
        resized = cv2.resize(image, (max(int(width * scale), 1), max(int(height * scale), 1)))
        cv2.imwrite(str(thumbnail_path), resized)
        return thumbnail_path

    @staticmethod
    def _normalize_storage_path(storage_path: str) -> str:
        return str(storage_path or "").strip().replace("\\", "/").lstrip("/")

    def _list_recent_batches(self, limit: int = 20) -> list[PhotoBatchRecord]:
        rows = self._client_provider.execute(
            self._client_provider.client.table(self._batches_table)
            .select("*")
            .order("created_at", desc=True)
            .limit(max(int(limit), 1))
        )
        return [self._batch_from_row(row) for row in rows]

    def _count_candidates(self, status: str) -> int:
        response = self._client_provider.execute_response(
            self._client_provider.client.table(self._candidates_table)
            .select("id", count="exact")
            .eq("status", status)
        )
        return int(getattr(response, "count", 0) or 0)

    def _refresh_batch_counts(self, batch_id: str) -> None:
        candidates = self._client_provider.execute(
            self._client_provider.client.table(self._candidates_table)
            .select("status")
            .eq("batch_id", batch_id)
        )
        approved = sum(1 for item in candidates if item.get("status") == "approved")
        rejected = sum(1 for item in candidates if item.get("status") in {"rejected", "deleted"})
        pending = sum(1 for item in candidates if item.get("status") == "pending")
        current_status = self._get_batch_status(batch_id)
        if current_status in {"accepted", "rejected"}:
            status = current_status
        elif pending > 0:
            status = "pending_review"
        else:
            status = "reviewed"
        self._client_provider.execute(
            self._client_provider.client.table(self._batches_table)
            .update(
                {
                    "approved_count": approved,
                    "rejected_count": rejected,
                    "status": status,
                    "updated_at": self._utcnow(),
                }
            )
            .eq("id", batch_id)
        )

    def _refresh_many_batch_counts(self, batch_ids: set[str]) -> None:
        for batch_id in sorted(batch_ids):
            if batch_id:
                self._refresh_batch_counts(batch_id)

    def _bulk_upsert_candidates(self, payload: list[dict]) -> list[PhotoCandidateRecord]:
        if not payload:
            return []
        rows = self._client_provider.execute(
            self._client_provider.client.table(self._candidates_table).upsert(payload)
        )
        return [self._candidate_from_row(row) for row in rows]

    @staticmethod
    def _chunks(items: list, size: int):
        normalized_size = max(int(size), 1)
        for index in range(0, len(items), normalized_size):
            yield items[index : index + normalized_size]

    def _get_batch_status(self, batch_id: str) -> str:
        rows = self._client_provider.execute(
            self._client_provider.client.table(self._batches_table)
            .select("status")
            .eq("id", batch_id)
            .limit(1)
        )
        if not rows:
            return ""
        return str(rows[0].get("status") or "")

    def _update_candidate(self, candidate_id: str, payload: dict) -> PhotoCandidateRecord:
        payload = dict(payload)
        payload["updated_at"] = self._utcnow()
        rows = self._client_provider.execute(
            self._client_provider.client.table(self._candidates_table)
            .update(payload)
            .eq("id", candidate_id)
        )
        return self._candidate_from_row(self._single(rows, "No se actualizo la foto candidata."))

    @staticmethod
    def _single(rows: list[dict], message: str) -> dict:
        if not rows:
            raise RuntimeError(message)
        return dict(rows[0])

    @staticmethod
    def _batch_from_row(row: dict) -> PhotoBatchRecord:
        return PhotoBatchRecord(
            id=str(row.get("id") or ""),
            user_id=str(row.get("user_id") or ""),
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
    def _candidate_from_row(row: dict) -> PhotoCandidateRecord:
        return PhotoCandidateRecord(
            id=str(row.get("id") or ""),
            batch_id=str(row.get("batch_id") or ""),
            user_id=str(row.get("user_id") or ""),
            storage_path=str(row.get("storage_path") or ""),
            original_name=str(row.get("original_name") or ""),
            frame_index=int(row.get("frame_index") or 0),
            timestamp_seconds=float(row.get("timestamp_seconds") or 0.0),
            blur_score=None if row.get("blur_score") is None else float(row.get("blur_score")),
            brightness_score=None if row.get("brightness_score") is None else float(row.get("brightness_score")),
            status=str(row.get("status") or ""),
            reviewed_by=row.get("reviewed_by"),
            reviewed_at=str(row.get("reviewed_at") or "") or None,
            rejection_reason=row.get("rejection_reason"),
            approved_photo_id=row.get("approved_photo_id"),
            created_at=str(row.get("created_at") or "") or None,
        )

    @staticmethod
    def _utcnow() -> str:
        return datetime.now(timezone.utc).isoformat()
