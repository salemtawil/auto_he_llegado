from __future__ import annotations

import os
import platform
import threading
import unicodedata
from collections.abc import Callable
from datetime import datetime, timezone
from time import monotonic

from automation.browser_manager import BrowserManager
from automation.compinche_site import CompincheSite
from automation.engine_router import FlowEngineRouter
from automation.engines.common import RegisteredSiteRunner
from automation.paripe_site import ParipeSite
from automation.ready4drive_site import Ready4DriveSite
from core.models import ProcessExecutionRequest, ProcessExecutionResult, SiteExecutionResult
from core.validators import sanitize_phone_number
from services.last_result_service import LastResultService
from services.local_config_service import LocalConfigService
from services.log_service import LogService


class ProcessService:
    _LOG_UPDATE_MIN_INTERVAL_SECONDS = 0.5
    _IMPORTANT_LOG_PHASES = {
        "login",
        "selfie_stage",
        "photo_upload",
        "block_read",
        "final_submit",
        "final_result",
        "unexpected",
        "finished",
    }
    _ACTION_CANONICAL_NAMES = {
        "he llegado instantaneas": "He llegado instantáneo",
        "he llegado instantaneo": "He llegado instantáneo",
    }

    def __init__(
        self,
        log_service: LogService | None = None,
        log_service_factory: Callable[[], LogService] | None = None,
        local_config_service: LocalConfigService | None = None,
        compinche_site: CompincheSite | None = None,
        paripe_site: ParipeSite | None = None,
        ready4drive_site: Ready4DriveSite | None = None,
        last_result_service: LastResultService | None = None,
        engine_router: FlowEngineRouter | None = None,
    ) -> None:
        self._log_service = log_service or LogService()
        self._log_service_factory = log_service_factory or (
            (lambda: log_service) if log_service is not None else LogService
        )
        self._local_config_service = local_config_service or LocalConfigService()
        self._last_result_service = last_result_service or LastResultService()
        self._engine_router = engine_router or FlowEngineRouter()
        # TODO(parallelism): keep execution state instance-local per run; do not share mutable site runners.
        self._site_runner_factories = {
            "Compinche": lambda: RegisteredSiteRunner(
                site_label="Compinche",
                site_host="compinche.io",
                runner=compinche_site or CompincheSite(),
            ),
            "Paripe": lambda: RegisteredSiteRunner(
                site_label="Paripe",
                site_host="paripe.io",
                runner=paripe_site or ParipeSite(),
            ),
            "Ready4Drive": lambda: RegisteredSiteRunner(
                site_label="Ready4Drive",
                site_host="ready4drive.com",
                runner=ready4drive_site or Ready4DriveSite(),
            ),
        }
        self._process_debug_exports: dict[str, dict] = {}
        self._process_debug_lock = threading.Lock()

    def shutdown(self) -> None:
        BrowserManager.shutdown_all()

    def get_process_debug_export(self, process_id: str | None) -> dict:
        if not process_id:
            return {}
        with self._process_debug_lock:
            return dict(self._process_debug_exports.get(process_id) or {})

    def execute(
        self,
        request: ProcessExecutionRequest,
        *,
        progress_callback: Callable[[str, str], None] | None = None,
    ) -> ProcessExecutionResult:
        run_log_service = self._create_run_log_service()
        sanitized_phone = sanitize_phone_number(request.phone_number)
        local_config = self._local_config_service.load()
        canonical_action_name = self._canonicalize_action_name(request.action_name)
        resolved_engine = self._resolve_execution_mode(request.execution_mode, local_config.flow_engine)
        normalized_request = request.model_copy(
            update={
                "process_id": request.process_id or f"fallback-{int(datetime.now().timestamp() * 1000)}",
                "phone_number": sanitized_phone,
                "action_name": canonical_action_name,
                "execution_mode": resolved_engine,
            }
        )
        initial_phase = "login"
        flow_engine = self._engine_router.resolve(resolved_engine)

        site_label = normalized_request.page_name.strip()
        site_runner = self._build_site_runner(site_label)
        if site_runner is None:
            return self._execute_stub(normalized_request)

        log_record = None
        log_updates_disabled = False
        log_warnings: list[str] = []
        last_log_update_at: float | None = None

        def emit_progress(phase: str, message: str) -> None:
            if progress_callback is not None:
                progress_callback(phase, message)

        def register_log_warning(message: str) -> None:
            log_warnings.append(message)
            emit_progress("log_warning", message)

        try:
            log_record = run_log_service.start_process(
                site=site_runner.site_host,
                action=normalized_request.action_name,
                phone=sanitized_phone,
                agent_name=normalized_request.agent_name,
                device_name=self._get_local_device_name(),
                phase=initial_phase,
                message=f"Iniciando automatizacion real de {site_runner.site_host}.",
            )
        except Exception as exc:
            register_log_warning(f"No se pudo crear process_logs inicial: {exc}")

        def should_write_log_update(phase: str) -> bool:
            nonlocal last_log_update_at
            now = monotonic()
            if phase in self._IMPORTANT_LOG_PHASES or last_log_update_at is None:
                last_log_update_at = now
                return True
            if (now - last_log_update_at) >= self._LOG_UPDATE_MIN_INTERVAL_SECONDS:
                last_log_update_at = now
                return True
            return False

        def emit(phase: str, message: str) -> None:
            nonlocal log_updates_disabled
            emit_progress(phase, message)
            if log_record is None or log_updates_disabled or not should_write_log_update(phase):
                return
            try:
                run_log_service.update_process(log_record.id, phase=phase, message=message)
            except Exception as exc:
                log_updates_disabled = True
                register_log_warning(
                    f"process_logs no disponible para updates en esta ejecucion: {exc}"
                )

        try:
            emit(
                initial_phase,
                f"Preparando navegador limpio para {site_runner.site_host}... Motor: {flow_engine.label}.",
            )
            site_result = flow_engine.execute_site(
                site_runner,
                request=normalized_request,
                local_config=local_config,
                progress_callback=emit,
            )
        except Exception as exc:
            message = f"Error durante la automatizacion de {site_runner.site_host}: {exc}"
            finished_log = None
            if log_record is not None:
                try:
                    finished_log = run_log_service.finish_process(
                        log_record.id,
                        phase="unexpected",
                        final_status="failed",
                        message=message,
                        error_message=message,
                    )
                except Exception as finish_exc:
                    register_log_warning(
                        f"No se pudo cerrar process_logs para esta ejecucion: {finish_exc}"
                    )
            self._store_process_debug_export(
                normalized_request.process_id,
                site_runner.runner,
                extras={"log_warnings": list(log_warnings)},
            )
            return ProcessExecutionResult(
                process_log_id=finished_log.id if finished_log is not None else None,
                process_id=normalized_request.process_id,
                page_name=normalized_request.page_name,
                action_name=normalized_request.action_name,
                phone_number=sanitized_phone,
                execution_mode=normalized_request.execution_mode,
                success=False,
                message=message,
                final_status="failed",
                phase="unexpected",
            )

        completed_at = self._utcnow()
        finished_log = None
        if log_record is not None:
            try:
                finished_log = run_log_service.finish_process(
                    log_record.id,
                    phase=site_result.phase,
                    final_status=site_result.final_status,
                    message=self._build_finish_message(site_result),
                    station_name=site_result.station_name,
                    block_price=site_result.block_price,
                    block_time=site_result.block_time,
                    error_message=site_result.message if not site_result.success else None,
                    finished_at=completed_at,
                )
            except Exception as finish_exc:
                register_log_warning(
                    f"No se pudo cerrar process_logs para esta ejecucion: {finish_exc}"
                )

        self._store_process_debug_export(
            normalized_request.process_id,
            site_runner.runner,
            extras={"log_warnings": list(log_warnings)},
        )
        result = ProcessExecutionResult(
            process_id=normalized_request.process_id,
            process_log_id=finished_log.id if finished_log is not None else None,
            page_name=normalized_request.page_name,
            action_name=normalized_request.action_name,
            phone_number=sanitized_phone,
            agent_name=normalized_request.agent_name,
            execution_mode=normalized_request.execution_mode,
            success=site_result.success,
            message=site_result.message,
            final_status=site_result.final_status,
            phase=site_result.phase,
            station_name=site_result.station_name,
            block_price=site_result.block_price,
            block_time=site_result.block_time,
            block_duration=site_result.block_duration,
            selfie_retry_count=site_result.selfie_retry_count,
            deepfakescore_retries=site_result.deepfakescore_retries or site_result.selfie_retry_count,
            deepfakescore_activated=site_result.deepfakescore_activated,
            completed_at=completed_at,
        )
        self._last_result_service.save_result(result)
        return result

    def _build_finish_message(self, site_result: SiteExecutionResult) -> str:
        retry_suffix = (
            f" Reintentos selfie: {site_result.selfie_retry_count}. "
            f"Deepfakescore: {'activado' if site_result.deepfakescore_activated else 'no activado'}."
        )
        return f"{site_result.message}{retry_suffix}"

    def _execute_stub(self, request: ProcessExecutionRequest) -> ProcessExecutionResult:
        log_record = self._log_service.log_info(
            site=request.page_name,
            action=request.action_name,
            phone=request.phone_number,
            agent_name=request.agent_name,
            device_name="LOCAL_UI",
            station_name="MAIN_APP",
            block_price="N/A",
            block_time="N/A",
            phase="stub_validation",
            message=(
                "Proceso registrado sin automatizacion web. "
                "El sitio seleccionado todavia no tiene integracion activa en esta fase."
            ),
            final_status="success",
        )
        return ProcessExecutionResult(
            process_id=request.process_id,
            process_log_id=log_record.id,
            page_name=request.page_name,
            action_name=request.action_name,
            phone_number=request.phone_number,
            agent_name=request.agent_name,
            execution_mode=request.execution_mode,
            success=True,
            message=(
                "Solicitud preparada correctamente. "
                "La automatizacion real todavia no esta implementada para este sitio."
            ),
            final_status="success",
            phase="stub_validation",
        )

    def _build_site_runner(self, site_label: str) -> RegisteredSiteRunner | None:
        factory = self._site_runner_factories.get(site_label)
        if factory is None:
            return None
        return factory()

    def _create_run_log_service(self) -> LogService:
        return self._log_service_factory()

    def _store_process_debug_export(self, process_id: str | None, runner, *, extras: dict | None = None) -> None:
        if not process_id:
            return
        payload: dict = {}
        export_debug = getattr(runner, "export_process_debug_state", None)
        if callable(export_debug):
            try:
                exported = export_debug()
            except Exception:
                exported = {}
            if isinstance(exported, dict):
                payload = dict(exported)
        if isinstance(extras, dict):
            payload.update(extras)
        payload["process_id"] = process_id
        with self._process_debug_lock:
            self._process_debug_exports[process_id] = payload

    @staticmethod
    def _get_local_device_name() -> str:
        return os.getenv("COMPUTERNAME") or platform.node().strip() or "UNKNOWN_DEVICE"

    @staticmethod
    def _utcnow() -> datetime:
        return datetime.now(timezone.utc)

    @classmethod
    def _canonicalize_action_name(cls, action_name: str) -> str:
        normalized = unicodedata.normalize("NFKD", action_name)
        normalized = normalized.encode("ascii", "ignore").decode("ascii")
        normalized = " ".join(normalized.strip().lower().split())
        return cls._ACTION_CANONICAL_NAMES.get(normalized, action_name.strip())

    @staticmethod
    def _resolve_execution_mode(request_mode: str, config_mode: str) -> str:
        normalized_request = (request_mode or "").strip().lower()
        if normalized_request in {"traditional", "extension"}:
            return normalized_request
        normalized_config = (config_mode or "").strip().lower()
        if normalized_config in {"traditional", "extension"}:
            return normalized_config
        return "traditional"
