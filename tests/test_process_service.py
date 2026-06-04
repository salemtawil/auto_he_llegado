from core.models import LocalConfig, ProcessExecutionRequest, SiteExecutionResult
from services.process_service import ProcessService
from services.process_run_context import RunStatsRecorder


class StubLogRecord:
    def __init__(self, log_id: int) -> None:
        self.id = log_id


class StubLogService:
    def __init__(self) -> None:
        self.start_calls = []
        self.update_calls = []
        self.finish_calls = []
        self.info_calls = []
        self.start_error = None
        self.update_error = None
        self.finish_error = None

    def start_process(self, **kwargs):
        if self.start_error is not None:
            raise self.start_error
        self.start_calls.append(kwargs)
        return StubLogRecord(77)

    def update_process(self, log_id, **kwargs):
        if self.update_error is not None:
            raise self.update_error
        self.update_calls.append((log_id, kwargs))
        return StubLogRecord(log_id)

    def finish_process(self, log_id, **kwargs):
        if self.finish_error is not None:
            raise self.finish_error
        self.finish_calls.append((log_id, kwargs))
        return StubLogRecord(log_id)

    def log_info(self, **kwargs):
        self.info_calls.append(kwargs)
        return StubLogRecord(15)


class StubLocalConfigService:
    def load(self) -> LocalConfig:
        return LocalConfig(
            agent_name="Agente Local",
            flow_engine="traditional",
            page_timeout_seconds=45,
            action_timeout_seconds=25,
            max_selfie_retries=10,
            theme_mode="light",
        )


class StubLastResultService:
    def __init__(self) -> None:
        self.saved_results = []

    def save_result(self, result) -> None:
        self.saved_results.append(result)


class StubCompincheSite:
    def __init__(self, result: SiteExecutionResult) -> None:
        self.result = result
        self.execute_calls = []
        self.debug_export = {}

    def execute_traditional(self, request, *, local_config, progress_callback):
        self.execute_calls.append(("traditional", request, local_config))
        progress_callback("photo_upload", "Subiendo foto reservada...")
        return self.result

    def execute_extension(self, request, *, local_config, progress_callback):
        self.execute_calls.append(("extension", request, local_config))
        progress_callback("photo_upload", "Subiendo foto reservada...")
        return self.result

    def export_process_debug_state(self):
        return dict(self.debug_export)


class StubParipeSite:
    def __init__(self, result: SiteExecutionResult) -> None:
        self.result = result
        self.execute_calls = []
        self.debug_export = {}

    def execute_traditional(self, request, *, local_config, progress_callback):
        self.execute_calls.append(("traditional", request, local_config))
        progress_callback("block_read", "Leyendo bloque de paripe...")
        return self.result

    def execute_extension(self, request, *, local_config, progress_callback):
        self.execute_calls.append(("extension", request, local_config))
        progress_callback("block_read", "Leyendo bloque de paripe...")
        return self.result

    def export_process_debug_state(self):
        return dict(self.debug_export)


class StubReady4DriveSite:
    def __init__(self, result: SiteExecutionResult) -> None:
        self.result = result
        self.execute_calls = []
        self.debug_export = {}

    def execute_traditional(self, request, *, local_config, progress_callback):
        self.execute_calls.append(("traditional", request, local_config))
        progress_callback("site_bootstrap", "Base inicial de ready4drive.")
        return self.result

    def execute_extension(self, request, *, local_config, progress_callback):
        self.execute_calls.append(("extension", request, local_config))
        progress_callback("site_bootstrap", "Base inicial de ready4drive.")
        return self.result

    def export_process_debug_state(self):
        return dict(self.debug_export)


class StubDebugRunner:
    def __init__(self, export_payload: dict | None = None) -> None:
        self.debug_export = dict(export_payload or {})

    def export_process_debug_state(self):
        return dict(self.debug_export)


def test_execute_finish_message_prioritizes_run_stats_summary_over_local_timing_summary() -> None:
    log_service = StubLogService()
    site = StubCompincheSite(
        SiteExecutionResult(
            success=True,
            message="Proceso completado correctamente en compinche.io.",
            final_status="success",
            phase="final_result",
        )
    )
    site.debug_export = {"timing_summary_text": "Resumen tiempos: fallback local"}
    service = ProcessService(
        log_service_factory=build_log_service_factory(log_service),
        local_config_service=StubLocalConfigService(),
        compinche_site=site,
        paripe_site=StubParipeSite(
            SiteExecutionResult(success=True, message="unused", final_status="success", phase="final_result")
        ),
    )

    result = service.execute(
        ProcessExecutionRequest(
            page_name="Compinche",
            action_name="He llegado",
            phone_number="8095551234",
            password="secret",
            agent_name="Agente Local",
            execution_mode="normal",
        )
    )

    assert result.success is True
    finish_message = log_service.finish_calls[0][1]["message"]
    assert "Resumen tiempos:" in finish_message
    assert "fallback local" not in finish_message
    assert "login" in finish_message


