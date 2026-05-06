from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Protocol

from core.models import LocalConfig, ProcessExecutionRequest, SiteExecutionResult


ProgressEmitter = Callable[[str, str], None] | None


class SiteAutomationRunner(Protocol):
    def execute_traditional(
        self,
        request: ProcessExecutionRequest,
        *,
        local_config: LocalConfig,
        progress_callback: ProgressEmitter,
    ) -> SiteExecutionResult:
        ...

    def execute_extension(
        self,
        request: ProcessExecutionRequest,
        *,
        local_config: LocalConfig,
        progress_callback: ProgressEmitter,
    ) -> SiteExecutionResult:
        ...


@dataclass(frozen=True)
class RegisteredSiteRunner:
    site_label: str
    site_host: str
    runner: SiteAutomationRunner


class FlowEngine(Protocol):
    mode: str
    label: str

    def execute_site(
        self,
        site: RegisteredSiteRunner,
        *,
        request: ProcessExecutionRequest,
        local_config: LocalConfig,
        progress_callback: ProgressEmitter,
    ) -> SiteExecutionResult:
        ...
