from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

from core.enums import PhotoStatus
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


def test_update_filters_non_schema_fields() -> None:
    sink: dict = {}
    response_data = [
        {
            "id": "550e8400-e29b-41d4-a716-446655440000",
            "original_name": "example.jpg",
            "file_path": "available/example.jpg",
            "status": "reserved",
            "reserved_at": "2026-04-13T01:00:00",
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
            status=PhotoStatus.RESERVED,
            reserved_at=datetime.fromisoformat("2026-04-13T01:00:00"),
            error_message="should not be sent",
        ),
    )

    assert sink["operation"] == "update"
    assert sink["eq"] == ("id", "550e8400-e29b-41d4-a716-446655440000")
    assert sink["payload"] == {
        "status": "reserved",
        "reserved_at": "2026-04-13T01:00:00",
    }