def test_run_stats_common_summary_text_includes_intermediate_phases_when_available() -> None:
    recorder = RunStatsRecorder()
    for event in (
        "process_started",
        "login_started",
        "login_done",
        "photo_prepare_started",
        "photo_prepare_done",
        "selfie_input_detected",
        "photo_upload_started",
        "photo_upload_done",
        "continue_clicked",
        "block_visual_detected",
        "final_click_done",
        "final_result_done",
        "process_finished",
    ):
        recorder.record(event)

    summary = recorder.build_common_timing_summary()
    summary_text = recorder.build_common_timing_summary_text()

    assert summary["login"] != "N/A"
    assert summary["foto_prep"] != "N/A"
    assert summary["inputupload"] != "N/A"
    assert summary["photo_upload"] != "N/A"
    assert summary["validacion_sitio"] != "N/A"
    assert summary["bloqueclick"] != "N/A"
    assert summary["resultado_final"] != "N/A"
    assert "photo upload" in summary_text
    assert "validacion sitio" in summary_text
    assert "bloqueclick" in summary_text


def test_run_stats_common_summary_uses_fallback_events_without_old_duplicate_labels() -> None:
    recorder = RunStatsRecorder()
    for event in (
        "process_started",
        "login_started",
        "login_done",
        "continue_clicked",
        "block_detected",
        "final_click_done",
        "final_result_started",
        "final_result_done",
        "process_finished",
    ):
        recorder.record(event)

    summary = recorder.build_common_timing_summary()
    summary_text = recorder.build_common_timing_summary_text()

    assert summary["validacion_sitio"] != "N/A"
    assert summary["bloqueclick"] != "N/A"
    assert summary["resultado_final"] != "N/A"
    assert "selfie " not in summary_text
    assert "bloque " not in summary_text


def test_run_stats_total_prefers_final_result_done_over_late_process_finished() -> None:
    recorder = RunStatsRecorder()
    recorder.record("process_started")
    recorder.record("final_result_done")
    recorder.record("process_finished")

    summary = recorder.build_common_timing_summary()

    assert summary["total"] != "N/A"


def build_log_service_factory(log_service: StubLogService):
    return lambda: log_service


def test_execute_compinche_runs_real_site_and_finishes_log() -> None:
    log_service = StubLogService()
    last_result_service = StubLastResultService()
    site = StubCompincheSite(
        SiteExecutionResult(
            success=True,
            message="Proceso completado correctamente en compinche.io.",
            final_status="success",
            phase="final_result",
            station_name="Estacion Central",
            block_price="RD$ 300",
            block_time="3:30 PM",
            block_duration="3 horas",
            deepfakescore_retries=2,
            reserved_photo_id="photo-1",
        )
    )
    service = ProcessService(
        log_service_factory=build_log_service_factory(log_service),
        local_config_service=StubLocalConfigService(),
        last_result_service=last_result_service,
        compinche_site=site,
        paripe_site=StubParipeSite(
            SiteExecutionResult(
                success=True,
                message="unused",
                final_status="success",
                phase="final_result",
            )
        ),
    )
    progress_events = []

    result = service.execute(
        ProcessExecutionRequest(
            page_name="Compinche",
            action_name="He llegado",
            phone_number="+1 (809) 555-1234",
            password="secret",
            agent_name="Agente Local",
            execution_mode="normal",
        ),
        progress_callback=lambda phase, message: progress_events.append((phase, message)),
    )

    assert result.process_log_id == 77
    assert result.success is True
    assert result.final_status == "success"
    assert result.station_name == "Estacion Central"
    assert log_service.start_calls[0]["site"] == "compinche.io"
    assert log_service.update_calls[0][1]["phase"] == "login"
    assert log_service.update_calls[1][1]["phase"] == "photo_upload"
    assert log_service.finish_calls[0][1]["final_status"] == "success"
    assert last_result_service.saved_results[0].phone_number == "8095551234"
    assert last_result_service.saved_results[0].action_name == "He llegado"
    assert last_result_service.saved_results[0].deepfakescore_retries == 2
    assert progress_events == [
        ("login", "Preparando navegador limpio para compinche.io... Motor: Tradicional."),
        ("photo_upload", "Subiendo foto reservada..."),
    ]


