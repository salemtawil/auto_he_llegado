from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

from core.models import ProcessLogCreate, ProcessLogUpdate
from storage.logs_repository import ProcessLogsRepository


class FakeOperation:
    def __init__(self, response_data, sink: dict, operation: str) -> None:
        self._response_data = response_data
        self._sink = sink
        self._operation = operation

    def execute(self):
        self._sink["operation"] = self._operation
        return SimpleNamespace(data=self._response_data)


class FakeQuery:
    def __init__(self, sink: dict, response_map: dict[str, list[dict]], operation: str) -> None:
        self._sink = sink
        self._response_map = response_map
        self._operation = operation

    def eq(self, field, value):
        self._sink.setdefault("eq_calls", []).append((self._operation, field, value))
        return self

    def limit(self, value):
        self._sink.setdefault("limit_calls", []).append((self._operation, value))
        return FakeOperation(self._response_map[self._operation], self._sink, self._operation)

    def execute(self):
        self._sink["operation"] = self._operation
        return SimpleNamespace(data=self._response_map[self._operation])


class FakeTable:
    def __init__(self, sink: dict, response_map: dict[str, list[dict]]) -> None:
        self._sink = sink
        self._response_map = response_map

    def insert(self, payload):
        self._sink["payload"] = payload
        return FakeOperation(self._response_map["insert"], self._sink, "insert")

    def update(self, payload):
        self._sink["payload"] = payload
        return FakeQuery(self._sink, self._response_map, "update")

    def select(self, _fields):
        return FakeQuery(self._sink, self._response_map, "select")


class FakeClient:
    def __init__(self, sink: dict, response_map: dict[str, list[dict]]) -> None:
        self._sink = sink
        self._response_map = response_map

    def table(self, table_name: str) -> FakeTable:
        self._sink["table"] = table_name
        return FakeTable(self._sink, self._response_map)


class FakeClientProvider:
    def __init__(self, sink: dict, response_map: dict[str, list[dict]]) -> None:
        self.client = FakeClient(sink, response_map)

    @staticmethod
    def execute(operation):
        return list(operation.execute().data)


class FakeSettings:
    supabase_process_logs_table = "process_logs"


def test_repositories_keep_distinct_client_providers() -> None:
    first_provider = FakeClientProvider({}, {"insert": [], "update": [], "select": []})
    second_provider = FakeClientProvider({}, {"insert": [], "update": [], "select": []})

    first_repository = ProcessLogsRepository(client_provider=first_provider, settings=FakeSettings())
    second_repository = ProcessLogsRepository(client_provider=second_provider, settings=FakeSettings())

    assert first_repository._client_provider is first_provider
    assert second_repository._client_provider is second_provider
    assert first_repository._client_provider is not second_repository._client_provider


def test_create_only_sends_real_process_logs_columns() -> None:
    sink: dict = {}
    timestamp = datetime.fromisoformat("2026-04-13T12:00:00")
    response_map = {
        "insert": [
            {
                "id": 2,
                "started_at": "2026-04-13T12:00:00",
                "finished_at": "2026-04-13T12:00:00",
                "site": "compinche.io",
                "action": "he_llegado",
                "phone": "18095551234",
                "agent_name": "Agente Local",
                "device_name": "PC-ADMIN-01",
                "station_name": "TEST_STATION",
                "block_price": "RD$ 999",
                "block_time": "3:30 PM",
                "final_status": "success",
                "phase": "testing",
                "page_message": "Test log inserted from app",
                "created_at": "2026-04-13T12:00:01",
            }
        ],
        "update": [],
        "select": [],
    }
    repository = ProcessLogsRepository(
        client_provider=FakeClientProvider(sink, response_map),
        settings=FakeSettings(),
    )

    record = repository.create(
        ProcessLogCreate(
            started_at=timestamp,
            finished_at=timestamp,
            site="compinche.io",
            action="he_llegado",
            phone="18095551234",
            agent_name="Agente Local",
            device_name="PC-ADMIN-01",
            station_name="TEST_STATION",
            block_price="RD$ 999",
            block_time="3:30 PM",
            final_status="success",
            phase="testing",
            page_message="Test log inserted from app",
            error_message=None,
            created_at=None,
        )
    )

    assert sink["table"] == "process_logs"
    assert sink["operation"] == "insert"
    assert sink["payload"] == {
        "started_at": "2026-04-13T12:00:00",
        "finished_at": "2026-04-13T12:00:00",
        "site": "compinche.io",
        "action": "he_llegado",
        "phone": "18095551234",
        "agent_name": "Agente Local",
        "device_name": "PC-ADMIN-01",
        "station_name": "TEST_STATION",
        "block_price": "RD$ 999",
        "block_time": "3:30 PM",
        "final_status": "success",
        "phase": "testing",
        "page_message": "Test log inserted from app",
    }
    assert record.site == "compinche.io"
    assert record.final_status == "success"
    assert record.id == 2


def test_update_fetches_existing_row_when_supabase_returns_empty_update_payload() -> None:
    sink: dict = {}
    response_map = {
        "insert": [],
        "update": [],
        "select": [
            {
                "id": 4,
                "started_at": "2026-04-13T12:00:00",
                "finished_at": None,
                "site": "compinche.io",
                "action": "he_llegado",
                "phone": "18095551234",
                "agent_name": "Agente Local",
                "device_name": "PC-ADMIN-01",
                "station_name": "N/A",
                "block_price": "N/A",
                "block_time": "N/A",
                "final_status": "started",
                "phase": "login",
                "page_message": "Preparando navegador",
                "created_at": "2026-04-13T12:00:01",
            }
        ],
    }
    repository = ProcessLogsRepository(
        client_provider=FakeClientProvider(sink, response_map),
        settings=FakeSettings(),
    )

    record = repository.update(
        4,
        ProcessLogUpdate(
            phase="login",
            page_message="Preparando navegador",
        ),
    )

    assert record.id == 4
    assert sink["payload"] == {
        "phase": "login",
        "page_message": "Preparando navegador",
    }
    assert ("update", "id", 4) in sink["eq_calls"]
    assert ("select", "id", 4) in sink["eq_calls"]
