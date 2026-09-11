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
        video_submission_mode="frames",
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
        self.batches = []
        self.fingerprint_candidates = []

    def create_batch(self, *, user_id, week_start, original_video_name, **kwargs):
        batch = PhotoBatchRecord(
            id="batch-1",
            user_id=user_id,
            week_start=week_start.isoformat(),
            original_video_name=original_video_name,
            frames_extracted=0,
            candidates_uploaded=0,
            approved_count=0,
            rejected_count=0,
            status="processing",
            **kwargs,
        )
        self.batches.append(batch)
        return batch

    def upload_candidate_binary(self, *, storage_path, content):
        self.uploads.append((storage_path, content))

    def create_candidate(self, **kwargs):
        self.candidates.append(kwargs)
        return SimpleNamespace(**kwargs)

    def create_candidates(self, candidates):
        self.candidates.extend(candidates)
        return [SimpleNamespace(**candidate) for candidate in candidates]

    def finish_batch(self, *, batch_id, frames_extracted, candidates_uploaded, **kwargs):
        self.finished.append((batch_id, frames_extracted, candidates_uploaded, kwargs))
        return PhotoBatchRecord(
            id=batch_id,
            user_id="user-1",
            week_start="2026-06-15",
            original_video_name="weekly.mp4",
            frames_extracted=frames_extracted,
            candidates_uploaded=candidates_uploaded,
            approved_count=0,
            rejected_count=0,
            status=kwargs.get("status", "pending_review"),
            delivery_provider=kwargs.get("delivery_provider") or "",
            delivery_file_id=kwargs.get("delivery_file_id") or "",
            delivery_url=kwargs.get("delivery_url") or "",
        )

    def mark_batch_failed(self, batch_id, message):
        self.failed.append((batch_id, message))

    def list_video_fingerprint_candidates(self):
        return self.fingerprint_candidates


class StubDeliveryService:
    def __init__(self, error: Exception | None = None) -> None:
        self.calls = []
        self.error = error

    def upload_video(self, video_path, *, display_name):
        self.calls.append((Path(video_path), display_name))
        if self.error is not None:
            raise self.error
        return SimpleNamespace(
            provider="google_drive",
            file_id="drive-file-1",
            url="https://drive.google.com/file/d/drive-file-1/view",
        )


class StubNotificationService:
    def __init__(self, error: Exception | None = None) -> None:
        self.messages = []
        self.error = error

    def send_video_received(self, **kwargs):
        if self.error is not None:
            raise self.error
        self.messages.append(kwargs)


class StubFingerprintService:
    def __init__(self, duplicate=None, *, duration_seconds: float = 12.0) -> None:
        self.duplicate = duplicate
        self.duration_seconds = duration_seconds
        self.build_calls = []
        self.find_calls = []

    def build(self, video_path):
        self.build_calls.append(Path(video_path))
        return SimpleNamespace(
            sha256="video-sha",
            size_bytes=1234,
            duration_seconds=self.duration_seconds,
            width=1920,
            height=1080,
            fps=30.0,
            hashes=("a" * 16, "b" * 16),
            as_payload=lambda: {"version": "dhash-v1", "hashes": ["a" * 16, "b" * 16]},
        )

    def find_duplicate(self, fingerprint, existing_batches, *, similarity_threshold, hamming_threshold):
        self.find_calls.append((fingerprint, existing_batches, similarity_threshold, hamming_threshold))
        return self.duplicate


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
    assert sorted(review_service.uploads) == [
        ("candidates/user-1/batch-1/frame_0.jpg", b"jpg-0"),
        ("candidates/user-1/batch-1/frame_1.jpg", b"jpg-1"),
    ]
    assert len(review_service.candidates) == 2
    assert review_service.candidates[0]["storage_path"] == "candidates/user-1/batch-1/frame_0.jpg"
    assert review_service.finished == [("batch-1", 2, 2, {})]
    assert review_service.failed == []


def test_video_submission_uploads_full_video_to_drive_and_notifies(tmp_path) -> None:
    video = tmp_path / "weekly.mp4"
    video.write_bytes(b"video-data")
    settings = build_settings(tmp_path)
    settings = Settings(**{**settings.__dict__, "video_submission_mode": "drive"})
    review_service = StubReviewService()
    delivery_service = StubDeliveryService()
    notification_service = StubNotificationService()
    fingerprint_service = StubFingerprintService()
    service = VideoContributionService(
        review_service=review_service,
        extractor=StubExtractor(tmp_path),
        delivery_service=delivery_service,
        notification_service=notification_service,
        fingerprint_service=fingerprint_service,
        settings=settings,
    )
    session = AuthSession(
        user_id="user-1",
        email="member@example.com",
        access_token="access",
        refresh_token="refresh",
        display_name="Agente Uno",
        approved=True,
    )

    progress = []

    result = service.submit_video(video, session=session, progress_callback=progress.append)

    assert result.frames_extracted == 0
    assert result.candidates_uploaded == 0
    assert [item.phase for item in progress] == ["fingerprinting", "received", "uploading", "done"]
    assert review_service.batches[0].video_sha256 == "video-sha"
    assert review_service.batches[0].video_fingerprint == {
        "version": "dhash-v1",
        "hashes": ["a" * 16, "b" * 16],
    }
    assert delivery_service.calls[0][0] == video
    assert review_service.finished == [
        (
            "batch-1",
            0,
            0,
            {
                "delivery_provider": "google_drive",
                "delivery_file_id": "drive-file-1",
                "delivery_url": "https://drive.google.com/file/d/drive-file-1/view",
                "status": "pending_review",
            },
        )
    ]
    assert notification_service.messages[0]["user_label"] == "Agente Uno"
    assert notification_service.messages[0]["drive_url"] == "https://drive.google.com/file/d/drive-file-1/view"