def test_execute_ready4drive_uses_initial_site_base_and_does_not_fallback_to_stub() -> None:
    log_service = StubLogService()
    ready4drive_site = StubReady4DriveSite(
        SiteExecutionResult(
            success=False,
            message="Base inicial de ready4drive.",
            final_status="not_implemented",
            phase="site_bootstrap",
        )
    )
    service = ProcessService(
        log_service_factory=build_log_service_factory(log_service),
        local_config_service=StubLocalConfigService(),
        compinche_site=StubCompincheSite(
            SiteExecutionResult(
                success=True,
                message="unused",
                final_status="success",
                phase="final_result",
            )
        ),
        paripe_site=StubParipeSite(
            SiteExecutionResult(
                success=True,
                message="unused",
                final_status="success",
                phase="final_result",
            )
        ),
        ready4drive_site=ready4drive_site,
    )

    result = service.execute(
        ProcessExecutionRequest(
            page_name="Ready4Drive",
            action_name="He llegado",
            phone_number="8095551234",
            password="secret",
            agent_name="Agente Local",
            execution_mode="normal",
        )
    )

    assert result.success is False
    assert result.phase == "site_bootstrap"
    assert log_service.start_calls[0]["site"] == "ready4drive.com"
    assert ready4drive_site.execute_calls[0][0] == "traditional"
    assert ready4drive_site.execute_calls[0][1].page_name == "Ready4Drive"


def test_execute_compinche_continues_when_initial_log_creation_fails() -> None:
    log_service = StubLogService()
    log_service.start_error = RuntimeError("Server disconnected")
    site = StubCompincheSite(
        SiteExecutionResult(
            success=True,
            message="Proceso completado sin process_logs.",
            final_status="success",
            phase="final_result",
        )
    )
    service = ProcessService(
        log_service_factory=build_log_service_factory(log_service),
        local_config_service=StubLocalConfigService(),
        compinche_site=site,
        paripe_site=StubParipeSite(
            SiteExecutionResult(
                success=True,
                message="unused",
                final_status="success",
                phase="final_result",
            )
        ),
    )

    result = service.execute(
        ProcessExecutionRequest(
            page_name="Compinche",
            action_name="He llegado",
            phone_number="8095551234",
            password="secret",
            agent_name="Agente Local",
            execution_mode="normal",
        )
    )

    assert result.success is True
    assert result.process_log_id is None
    assert result.message == "Proceso completado sin process_logs."
    assert site.execute_calls[0][0] == "traditional"


def test_execute_compinche_reports_log_warning_when_initial_log_creation_fails() -> None:
    log_service = StubLogService()
    log_service.start_error = RuntimeError("Server disconnected")
    service = ProcessService(
        log_service_factory=build_log_service_factory(log_service),
        local_config_service=StubLocalConfigService(),
        compinche_site=StubCompincheSite(
            SiteExecutionResult(
                success=True,
                message="Proceso completado sin process_logs.",
                final_status="success",
                phase="final_result",
            )
        ),
        paripe_site=StubParipeSite(
            SiteExecutionResult(success=True, message="unused", final_status="success", phase="final_result")
        ),
    )
    progress_events = []

    result = service.execute(
        ProcessExecutionRequest(
            page_name="Compinche",
            action_name="He llegado",
            phone_number="8095551234",
            password="secret",
            agent_name="Agente Local",
            execution_mode="normal",
        ),
        progress_callback=lambda phase, message: progress_events.append((phase, message)),
    )

    assert result.success is True
    assert result.process_log_id is None
    assert progress_events[0][0] == "log_warning"
    assert "No se pudo crear process_logs inicial" in progress_events[0][1]
    assert progress_events[1][0] == "login"


def test_execute_compinche_continues_when_log_updates_fail() -> None:
    log_service = StubLogService()
    log_service.update_error = RuntimeError("Server disconnected")
    service = ProcessService(
        log_service_factory=build_log_service_factory(log_service),
        local_config_service=StubLocalConfigService(),
        compinche_site=StubCompincheSite(
            SiteExecutionResult(
                success=True,
                message="Proceso completado correctamente en compinche.io.",
                final_status="success",
                phase="final_result",
            )
        ),
        paripe_site=StubParipeSite(
            SiteExecutionResult(success=True, message="unused", final_status="success", phase="final_result")
        ),
    )
    progress_events = []

    result = service.execute(
        ProcessExecutionRequest(
            page_name="Compinche",
            action_name="He llegado",
            phone_number="8095551234",
            password="secret",
            agent_name="Agente Local",
            execution_mode="normal",
        ),
        progress_callback=lambda phase, message: progress_events.append((phase, message)),
    )

    assert result.success is True
    assert result.process_log_id == 77
    assert progress_events[0][0] == "login"
    assert progress_events[1][0] == "log_warning"
    assert "updates" in progress_events[1][1]
    assert progress_events[2][0] == "photo_upload"
    assert log_service.finish_calls[0][1]["final_status"] == "success"


