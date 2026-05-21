from __future__ import annotations

from datetime import datetime, timezone
from time import sleep
from typing import Callable

from core.models import ProcessLogCreate, ProcessLogRecord, ProcessLogUpdate
from core.validators import validate_non_empty_string
from storage.logs_repository import ProcessLogsRepository


class LogService:
    _WRITE_RETRY_DELAYS = (0.2, 0.5, 1.0)
    _TRANSIENT_ERROR_MARKERS = (
        "server disconnected",
        "connection reset",
        "timeout",
        "temporarily unavailable",
        "network error",
        "httpx",
        "httpcore",
        "remoteprotocolerror",
        "readerror",
        "writeerror",
        "connecterror",
    )

    def __init__(
        self,
        logs_repository: ProcessLogsRepository | None = None,
        logs_repository_factory: Callable[[], ProcessLogsRepository] | None = None,
        sleep_func: Callable[[float], None] = sleep,
    ) -> None:
        if logs_repository is not None and logs_repository_factory is not None:
            raise ValueError("Provide either 'logs_repository' or 'logs_repository_factory', not both.")
        self._logs_repository_factory = logs_repository_factory or (
            (lambda: logs_repository) if logs_repository is not None else ProcessLogsRepository
        )
        self._logs_repository = logs_repository or self._logs_repository_factory()
        self._sleep = sleep_func

    def start_process(
        self,
        *,
        site: str,
        action: str,
        phone: str,
        agent_name: str,
        device_name: str,
        phase: str,
        message: str,
    ) -> ProcessLogRecord:
        timestamp = self._utcnow()
        try:
            return self._retry_log_operation(
                lambda repository: repository.create(
                    ProcessLogCreate(
                        started_at=timestamp,
                        finished_at=None,
                        site=site,
                        action=action,
                        phone=phone,
                        agent_name=agent_name,
                        device_name=device_name,
                        station_name="N/A",
                        block_price="N/A",
                        block_time="N/A",
                        final_status="started",
                        phase=phase,
                        page_message=message,
                        error_message=None,
                    )
                )
            )
        except Exception as exc:
            raise RuntimeError(
                f"No se pudo crear el log inicial en process_logs durante la fase '{phase}': {exc}"
            ) from exc

    def update_process(
        self,
        log_id: int,
        *,
        phase: str,
        message: str,
        station_name: str | None = None,
        block_price: str | None = None,
        block_time: str | None = None,
    ) -> ProcessLogRecord:
        try:
            return self._retry_log_operation(
                lambda repository: repository.update(
                    log_id,
                    ProcessLogUpdate(
                        phase=phase,
                        page_message=message,
                        station_name=station_name,
                        block_price=block_price,
                        block_time=block_time,
                    ),
                ),
            )
        except Exception as exc:
            raise RuntimeError(
                f"No se pudo actualizar process_logs para log_id={log_id} en la fase '{phase}': {exc}"
            ) from exc

    def finish_process(
        self,
        log_id: int,
        *,
        phase: str,
        final_status: str,
        message: str,
        station_name: str = "N/A",
        block_price: str = "N/A",
        block_time: str = "N/A",
        error_message: str | None = None,
        finished_at: datetime | None = None,
    ) -> ProcessLogRecord:
        try:
            return self._retry_log_operation(
                lambda repository: repository.update(
                    log_id,
                    ProcessLogUpdate(
                        finished_at=finished_at or self._utcnow(),
                        phase=phase,
                        final_status=final_status,
                        page_message=message,
                        error_message=error_message,
                        station_name=station_name,
                        block_price=block_price,
                        block_time=block_time,
                    ),
                ),
            )
        except Exception as exc:
            raise RuntimeError(
                f"No se pudo cerrar process_logs para log_id={log_id} en la fase '{phase}': {exc}"
            ) from exc

    def log_info(
        self,
        *,
        site: str,
        action: str,
        phone: str,
        agent_name: str,
        device_name: str,
        station_name: str,
        block_price: str,
        block_time: str,
        phase: str,
        message: str,
        final_status: str = "success",
    ) -> ProcessLogRecord:
        return self._logs_repository.create(
            ProcessLogCreate(
                started_at=self._utcnow(),
                finished_at=self._utcnow(),
                site=site,
                action=action,
                phone=phone,
                agent_name=agent_name,
                device_name=device_name,
                station_name=station_name,
                block_price=block_price,
                block_time=block_time,
                final_status=final_status,
                phase=phase,
                page_message=message,
                error_message=None,
            )
        )

    def log_error(
        self,
        *,
        site: str,
        action: str,
        phone: str,
        agent_name: str,
        device_name: str,
        station_name: str,
        block_price: str,
        block_time: str,
        phase: str,
        message: str,
    ) -> ProcessLogRecord:
        return self._logs_repository.create(
            ProcessLogCreate(
                started_at=self._utcnow(),
                finished_at=self._utcnow(),
                site=site,
                action=action,
                phone=phone,
                agent_name=agent_name,
                device_name=device_name,
                station_name=station_name,
                block_price=block_price,
                block_time=block_time,
                final_status="failed",
                phase=phase,
                page_message=message,
                error_message=message,
            )
        )

    def list_recent(
        self,
        *,
        limit: int = 10,
        only_successful: bool = False,
    ) -> list[ProcessLogRecord]:
        return self._logs_repository.list_recent(
            limit=limit,
            final_status="success" if only_successful else None,
        )

    def insert_test_log(
        self,
        *,
        agent_name: str,
        device_name: str,
    ) -> ProcessLogRecord:
        validated_agent_name = validate_non_empty_string(agent_name, "agent_name")
        validated_device_name = validate_non_empty_string(device_name, "device_name")
        timestamp = self._utcnow()
        return self._logs_repository.create(
            ProcessLogCreate(
                started_at=timestamp,
                finished_at=timestamp,
                site="compinche.io",
                action="he_llegado",
                phone="18095551234",
                agent_name=validated_agent_name,
                device_name=validated_device_name,
                station_name="TEST_STATION",
                block_price="RD$ 999",
                block_time="3:30 PM",
                final_status="success",
                phase="testing",
                page_message="Test log inserted from app",
                error_message=None,
            )
        )

    @staticmethod
    def _utcnow() -> datetime:
        return datetime.now(timezone.utc)

    def _retry_log_operation(
        self,
        operation: Callable[[ProcessLogsRepository], ProcessLogRecord],
    ) -> ProcessLogRecord:
        attempts = len(self._WRITE_RETRY_DELAYS) + 1
        last_error: Exception | None = None
        for attempt_index in range(attempts):
            repository = self._create_write_repository(attempt_index)
            try:
                return operation(repository)
            except Exception as exc:
                last_error = exc
                if attempt_index >= len(self._WRITE_RETRY_DELAYS) or not self._is_transient_error(exc):
                    raise
                self._sleep(self._WRITE_RETRY_DELAYS[attempt_index])
        if last_error is not None:
            raise last_error
        raise RuntimeError("Log write retry finished without a result or captured error.")

    def _create_write_repository(self, attempt_index: int) -> ProcessLogsRepository:
        if attempt_index == 0:
            return self._logs_repository
        return self._logs_repository_factory()

    @classmethod
    def _is_transient_error(cls, exc: Exception) -> bool:
        message = str(exc).lower()
        return any(marker in message for marker in cls._TRANSIENT_ERROR_MARKERS)
