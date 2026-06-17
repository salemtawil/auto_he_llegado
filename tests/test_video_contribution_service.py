from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from config.settings import Settings
from services.access_service import AccessService
from services.auth_context import AuthSession
from services.photo_review_service import PhotoBatchRecord
from services.video_contribution_service import VideoContributionService
from services.video_frame_extractor import ExtractedFrame


def build_settings(tmp_path: Path) -> Settings:
    return Settings(
        app_name="test-app",
        app_env="test",
        log_level="INFO",
        project_root=tmp_path,
        local_data_dir=tmp_path / "local_data",
        supabase_url="https://example.supabase.co",
        supabase_key="test-key",
        supabase_storage_bucket="photo-pool",
        supabase_photos_table="photos",
        supabase_process_logs_table="process_logs",
        supabase_photo_batches_table="photo_ingest_batches",
        supabase_photo_candidates_table="photo_candidates",
        supabase_profiles_table="profiles",
        supabase_timeout_seconds=30,
        admin_access_password="secret",
        weekly_min_approved_photos=20,
        video_frame_interval_seconds=0.0,
        video_max_candidate_frames=300,
        video_jpeg_quality=88,
        use_chrome_profile_extension=False,
        chrome_profile_dir=None,
        chrome_executable_path=None,
    )


class StubExtractor:
    def __init__(self, tmp_path: Path) -> None:
        self.tmp_path = tmp_path
        self.calls = []

    def extract(self, video_path, output_dir, **kwargs):
        self.calls.append((video_path, output_dir, kwargs))
        frame_paths = []
        for index in range(2):
            path = Path(output_dir) / f"frame_{index}.jpg"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(f"jpg-{index}".encode())
            frame_paths.append(path)
        return [
            ExtractedFrame(
                path=frame_paths[0],
                frame_index=10,
                timestamp_seconds=1.0,
                blur_score=45.0,
                brightness_score=120.0,
            ),
            ExtractedFrame(
                path=frame_paths[1],
                frame_index=20,
                timestamp_seconds=2.0,
                blur_score=55.0,
                brightness_score=125.0,
            ),
        ]


class StubReviewService:
    def __init__(self) -> None:
        self.uploads = []
        self.candidates = []
        self.finished = []
        self.failed = []

    def create_batch(self, *, user_id, week_start, original_video_name):
        return PhotoBatchRecord(
            id="batch-1",
            user_id=user_id,
            week_start=week_start.isoformat(),
            original_video_name=original_video_name,
            frames_extracted=0,
            candidates_uploaded=0,
            approved_count=0,
            rejected_count=0,
            status="processing",
        )

    def upload_candidate_binary(self, *, storage_path, content):
        self.uploads.append((storage_path, content))

    def create_candidate(self, **kwargs):
        self.candidates.append(kwargs)
        return SimpleNamespace(**kwargs)

    def create_candidates(self, candidates):
        self.candidates.extend(candidates)
        return [SimpleNamespace(**candidate) for candidate in candidates]

    def finish_batch(self, *, batch_id, frames_extracted, candidates_uploaded):
        self.finished.append((batch_id, frames_extracted, candidates_uploaded))
        return PhotoBatchRecord(
            id=batch_id,
            user_id="user-1",
            week_start="2026-06-15",
            original_video_name="weekly.mp4",
            frames_extracted=frames_extracted,
            candidates_uploaded=candidates_uploaded,
            approved_count=0,
            rejected_count=0,
            status="pending_review",
        )

    def mark_batch_failed(self, batch_id, message):
        self.failed.append((batch_id, message))


def test_current_week_start_uses_monday_utc() -> None:
    assert AccessService.current_week_start(
        datetime(2026, 6, 17, tzinfo=timezone.utc)
    ).isoformat() == "2026-06-15"


def test_video_submission_uploads_extracted_jpg_candidates_only(tmp_path) -> None:
    video = tmp_path / "weekly.mp4"
    video.write_bytes(b"video-data")
    review_service = StubReviewService()
    extractor = StubExtractor(tmp_path)
    service = VideoContributionService(
        review_service=review_service,
        extractor=extractor,
        settings=build_settings(tmp_path),
    )
    session = AuthSession(
        user_id="user-1",
        email="member@example.com",
        access_token="access",
        refresh_token="refresh",
        approved=True,
    )

    result = service.submit_video(video, session=session)

    assert result.frames_extracted == 2
    assert result.candidates_uploaded == 2
    assert review_service.uploads == [
        ("candidates/user-1/batch-1/frame_0.jpg", b"jpg-0"),
        ("candidates/user-1/batch-1/frame_1.jpg", b"jpg-1"),
    ]
    assert len(review_service.candidates) == 2
    assert review_service.candidates[0]["storage_path"] == "candidates/user-1/batch-1/frame_0.jpg"
    assert review_service.finished == [("batch-1", 2, 2)]
    assert review_service.failed == []