def test_execute_compinche_keeps_site_success_when_finish_log_fails() -> None:
    log_service = StubLogService()
    log_service.finish_error = RuntimeError("Server disconnected")
    service = ProcessService(
        log_service_factory=build_log_service_factory(log_service),
        local_config_service=StubLocalConfigService(),
        compinche_site=StubCompincheSite(
            SiteExecutionResult(
                success=True,
                message="Proceso completado correctamente en compinche.io.",
                final_status="success",
                phase="final_result",
            )
        ),
        paripe_site=StubParipeSite(
            SiteExecutionResult(success=True, message="unused", final_status="success", phase="final_result")
        ),
    )
    progress_events = []

    result = service.execute(
        ProcessExecutionRequest(
            page_name="Compinche",
            action_name="He llegado",
            phone_number="8095551234",
            password="secret",
            agent_name="Agente Local",
            execution_mode="normal",
        ),
        progress_callback=lambda phase, message: progress_events.append((phase, message)),
    )

    assert result.success is True
    assert result.process_log_id is None
    assert progress_events[-1][0] == "log_warning"
    assert "cerrar process_logs" in progress_events[-1][1]


def test_execute_creates_separate_log_service_per_run_when_factory_is_provided() -> None:
    created_services = []

    def build_log_service():
        service = StubLogService()
        created_services.append(service)
        return service

    service = ProcessService(
        log_service_factory=build_log_service,
        local_config_service=StubLocalConfigService(),
        compinche_site=StubCompincheSite(
            SiteExecutionResult(
                success=True,
                message="Proceso completado correctamente en compinche.io.",
                final_status="success",
                phase="final_result",
            )
        ),
        paripe_site=StubParipeSite(
            SiteExecutionResult(success=True, message="unused", final_status="success", phase="final_result")
        ),
    )

    first = service.execute(
        ProcessExecutionRequest(
            page_name="Compinche",
            action_name="He llegado",
            phone_number="8095551234",
            password="secret",
            agent_name="Agente Local",
            execution_mode="normal",
        )
    )
    second = service.execute(
        ProcessExecutionRequest(
            page_name="Compinche",
            action_name="He llegado",
            phone_number="8095551235",
            password="secret",
            agent_name="Agente Local",
            execution_mode="normal",
        )
    )

    assert first.success is True
    assert second.success is True
    assert len(created_services) == 2
    assert created_services[0] is not created_services[1]
    assert len(created_services[0].start_calls) == 1
    assert len(created_services[1].start_calls) == 1


def test_execute_throttles_non_critical_process_log_updates_without_hiding_progress() -> None:
    class ChattyCompincheSite(StubCompincheSite):
        def execute_traditional(self, request, *, local_config, progress_callback):
            self.execute_calls.append(("traditional", request, local_config))
            progress_callback("micro_step", "Paso 1")
            progress_callback("micro_step", "Paso 2")
            progress_callback("micro_step", "Paso 3")
            progress_callback("final_result", "Resultado final visible")
            return self.result

    log_service = StubLogService()
    progress_events = []
    service = ProcessService(
        log_service_factory=build_log_service_factory(log_service),
        local_config_service=StubLocalConfigService(),
        compinche_site=ChattyCompincheSite(
            SiteExecutionResult(
                success=True,
                message="Proceso completado correctamente en compinche.io.",
                final_status="success",
                phase="final_result",
            )
        ),
        paripe_site=StubParipeSite(
            SiteExecutionResult(success=True, message="unused", final_status="success", phase="final_result")
        ),
    )

    result = service.execute(
        ProcessExecutionRequest(
            page_name="Compinche",
            action_name="He llegado",
            phone_number="8095551234",
            password="secret",
            agent_name="Agente Local",
            execution_mode="normal",
        ),
        progress_callback=lambda phase, message: progress_events.append((phase, message)),
    )

    assert result.success is True
    assert len(progress_events) == 5
    assert [phase for phase, _message in progress_events] == [
        "login",
        "micro_step",
        "micro_step",
        "micro_step",
        "final_result",
    ]
    assert [call[1]["phase"] for call in log_service.update_calls] == ["login", "final_result"]


