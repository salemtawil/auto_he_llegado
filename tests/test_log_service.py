from services.log_service import LogService


class StubLogsRepository:
    def __init__(self) -> None:
        self.created_entries = []
        self.updated_entries = []
        self.create_error = None
        self.update_error = None

    def create(self, log_entry):
        if self.create_error is not None:
            raise self.create_error
        self.created_entries.append(log_entry)
        return type("StubLogRecord", (), {"id": 123})()

    def update(self, log_id, changes):
        if self.update_error is not None:
            raise self.update_error
        self.updated_entries.append((log_id, changes))
        return type("StubLogRecord", (), {"id": log_id})()


class FlakyLogsRepository(StubLogsRepository):
    def __init__(self, *, create_error: Exception | None = None, update_error: Exception | None = None) -> None:
        super().__init__()
        self.create_error = create_error
        self.update_error = update_error


def test_insert_test_log_builds_expected_payload() -> None:
    repository = StubLogsRepository()
    service = LogService(logs_repository=repository)

    result = service.insert_test_log(
        agent_name="Agente Local",
        device_name="PC-ADMIN-01",
    )

    entry = repository.created_entries[0]

    assert result.id == 123
    assert entry.site == "compinche.io"
    assert entry.action == "he_llegado"
    assert entry.phone == "18095551234"
    assert entry.agent_name == "Agente Local"
    assert entry.device_name == "PC-ADMIN-01"
    assert entry.station_name == "TEST_STATION"
    assert entry.block_price == "RD$ 999"
    assert entry.block_time == "3:30 PM"
    assert entry.final_status == "success"
    assert entry.phase == "testing"
    assert entry.page_message == "Test log inserted from app"
    assert entry.error_message is None
    assert entry.started_at is not None
    assert entry.finished_at is not None


def test_start_update_and_finish_process_use_repository_update() -> None:
    repository = StubLogsRepository()
    service = LogService(logs_repository=repository)

    started = service.start_process(
        site="compinche.io",
        action="He llegado",
        phone="18095551234",
        agent_name="Agente Local",
        device_name="PC-01",
        phase="login",
        message="Iniciando",
    )
    updated = service.update_process(
        started.id,
        phase="photo_upload",
        message="Subiendo foto",
        station_name="E1",
        block_price="RD$ 100",
        block_time="3:30 PM",
    )
    finished = service.finish_process(
        started.id,
        phase="final_result",
        final_status="success",
        message="Completado",
        station_name="E1",
        block_price="RD$ 100",
        block_time="3:30 PM",
    )

    assert started.id == 123
    assert updated.id == 123
    assert finished.id == 123
    assert repository.created_entries[0].final_status == "started"
    assert repository.updated_entries[0][0] == 123
    assert repository.updated_entries[0][1].phase == "photo_upload"
    assert repository.updated_entries[0][1].page_message == "Subiendo foto"
    assert repository.updated_entries[1][1].final_status == "success"
    assert repository.updated_entries[1][1].finished_at is not None


def test_start_process_wraps_repository_failure_with_phase_context() -> None:
    repository = StubLogsRepository()
    repository.create_error = RuntimeError("insert without row")
    service = LogService(logs_repository=repository)

    try:
        service.start_process(
            site="compinche.io",
            action="He llegado",
            phone="18095551234",
            agent_name="Agente Local",
            device_name="PC-01",
            phase="login",
            message="Iniciando",
        )
    except RuntimeError as exc:
        assert "crear el log inicial" in str(exc)
        assert "fase 'login'" in str(exc)
    else:
        raise AssertionError("Expected start_process to raise a contextual RuntimeError.")


def test_start_process_retries_with_fresh_repository_when_error_is_transient() -> None:
    created_repositories = []

    def build_repository():
        repository = FlakyLogsRepository(
            create_error=RuntimeError("Supabase operation failed: Server disconnected")
            if not created_repositories
            else None
        )
        created_repositories.append(repository)
        return repository

    service = LogService(logs_repository_factory=build_repository, sleep_func=lambda _: None)

    result = service.start_process(
        site="compinche.io",
        action="He llegado",
        phone="18095551234",
        agent_name="Agente Local",
        device_name="PC-01",
        phase="login",
        message="Iniciando",
    )

    assert result.id == 123
    assert len(created_repositories) == 2
    assert len(created_repositories[0].created_entries) == 0
    assert len(created_repositories[1].created_entries) == 1


def test_update_process_retries_with_fresh_repository_when_error_is_transient() -> None:
    created_repositories = []

    def build_repository():
        repository = FlakyLogsRepository(
            update_error=RuntimeError("Supabase operation failed: timeout")
            if not created_repositories
            else None
        )
        created_repositories.append(repository)
        return repository

    service = LogService(logs_repository_factory=build_repository, sleep_func=lambda _: None)

    result = service.update_process(
        99,
        phase="photo_upload",
        message="Subiendo foto",
    )

    assert result.id == 99
    assert len(created_repositories) == 2
    assert len(created_repositories[0].updated_entries) == 0
    assert created_repositories[1].updated_entries[0][0] == 99
