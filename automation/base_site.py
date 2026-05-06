from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable

from core.models import LocalConfig, ProcessExecutionRequest, SiteExecutionResult

ProgressCallback = Callable[[str, str], None]


class BaseSite(ABC):
    site_name: str = ""

    @abstractmethod
    def execute(
        self,
        request: ProcessExecutionRequest,
        *,
        local_config: LocalConfig,
        progress_callback: ProgressCallback | None = None,
    ) -> SiteExecutionResult:
        raise NotImplementedError

    @staticmethod
    def emit_progress(
        progress_callback: ProgressCallback | None,
        *,
        phase: str,
        message: str,
    ) -> None:
        if progress_callback is not None:
            progress_callback(phase, message)