def test_execute_compinche_uses_configured_traditional_mode_when_request_uses_testing() -> None:
    log_service = StubLogService()
    site = StubCompincheSite(
        SiteExecutionResult(
            success=True,
            message="Proceso real completado.",
            final_status="success",
            phase="final_result",
        )
    )
    service = ProcessService(
        log_service_factory=build_log_service_factory(log_service),
        local_config_service=StubLocalConfigService(),
        compinche_site=site,
        paripe_site=StubParipeSite(
            SiteExecutionResult(
                success=True,
                message="unused",
                final_status="success",
                phase="final_result",
            )
        ),
    )

    result = service.execute(
        ProcessExecutionRequest(
            page_name="Compinche",
            action_name="He llegado",
            phone_number="8095551234",
            password="secret",
            agent_name="Agente Local",
            execution_mode="testing",
        )
    )

    assert result.success is True
    assert result.execution_mode == "traditional"
    assert result.phase == "final_result"
    assert log_service.start_calls[0]["phase"] == "login"
    assert site.execute_calls[0][0] == "traditional"
    assert site.execute_calls[0][1].execution_mode == "traditional"
    assert log_service.finish_calls[0][1]["phase"] == "final_result"


def test_execute_paripe_runs_real_site_and_returns_block_duration() -> None:
    log_service = StubLogService()
    paripe_site = StubParipeSite(
        SiteExecutionResult(
            success=True,
            message="Proceso completado correctamente en paripe.io.",
            final_status="success",
            phase="final_result",
            station_name="Bronx NY (VNY2) - Sub Same-Day",
            block_price="$93",
            block_time="5:00 15/04/2026",
            block_duration="05:00 am - 08:00 am (3 horas)",
            reserved_photo_id="photo-9",
        )
    )
    service = ProcessService(
        log_service_factory=build_log_service_factory(log_service),
        local_config_service=StubLocalConfigService(),
        compinche_site=StubCompincheSite(
            SiteExecutionResult(
                success=True,
                message="unused",
                final_status="success",
                phase="final_result",
            )
        ),
        paripe_site=paripe_site,
    )

    result = service.execute(
        ProcessExecutionRequest(
            page_name="Paripe",
            action_name="He llegado",
            phone_number="8095551234",
            password="secret",
            agent_name="Agente Local",
            execution_mode="normal",
        )
    )

    assert result.success is True
    assert result.phase == "final_result"
    assert result.block_duration == "05:00 am - 08:00 am (3 horas)"
    assert log_service.start_calls[0]["site"] == "paripe.io"
    assert log_service.update_calls[0][1]["message"] == "Preparando navegador limpio para paripe.io... Motor: Tradicional."
    assert log_service.finish_calls[0][1]["final_status"] == "success"
    assert paripe_site.execute_calls[0][0] == "traditional"
    assert paripe_site.execute_calls[0][1].page_name == "Paripe"


def test_execute_paripe_uses_extension_engine_when_configured() -> None:
    class ExtensionConfigService(StubLocalConfigService):
        def load(self) -> LocalConfig:
            config = super().load()
            return config.model_copy(update={"flow_engine": "extension"})

    paripe_site = StubParipeSite(
        SiteExecutionResult(
            success=True,
            message="Proceso completado correctamente en paripe.io.",
            final_status="success",
            phase="final_result",
        )
    )
    service = ProcessService(
        log_service_factory=build_log_service_factory(StubLogService()),
        local_config_service=ExtensionConfigService(),
        compinche_site=StubCompincheSite(
            SiteExecutionResult(success=True, message="unused", final_status="success", phase="final_result")
        ),
        paripe_site=paripe_site,
    )

    result = service.execute(
        ProcessExecutionRequest(
            page_name="Paripe",
            action_name="He llegado",
            phone_number="8095551234",
            password="secret",
            agent_name="Agente Local",
            execution_mode="testing",
        )
    )

    assert result.execution_mode == "extension"
    assert paripe_site.execute_calls[0][0] == "extension"
    assert paripe_site.execute_calls[0][1].execution_mode == "extension"


