from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

from core.enums import PhotoStatus
from core.exceptions import ValidationError
from core.models import PhotoCreate, PhotoUpdate
from storage.photos_repository import PhotosRepository


class FakeOperation:
    def __init__(self, response_data, sink: dict, operation: str) -> None:
        self._response_data = response_data
        self._sink = sink
        self._operation = operation

    def execute(self):
        self._sink["operation"] = self._operation
        return SimpleNamespace(data=self._response_data)


class FakeTable:
    def __init__(self, sink: dict, response_data) -> None:
        self._sink = sink
        self._response_data = response_data

    def insert(self, payload):
        self._sink["payload"] = payload
        return FakeOperation(self._response_data, self._sink, "insert")

    def update(self, payload):
        self._sink["payload"] = payload
        return self

    def eq(self, field, value):
        self._sink["eq"] = (field, value)
        return FakeOperation(self._response_data, self._sink, "update")


class FakeClient:
    def __init__(self, sink: dict, response_data) -> None:
        self._sink = sink
        self._response_data = response_data

    def table(self, table_name: str) -> FakeTable:
        self._sink["table"] = table_name
        return FakeTable(self._sink, self._response_data)


class FakeClientProvider:
    def __init__(self, sink: dict, response_data) -> None:
        self.client = FakeClient(sink, response_data)

    @staticmethod
    def execute(operation):
        return list(operation.execute().data)


class FakeSettings:
    supabase_photos_table = "photos"


def test_create_only_sends_real_photos_columns() -> None:
    sink: dict = {}
    response_data = [
        {
            "id": "550e8400-e29b-41d4-a716-446655440000",
            "original_name": "example.jpg",
            "file_path": "available/example.jpg",
            "status": "available",
            "created_at": "2026-04-13T00:00:00",
        }
    ]
    repository = PhotosRepository(
        client_provider=FakeClientProvider(sink, response_data),
        settings=FakeSettings(),
    )

    record = repository.create(
        PhotoCreate(
            id="550e8400-e29b-41d4-a716-446655440000",
            original_filename="example.jpg",
            storage_path="available/example.jpg",
            status=PhotoStatus.AVAILABLE,
            source="uploader_app",
            metadata={"debug": True},
            error_message="should not be sent",
        )
    )

    assert sink["table"] == "photos"
    assert sink["operation"] == "insert"
    assert sink["payload"] == {
        "id": "550e8400-e29b-41d4-a716-446655440000",
        "original_name": "example.jpg",
        "file_path": "available\\example.jpg",
        "status": "available",
    }
    assert record.original_filename == "example.jpg"
    assert record.storage_path == "available\\example.jpg"


def test_bulk_create_only_sends_confirmed_photos_columns() -> None:
    sink: dict = {}
    response_data = [
        {
            "id": "550e8400-e29b-41d4-a716-446655440000",
            "original_name": "one.jpg",
            "file_path": "available/one.jpg",
            "status": "available",
            "created_at": "2026-04-13T00:00:00",
        },
        {
            "id": "550e8400-e29b-41d4-a716-446655440001",
            "original_name": "two.jpg",
            "file_path": "available/two.jpg",
            "status": "available",
            "created_at": "2026-04-13T00:00:01",
        },
    ]
    repository = PhotosRepository(
        client_provider=FakeClientProvider(sink, response_data),
        settings=FakeSettings(),
    )

    records = repository.bulk_create(
        [
            PhotoCreate(
                id="550e8400-e29b-41d4-a716-446655440000",
                original_filename="one.jpg",
                storage_path="available/one.jpg",
                status=PhotoStatus.AVAILABLE,
                source="uploader_app",
                metadata={"ignored": True},
            ),
            PhotoCreate(
                id="550e8400-e29b-41d4-a716-446655440001",
                original_filename="two.jpg",
                storage_path="available/two.jpg",
                status=PhotoStatus.AVAILABLE,
                error_message="ignored",
            ),
        ]
    )

    assert sink["payload"] == [
        {
            "id": "550e8400-e29b-41d4-a716-446655440000",
            "original_name": "one.jpg",
            "file_path": "available\\one.jpg",
            "status": "available",
        },
        {
            "id": "550e8400-e29b-41d4-a716-446655440001",
            "original_name": "two.jpg",
            "file_path": "available\\two.jpg",
            "status": "available",
        },
    ]
    assert [record.id for record in records] == [
        "550e8400-e29b-41d4-a716-446655440000",
        "550e8400-e29b-41d4-a716-446655440001",
    ]


def test_update_sends_confirmed_cleanup_columns() -> None:
    sink: dict = {}
    response_data = [
        {
            "id": "550e8400-e29b-41d4-a716-446655440000",
            "original_name": "example.jpg",
            "file_path": "available/example.jpg",
            "status": "discarded",
            "reserved_by_process_id": None,
            "storage_deleted_at": "2026-04-13T01:00:00+00:00",
            "cleanup_reason": "stale_reserved_cleanup",
            "cleanup_error": None,
            "cleaned_by": "admin_cleanup",
            "created_at": "2026-04-13T00:00:00",
        }
    ]
    repository = PhotosRepository(
        client_provider=FakeClientProvider(sink, response_data),
        settings=FakeSettings(),
    )

    repository.update(
        "550e8400-e29b-41d4-a716-446655440000",
        PhotoUpdate(
            status=PhotoStatus.DISCARDED,
            reserved_by_process_id=None,
            storage_deleted_at=datetime.fromisoformat("2026-04-13T01:00:00+00:00"),
            cleanup_reason="stale_reserved_cleanup",
            cleanup_error=None,
            cleaned_by="admin_cleanup",
        ),
    )

    assert sink["operation"] == "update"
    assert sink["eq"] == ("id", "550e8400-e29b-41d4-a716-446655440000")
    assert sink["payload"] == {
        "status": "discarded",
        "reserved_by_process_id": None,
        "storage_deleted_at": "2026-04-13T01:00:00Z",
        "cleanup_reason": "stale_reserved_cleanup",
        "cleanup_error": None,
        "cleaned_by": "admin_cleanup",
    }


def test_update_status_rejects_unconfirmed_error_message_column() -> None:
    repository = PhotosRepository(
        client_provider=FakeClientProvider({}, []),
        settings=FakeSettings(),
    )

    try:
        repository.update_status(
            "550e8400-e29b-41d4-a716-446655440000",
            PhotoStatus.RESERVED,
            error_message="not supported by confirmed schema",
        )
    except ValidationError as exc:
        assert "error_message" in str(exc)
    else:
        raise AssertionError("Expected update_status to reject error_message.")
