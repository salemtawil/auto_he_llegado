from __future__ import annotations

from pathlib import Path

from config.settings import Settings
from core.enums import PhotoStatus
from services.auth_context import AuthSession
from services.photo_review_service import PhotoCandidateRecord, PhotoReviewService


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


class StubClientProvider:
    def __init__(self) -> None:
        self.moves = []
        self.removes = []

    def move_file(self, *, bucket_name: str, from_path: str, to_path: str) -> None:
        self.moves.append((bucket_name, from_path, to_path))

    def remove_files(self, *, bucket_name: str, storage_paths: list[str]) -> None:
        self.removes.append((bucket_name, tuple(storage_paths)))


class StubPhotosRepository:
    def __init__(self) -> None:
        self.bulk_created = []

    def bulk_create(self, photos):
        self.bulk_created.append(list(photos))
        return []


def make_candidate(candidate_id: str, *, batch_id: str = "batch-1") -> PhotoCandidateRecord:
    return PhotoCandidateRecord(
        id=candidate_id,
        batch_id=batch_id,
        user_id="user-1",
        storage_path=f"candidates/user-1/{batch_id}/{candidate_id}.jpg",
        original_name=f"{candidate_id}.jpg",
        frame_index=1,
        timestamp_seconds=1.0,
        blur_score=50.0,
        brightness_score=120.0,
        status="pending",
    )


def test_approve_candidates_moves_storage_and_bulk_creates_photos(tmp_path, monkeypatch) -> None:
    client_provider = StubClientProvider()
    repository = StubPhotosRepository()
    service = PhotoReviewService(
        client_provider=client_provider,
        photos_repository=repository,
        settings=build_settings(tmp_path),
    )
    candidates = [make_candidate("candidate-1"), make_candidate("candidate-2")]
    upserts = []
    refreshed_batches = []
    monkeypatch.setattr(service, "_get_candidates_by_ids", lambda _ids: candidates)
    monkeypatch.setattr(service, "_bulk_upsert_candidates", lambda payload: upserts.extend(payload) or candidates)
    monkeypatch.setattr(service, "_refresh_many_batch_counts", lambda batch_ids: refreshed_batches.extend(batch_ids))

    service.approve_candidates(
        ["candidate-1", "candidate-2"],
        reviewer=AuthSession(user_id="admin-1", email="admin@example.com", access_token="a", refresh_token="r"),
    )

    assert [move[0] for move in client_provider.moves] == ["photo-pool", "photo-pool"]
    assert client_provider.moves[0][1] == "candidates/user-1/batch-1/candidate-1.jpg"
    assert client_provider.moves[0][2].startswith("available/")
    assert len(repository.bulk_created) == 1
    assert [photo.status for photo in repository.bulk_created[0]] == [PhotoStatus.AVAILABLE, PhotoStatus.AVAILABLE]
    assert [item["status"] for item in upserts] == ["approved", "approved"]
    assert refreshed_batches == ["batch-1"]


def test_reject_candidates_removes_storage_in_bulk_and_updates_candidates(tmp_path, monkeypatch) -> None:
    client_provider = StubClientProvider()
    service = PhotoReviewService(
        client_provider=client_provider,
        photos_repository=StubPhotosRepository(),
        settings=build_settings(tmp_path),
    )
    candidates = [make_candidate("candidate-1"), make_candidate("candidate-2")]
    upserts = []
    refreshed_batches = []
    monkeypatch.setattr(service, "_get_candidates_by_ids", lambda _ids: candidates)
    monkeypatch.setattr(service, "_bulk_upsert_candidates", lambda payload: upserts.extend(payload) or candidates)
    monkeypatch.setattr(service, "_refresh_many_batch_counts", lambda batch_ids: refreshed_batches.extend(batch_ids))

    service.reject_candidates(
        ["candidate-1", "candidate-2"],
        reviewer=AuthSession(user_id="admin-1", email="admin@example.com", access_token="a", refresh_token="r"),
    )

    assert client_provider.removes == [
        (
            "photo-pool",
            (
                "candidates/user-1/batch-1/candidate-1.jpg",
                "candidates/user-1/batch-1/candidate-2.jpg",
            ),
        )
    ]
    assert [item["status"] for item in upserts] == ["deleted", "deleted"]
    assert refreshed_batches == ["batch-1"]