def test_execute_paripe_keeps_instant_action_name_in_results() -> None:
    log_service = StubLogService()
    last_result_service = StubLastResultService()
    paripe_site = StubParipeSite(
        SiteExecutionResult(
            success=True,
            message="Proceso completado correctamente en paripe.io.",
            final_status="success",
            phase="final_result",
            station_name="Estacion Instant",
            block_price="RD$ 450",
            block_time="15/04/2026 05:00 am - 08:00 am",
            block_duration="3 horas",
            selfie_retry_count=1,
            deepfakescore_activated=True,
        )
    )
    service = ProcessService(
        log_service_factory=build_log_service_factory(log_service),
        local_config_service=StubLocalConfigService(),
        last_result_service=last_result_service,
        compinche_site=StubCompincheSite(
            SiteExecutionResult(success=True, message="unused", final_status="success", phase="final_result")
        ),
        paripe_site=paripe_site,
    )

    result = service.execute(
        ProcessExecutionRequest(
            page_name="Paripe",
            action_name="He llegado Instantaneas",
            phone_number="8095551234",
            password="secret",
            agent_name="Agente Local",
            execution_mode="normal",
        )
    )

    assert result.success is True
    assert result.action_name == "He llegado instantáneo"
    assert paripe_site.execute_calls[0][0] == "traditional"
    assert paripe_site.execute_calls[0][1].action_name == "He llegado instantáneo"
    assert last_result_service.saved_results[0].action_name == "He llegado instantáneo"


def test_execute_paripe_preserves_canonical_instant_action_name_when_already_accented() -> None:
    service = ProcessService(
        log_service_factory=build_log_service_factory(StubLogService()),
        local_config_service=StubLocalConfigService(),
        last_result_service=StubLastResultService(),
        compinche_site=StubCompincheSite(
            SiteExecutionResult(success=True, message="unused", final_status="success", phase="final_result")
        ),
        paripe_site=StubParipeSite(
            SiteExecutionResult(success=True, message="Proceso completado", final_status="success", phase="final_result")
        ),
    )

    result = service.execute(
        ProcessExecutionRequest(
            page_name="Paripe",
            action_name="He llegado instantáneo",
            phone_number="8095551234",
            password="secret",
            agent_name="Agente Local",
            execution_mode="normal",
        )
    )

    assert result.action_name == "He llegado instantáneo"


def test_execute_paripe_persists_login_failed_result() -> None:
    log_service = StubLogService()
    paripe_site = StubParipeSite(
        SiteExecutionResult(
            success=False,
            message="Login fallido: paripe.io no acepto el telefono o la contrasena.",
            final_status="login_failed",
            phase="login",
        )
    )
    service = ProcessService(
        log_service_factory=build_log_service_factory(log_service),
        local_config_service=StubLocalConfigService(),
        compinche_site=StubCompincheSite(
            SiteExecutionResult(success=True, message="unused", final_status="success", phase="final_result")
        ),
        paripe_site=paripe_site,
    )

    result = service.execute(
        ProcessExecutionRequest(
            page_name="Paripe",
            action_name="He llegado",
            phone_number="8095551234",
            password="bad-secret",
            agent_name="Agente Local",
            execution_mode="normal",
        )
    )

    assert result.success is False
    assert result.final_status == "login_failed"
    assert result.phase == "login"
    assert log_service.finish_calls[0][1]["final_status"] == "login_failed"


def test_execute_paripe_persists_timeout_and_no_block_results() -> None:
    log_service = StubLogService()
    timeout_service = ProcessService(
        log_service_factory=build_log_service_factory(log_service),
        local_config_service=StubLocalConfigService(),
        compinche_site=StubCompincheSite(
            SiteExecutionResult(success=True, message="unused", final_status="success", phase="final_result")
        ),
        paripe_site=StubParipeSite(
            SiteExecutionResult(
                success=False,
                message="No aparecio la informacion del bloque dentro del timeout esperado.",
                final_status="timeout",
                phase="block_read",
            )
        ),
    )

    timeout_result = timeout_service.execute(
        ProcessExecutionRequest(
            page_name="Paripe",
            action_name="He llegado",
            phone_number="8095551234",
            password="secret",
            agent_name="Agente Local",
            execution_mode="normal",
        )
    )

    assert timeout_result.final_status == "timeout"
    assert log_service.finish_calls[0][1]["final_status"] == "timeout"

    no_block_log_service = StubLogService()
    no_block_service = ProcessService(
        log_service_factory=build_log_service_factory(no_block_log_service),
        local_config_service=StubLocalConfigService(),
        compinche_site=StubCompincheSite(
            SiteExecutionResult(success=True, message="unused", final_status="success", phase="final_result")
        ),
        paripe_site=StubParipeSite(
            SiteExecutionResult(
                success=False,
                message="Paripe.io reporto que no hay bloque disponible para completar el flujo.",
                final_status="no_block",
                phase="block_read",
            )
        ),
    )

    no_block_result = no_block_service.execute(
        ProcessExecutionRequest(
            page_name="Paripe",
            action_name="He llegado",
            phone_number="8095551234",
            password="secret",
            agent_name="Agente Local",
            execution_mode="normal",
        )
    )

    assert no_block_result.final_status == "no_block"
    assert no_block_result.phase == "block_read"
    assert no_block_log_service.finish_calls[0][1]["final_status"] == "no_block"


