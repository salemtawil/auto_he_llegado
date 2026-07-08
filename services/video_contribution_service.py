from __future__ import annotations

from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import shutil
from time import sleep
from typing import Callable

from config.settings import Settings, get_settings
from services.access_service import AccessService
from services.auth_context import AuthSession, require_current_session
from services.photo_review_service import PhotoBatchRecord, PhotoReviewService
from services.video_frame_extractor import ExtractedFrame, VideoFrameExtractor


@dataclass(frozen=True)
class VideoContributionProgress:
    phase: str
    message: str
    current: int = 0
    total: int = 0


@dataclass(frozen=True)
class VideoContributionResult:
    batch: PhotoBatchRecord
    frames_extracted: int
    candidates_uploaded: int


class VideoContributionService:
    _DB_BATCH_SIZE = 25
    _MAX_CONCURRENT_UPLOADS = 3
    _RETRY_DELAYS_SECONDS = (0.8, 1.6, 3.0)

    def __init__(
        self,
        review_service: PhotoReviewService | None = None,
        extractor: VideoFrameExtractor | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._review_service = review_service or PhotoReviewService(settings=self._settings)
        self._extractor = extractor or VideoFrameExtractor()
        self._work_dir = self._settings.local_data_dir / "video_frames"
        self._work_dir.mkdir(parents=True, exist_ok=True)

    def submit_video(
        self,
        video_path: str | Path,
        *,
        session: AuthSession | None = None,
        progress_callback: Callable[[VideoContributionProgress], None] | None = None,
    ) -> VideoContributionResult:
        session = session or require_current_session()
        source = Path(video_path)
        week_start = AccessService.current_week_start()
        batch = self._review_service.create_batch(
            user_id=session.user_id,
            week_start=week_start,
            original_video_name=source.name,
        )
        batch_dir = self._work_dir / batch.id
        self._emit(progress_callback, "extracting", "Extrayendo fotos utiles del video...")
        try:
            frames = self._extractor.extract(
                source,
                batch_dir,
                interval_seconds=self._settings.video_frame_interval_seconds,
                max_frames=self._settings.video_max_candidate_frames,
                jpeg_quality=self._settings.video_jpeg_quality,
            )
            uploaded_count = self._upload_frames(
                frames,
                batch_id=batch.id,
                user_id=session.user_id,
                progress_callback=progress_callback,
            )
            final_batch = self._review_service.finish_batch(
                batch_id=batch.id,
                frames_extracted=len(frames),
                candidates_uploaded=uploaded_count,
            )
            self._emit(
                progress_callback,
                "done",
                f"Video recibido. {uploaded_count} foto(s) quedaron pendientes de revision.",
                current=uploaded_count,
                total=uploaded_count,
            )
            return VideoContributionResult(
                batch=final_batch,
                frames_extracted=len(frames),
                candidates_uploaded=uploaded_count,
            )
        except Exception as exc:
            self._review_service.mark_batch_failed(batch.id, str(exc))
            raise
        finally:
            shutil.rmtree(batch_dir, ignore_errors=True)

    def _upload_frames(
        self,
        frames: list[ExtractedFrame],
        *,
        batch_id: str,
        user_id: str,
        progress_callback: Callable[[VideoContributionProgress], None] | None,
    ) -> int:
        total = len(frames)
        uploaded_count = 0
        pending_candidates: list[dict] = []
        max_workers = min(self._MAX_CONCURRENT_UPLOADS, max(total, 1))
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            uploaded_candidates = executor.map(
                lambda current_frame: self._upload_single_frame(
                    current_frame,
                    batch_id=batch_id,
                    user_id=user_id,
                ),
                frames,
            )
            for index, candidate in enumerate(uploaded_candidates, start=1):
                uploaded_count += 1
                pending_candidates.append(candidate)
                self._emit(
                    progress_callback,
                    "uploading",
                    f"Subiendo foto candidata {index} de {total}...",
                    current=index,
                    total=total,
                )
                if len(pending_candidates) >= self._DB_BATCH_SIZE:
                    self._flush_candidates(pending_candidates)
                    pending_candidates = []
        if pending_candidates:
            self._flush_candidates(pending_candidates)
        return uploaded_count

    def _upload_single_frame(self, frame: ExtractedFrame, *, batch_id: str, user_id: str) -> dict:
        candidate_id = frame.path.stem
        storage_path = f"candidates/{user_id}/{batch_id}/{candidate_id}.jpg"
        self._retry_supabase_write(
            lambda current_path=storage_path, current_frame=frame: self._review_service.upload_candidate_binary(
                storage_path=current_path,
                content=current_frame.path.read_bytes(),
            )
        )
        return {
            "batch_id": batch_id,
            "user_id": user_id,
            "storage_path": storage_path,
            "original_name": frame.path.name,
            "frame_index": frame.frame_index,
            "timestamp_seconds": frame.timestamp_seconds,
            "blur_score": frame.blur_score,
            "brightness_score": frame.brightness_score,
        }

    def _flush_candidates(self, candidates: list[dict]) -> None:
        self._retry_supabase_write(lambda: self._review_service.create_candidates(candidates))

    def _retry_supabase_write(self, operation) -> None:
        last_error: Exception | None = None
        for delay_index, delay_seconds in enumerate((0.0, *self._RETRY_DELAYS_SECONDS)):
            if delay_seconds > 0:
                sleep(delay_seconds)
            try:
                operation()
                return
            except Exception as exc:
                last_error = exc
                if not self._is_retryable_supabase_error(exc) or delay_index >= len(self._RETRY_DELAYS_SECONDS):
                    raise
        if last_error is not None:
            raise last_error

    @staticmethod
    def _is_retryable_supabase_error(exc: Exception) -> bool:
        message = str(exc).lower()
        return any(
            marker in message
            for marker in (
                "too_many_connections",
                "too many connections",
                "statuscode': 429",
                "statuscode\": 429",
                "timeout",
                "temporarily unavailable",
            )
        )

    @staticmethod
    def _emit(
        callback: Callable[[VideoContributionProgress], None] | None,
        phase: str,
        message: str,
        *,
        current: int = 0,
        total: int = 0,
    ) -> None:
        if callback is not None:
            callback(
                VideoContributionProgress(
                    phase=phase,
                    message=message,
                    current=current,
                    total=total,
                )
            )