def test_video_submission_rejects_visual_duplicate_before_drive_upload(tmp_path) -> None:
    video = tmp_path / "weekly.mp4"
    video.write_bytes(b"video-data")
    settings = build_settings(tmp_path)
    settings = Settings(**{**settings.__dict__, "video_submission_mode": "drive"})
    review_service = StubReviewService()
    review_service.fingerprint_candidates = [{"id": "old-batch", "video_fingerprint": {"hashes": ["a" * 16]}}]
    duplicate = SimpleNamespace(batch_id="old-batch", score=0.83)
    delivery_service = StubDeliveryService()
    service = VideoContributionService(
        review_service=review_service,
        extractor=StubExtractor(tmp_path),
        delivery_service=delivery_service,
        notification_service=StubNotificationService(),
        fingerprint_service=StubFingerprintService(duplicate=duplicate),
        settings=settings,
    )
    session = AuthSession(
        user_id="user-1",
        email="member@example.com",
        access_token="access",
        refresh_token="refresh",
        approved=True,
    )

    try:
        service.submit_video(video, session=session)
    except RuntimeError as exc:
        assert "parece repetido" in str(exc)
    else:
        raise AssertionError("Expected duplicate video to be rejected.")

    assert review_service.batches[0].duplicate_of_batch_id == "old-batch"
    assert review_service.failed[0][0] == "batch-1"
    assert delivery_service.calls == []


def test_video_submission_rejects_short_video_before_batch_and_drive_upload(tmp_path) -> None:
    video = tmp_path / "short.mp4"
    video.write_bytes(b"video-data")
    settings = build_settings(tmp_path)
    settings = Settings(**{**settings.__dict__, "video_submission_mode": "drive"})
    review_service = StubReviewService()
    delivery_service = StubDeliveryService()
    service = VideoContributionService(
        review_service=review_service,
        extractor=StubExtractor(tmp_path),
        delivery_service=delivery_service,
        notification_service=StubNotificationService(),
        fingerprint_service=StubFingerprintService(duration_seconds=9.5),
        settings=settings,
    )
    session = AuthSession(
        user_id="user-1",
        email="member@example.com",
        access_token="access",
        refresh_token="refresh",
        approved=True,
    )

    try:
        service.submit_video(video, session=session)
    except RuntimeError as exc:
        assert "minimo 10 s" in str(exc)
        assert "Duracion detectada: 9.5 s" in str(exc)
    else:
        raise AssertionError("Expected short video to be rejected.")

    assert review_service.batches == []
    assert review_service.failed == []
    assert delivery_service.calls == []


def test_video_submission_marks_batch_failed_when_drive_upload_fails(tmp_path) -> None:
    video = tmp_path / "weekly.mp4"
    video.write_bytes(b"video-data")
    settings = build_settings(tmp_path)
    settings = Settings(**{**settings.__dict__, "video_submission_mode": "drive"})
    review_service = StubReviewService()
    delivery_service = StubDeliveryService(error=RuntimeError("drive caido"))
    service = VideoContributionService(
        review_service=review_service,
        extractor=StubExtractor(tmp_path),
        delivery_service=delivery_service,
        notification_service=StubNotificationService(),
        fingerprint_service=StubFingerprintService(),
        settings=settings,
    )
    session = AuthSession(
        user_id="user-1",
        email="member@example.com",
        access_token="access",
        refresh_token="refresh",
        approved=True,
    )
    progress = []

    try:
        service.submit_video(video, session=session, progress_callback=progress.append)
    except RuntimeError as exc:
        assert "No se pudo subir el video a Google Drive" in str(exc)
    else:
        raise AssertionError("Expected Drive upload failure to reject the video batch.")

    assert review_service.failed == [("batch-1", "No se pudo subir el video a Google Drive: drive caido")]
    assert review_service.finished == []
    assert [item.phase for item in progress] == ["fingerprinting", "received", "uploading", "failed"]


def test_video_submission_keeps_success_when_telegram_fails_after_drive_upload(tmp_path) -> None:
    video = tmp_path / "weekly.mp4"
    video.write_bytes(b"video-data")
    settings = build_settings(tmp_path)
    settings = Settings(**{**settings.__dict__, "video_submission_mode": "drive"})
    service = VideoContributionService(
        review_service=StubReviewService(),
        extractor=StubExtractor(tmp_path),
        delivery_service=StubDeliveryService(),
        notification_service=StubNotificationService(error=RuntimeError("chat_id invalido")),
        fingerprint_service=StubFingerprintService(),
        settings=settings,
    )
    session = AuthSession(
        user_id="user-1",
        email="member@example.com",
        access_token="access",
        refresh_token="refresh",
        approved=True,
    )

    result = service.submit_video(video, session=session)

    assert result.batch.delivery_url == "https://drive.google.com/file/d/drive-file-1/view"
    assert result.batch.status == "pending_review"