def test_process_service_stores_runner_debug_export_with_run_stats_and_metadata() -> None:
    log_service = StubLogService()
    site = StubParipeSite(
        SiteExecutionResult(
            success=True,
            message="Proceso completado correctamente en paripe.io.",
            final_status="success",
            phase="final_result",
        )
    )
    site.debug_export = {
        "timeline": [{"event": "flow_detector_state"}],
        "flow_state_detector": {"last_state": "FINAL_RESULT"},
        "timing_summary_text": "Resumen tiempos: local",
        "last_final_button_candidate": {"text": "He llegado"},
    }
    service = ProcessService(
        log_service_factory=build_log_service_factory(log_service),
        local_config_service=StubLocalConfigService(),
        compinche_site=StubCompincheSite(
            SiteExecutionResult(success=True, message="unused", final_status="success", phase="final_result")
        ),
        paripe_site=site,
    )

    result = service.execute(
        ProcessExecutionRequest(
            process_id="proc-debug-1",
            page_name="Paripe",
            action_name="He llegado",
            phone_number="8095551234",
            password="secret",
            agent_name="Agente Local",
            execution_mode="normal",
        )
    )

    process_debug = service.get_process_debug_export(result.process_id)

    assert process_debug["process_id"] == "proc-debug-1"
    assert process_debug["page_name"] == "Paripe"
    assert "flow_state_detector" in process_debug
    assert process_debug["timeline"] == [{"event": "flow_detector_state"}]
    assert "run_stats_timeline" in process_debug
    assert "run_stats_summary_text" in process_debug
    assert process_debug["last_final_button_candidate"] == {"text": "He llegado"}


def test_process_service_can_retrieve_debug_by_slot_id_when_process_lookup_is_not_used() -> None:
    log_service = StubLogService()
    site = StubParipeSite(
        SiteExecutionResult(
            success=True,
            message="Proceso completado correctamente en paripe.io.",
            final_status="success",
            phase="final_result",
        )
    )
    site.debug_export = {"flow_state_detector": {"last_state": "FINAL_RESULT"}, "timeline": [{"event": "done"}]}
    service = ProcessService(
        log_service_factory=build_log_service_factory(log_service),
        local_config_service=StubLocalConfigService(),
        compinche_site=StubCompincheSite(
            SiteExecutionResult(success=True, message="unused", final_status="success", phase="final_result")
        ),
        paripe_site=site,
    )
    service.register_process_slot("proc-debug-slot", "slot_1")

    service.execute(
        ProcessExecutionRequest(
            process_id="proc-debug-slot",
            page_name="Paripe",
            action_name="He llegado",
            phone_number="8095551234",
            password="secret",
            agent_name="Agente Local",
            execution_mode="normal",
        )
    )

    process_debug = service.get_process_debug_export(None, slot_id="slot_1")

    assert process_debug["slot_id"] == "slot_1"
    assert process_debug["process_id"] == "proc-debug-slot"
    assert process_debug["flow_state_detector"]["last_state"] == "FINAL_RESULT"


def test_process_service_limits_process_debug_exports_to_recent_entries() -> None:
    service = ProcessService(
        log_service_factory=build_log_service_factory(StubLogService()),
        local_config_service=StubLocalConfigService(),
    )

    for index in range(60):
        runner = StubDebugRunner({"timeline": [{"event": f"process-{index}"}]})
        service._store_process_debug_export(
            f"proc-{index}",
            runner,
            extras={
                "process_id": f"proc-{index}",
                "slot_id": f"slot-{index % 3}",
                "page_name": "Paripe",
                "action_name": "He llegado",
                "execution_mode": "traditional",
            },
        )

    assert len(service._process_debug_exports) == 50
    assert service.get_process_debug_export("proc-0") == {}
    latest = service.get_process_debug_export("proc-59")
    assert latest["process_id"] == "proc-59"
    assert latest["slot_id"] == "slot-2"
    assert "recorded_at" in latest


