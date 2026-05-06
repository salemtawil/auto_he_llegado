from automation.engine_router import FlowEngineRouter
from automation.engines.extension import ExtensionFlowEngine
from automation.engines.traditional import TraditionalFlowEngine
from core.models import LocalConfig, ProcessExecutionRequest, SiteExecutionResult
from automation.engines.common import RegisteredSiteRunner


class StubSiteRunner:
    def __init__(self) -> None:
        self.calls = []

    def execute_traditional(self, request, *, local_config, progress_callback):
        self.calls.append(("traditional", request, local_config))
        if progress_callback is not None:
            progress_callback("engine", f"runner mode={request.execution_mode}")
        return SiteExecutionResult(
            success=True,
            message="ok",
            final_status="success",
            phase="final_result",
        )

    def execute_extension(self, request, *, local_config, progress_callback):
        self.calls.append(("extension", request, local_config))
        if progress_callback is not None:
            progress_callback("engine", f"runner mode={request.execution_mode}")
        return SiteExecutionResult(
            success=True,
            message="ok",
            final_status="success",
            phase="final_result",
        )


def test_router_returns_traditional_engine_by_default() -> None:
    router = FlowEngineRouter()

    engine = router.resolve("unknown")

    assert isinstance(engine, TraditionalFlowEngine)
    assert engine.mode == "traditional"


def test_router_returns_extension_engine_when_requested() -> None:
    router = FlowEngineRouter()

    engine = router.resolve("extension")

    assert isinstance(engine, ExtensionFlowEngine)
    assert engine.mode == "extension"


def test_traditional_engine_executes_site_in_traditional_mode() -> None:
    runner = StubSiteRunner()
    site = RegisteredSiteRunner(site_label="Paripe", site_host="paripe.io", runner=runner)
    request = ProcessExecutionRequest(
        page_name="Paripe",
        action_name="He llegado",
        phone_number="8095551234",
        password="secret",
        agent_name="Agente Local",
        execution_mode="extension",
    )

    result = TraditionalFlowEngine().execute_site(
        site,
        request=request,
        local_config=LocalConfig(),
        progress_callback=None,
    )

    assert result.success is True
    assert runner.calls[0][0] == "traditional"
    assert runner.calls[0][1].execution_mode == "traditional"


def test_extension_engine_executes_site_in_extension_mode() -> None:
    runner = StubSiteRunner()
    site = RegisteredSiteRunner(site_label="Compinche", site_host="compinche.io", runner=runner)
    request = ProcessExecutionRequest(
        page_name="Compinche",
        action_name="He llegado",
        phone_number="8095551234",
        password="secret",
        agent_name="Agente Local",
        execution_mode="traditional",
    )

    result = ExtensionFlowEngine().execute_site(
        site,
        request=request,
        local_config=LocalConfig(),
        progress_callback=None,
    )

    assert result.success is True
    assert runner.calls[0][0] == "extension"
    assert runner.calls[0][1].execution_mode == "extension"
