from __future__ import annotations

from automation.engines.common import FlowEngine, ProgressEmitter, RegisteredSiteRunner
from core.models import LocalConfig, ProcessExecutionRequest, SiteExecutionResult


class TraditionalFlowEngine(FlowEngine):
    mode = "traditional"
    label = "Tradicional"

    def execute_site(
        self,
        site: RegisteredSiteRunner,
        *,
        request: ProcessExecutionRequest,
        local_config: LocalConfig,
        progress_callback: ProgressEmitter,
    ) -> SiteExecutionResult:
        normalized_request = request.model_copy(update={"execution_mode": self.mode})
        return site.runner.execute_traditional(
            normalized_request,
            local_config=local_config,
            progress_callback=progress_callback,
        )