def test_process_service_limits_slot_debug_exports_and_keeps_latest_per_slot() -> None:
    service = ProcessService(
        log_service_factory=build_log_service_factory(StubLogService()),
        local_config_service=StubLocalConfigService(),
    )

    for index in range(55):
        process_id = f"proc-slot-{index}"
        slot_id = f"slot-{index}"
        service.register_process_slot(process_id, slot_id)
        runner = StubDebugRunner({"timeline": [{"event": f"slot-{index}"}]})
        service._store_process_debug_export(
            process_id,
            runner,
            extras={
                "process_id": process_id,
                "slot_id": slot_id,
                "page_name": "Compinche",
                "action_name": "He llegado",
                "execution_mode": "traditional",
            },
        )

    assert len(service._slot_debug_exports) == 50
    assert service.get_process_debug_export(None, slot_id="slot-0") == {}
    latest_slot = service.get_process_debug_export(None, slot_id="slot-54")
    assert latest_slot["process_id"] == "proc-slot-54"
    assert latest_slot["slot_id"] == "slot-54"
    assert latest_slot["timeline"] == [{"event": "slot-54"}]


def test_process_service_store_debug_export_merges_previous_payload_and_preserves_latest_slot() -> None:
    service = ProcessService(
        log_service_factory=build_log_service_factory(StubLogService()),
        local_config_service=StubLocalConfigService(),
    )
    service.register_process_slot("proc-merge", "slot-merge")

    first_runner = StubDebugRunner({"timeline": [{"event": "first"}], "flow_state_detector": {"last_state": "LOGIN"}})
    service._store_process_debug_export(
        "proc-merge",
        first_runner,
        extras={
            "page_name": "Paripe",
            "action_name": "He llegado",
            "execution_mode": "traditional",
        },
    )

    second_runner = StubDebugRunner({"last_final_button_candidate": {"text": "He llegado"}})
    service._store_process_debug_export(
        "proc-merge",
        second_runner,
        extras={
            "page_name": "Paripe",
            "action_name": "He llegado",
            "execution_mode": "extension",
        },
    )

    payload = service.get_process_debug_export("proc-merge")
    slot_payload = service.get_process_debug_export(None, slot_id="slot-merge")

    assert payload["timeline"] == [{"event": "first"}]
    assert payload["flow_state_detector"] == {"last_state": "LOGIN"}
    assert payload["last_final_button_candidate"] == {"text": "He llegado"}
    assert payload["execution_mode"] == "extension"
    assert slot_payload["process_id"] == "proc-merge"


def test_process_service_evicted_process_debug_does_not_break_slot_lookup() -> None:
    service = ProcessService(
        log_service_factory=build_log_service_factory(StubLogService()),
        local_config_service=StubLocalConfigService(),
    )

    for index in range(52):
        process_id = f"proc-evict-{index}"
        slot_id = f"slot-evict-{index}"
        service.register_process_slot(process_id, slot_id)
        runner = StubDebugRunner({"timeline": [{"event": f"evict-{index}"}]})
        service._store_process_debug_export(
            process_id,
            runner,
            extras={
                "page_name": "Ready4Drive",
                "action_name": "He llegado",
                "execution_mode": "traditional",
            },
        )

    assert service.get_process_debug_export("proc-evict-0") == {}
    fallback = service.get_process_debug_export(None, slot_id="slot-evict-51")
    assert fallback["process_id"] == "proc-evict-51"
    assert fallback["timeline"] == [{"event": "evict-51"}]


def test_execute_preserves_owner_selfie_request_fields_for_site_run() -> None:
    site = StubCompincheSite(
        SiteExecutionResult(
            success=True,
            message="Proceso completado correctamente en compinche.io.",
            final_status="success",
            phase="final_result",
        )
    )
    service = ProcessService(
        log_service_factory=build_log_service_factory(StubLogService()),
        local_config_service=StubLocalConfigService(),
        compinche_site=site,
        paripe_site=StubParipeSite(
            SiteExecutionResult(success=True, message="unused", final_status="success", phase="final_result")
        ),
    )

    service.execute(
        ProcessExecutionRequest(
            process_id="proc-owner-selfie",
            page_name="Compinche",
            action_name="He llegado",
            phone_number="8095551234",
            password="secret",
            agent_name="Agente Local",
            execution_mode="normal",
            slot_id="slot_1",
            owner_selfie_enabled=True,
            owner_selfie_path="C:/tmp/owner-selfie.jpg",
        )
    )

    request_used = site.execute_calls[0][1]
    assert request_used.slot_id == "slot_1"
    assert request_used.owner_selfie_enabled is True
    assert request_used.owner_selfie_path == "C:/tmp/owner-selfie.jpg"
