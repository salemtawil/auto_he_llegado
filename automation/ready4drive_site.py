from __future__ import annotations

from automation.base_site import ProgressCallback
from automation.compinche_site import CompincheSite
from core.models import LocalConfig, ProcessExecutionRequest, SiteExecutionResult


class Ready4DriveSite(CompincheSite):
    site_name = "ready4drive.com"
    _ENTRY_URL = "https://ready4drive.com/login"

    def execute(
        self,
        request: ProcessExecutionRequest,
        *,
        local_config: LocalConfig,
        progress_callback: ProgressCallback | None = None,
    ) -> SiteExecutionResult:
        return self.execute_traditional(
            request,
            local_config=local_config,
            progress_callback=progress_callback,
        )

    def execute_traditional(
        self,
        request: ProcessExecutionRequest,
        *,
        local_config: LocalConfig,
        progress_callback: ProgressCallback | None = None,
    ) -> SiteExecutionResult:
        return self._execute_bootstrap(
            request,
            local_config=local_config,
            progress_callback=progress_callback,
        )

    def execute_extension(
        self,
        request: ProcessExecutionRequest,
        *,
        local_config: LocalConfig,
        progress_callback: ProgressCallback | None = None,
    ) -> SiteExecutionResult:
        return self._execute_bootstrap(
            request,
            local_config=local_config,
            progress_callback=progress_callback,
        )

    def _execute_bootstrap(
        self,
        request: ProcessExecutionRequest,
        *,
        local_config: LocalConfig,
        progress_callback: ProgressCallback | None = None,
    ) -> SiteExecutionResult:
        self.emit_progress(
            progress_callback,
            phase="site_bootstrap",
            message="Base inicial de ready4drive creada sobre la arquitectura de compinche.",
        )
        self.emit_progress(
            progress_callback,
            phase="site_bootstrap",
            message="Pendiente validar selectores reales de login, iframe, bloque y resultado final en ready4drive.com.",
        )
        return SiteExecutionResult(
            success=False,
            message=(
                "Ready4Drive tiene base inicial creada, pero todavia no esta validado en flujo real. "
                "Faltan selectores confirmados para login, iframe, bloque y resultado final."
            ),
            final_status="not_implemented",
            phase="site_bootstrap",
        )
