from __future__ import annotations

from automation.engines.common import FlowEngine
from automation.engines.extension import ExtensionFlowEngine
from automation.engines.traditional import TraditionalFlowEngine


class FlowEngineRouter:
    def __init__(
        self,
        traditional_engine: FlowEngine | None = None,
        extension_engine: FlowEngine | None = None,
    ) -> None:
        self._engines = {
            "traditional": traditional_engine or TraditionalFlowEngine(),
            "extension": extension_engine or ExtensionFlowEngine(),
        }

    def resolve(self, mode: str) -> FlowEngine:
        normalized_mode = (mode or "").strip().lower()
        return self._engines.get(normalized_mode, self._engines["traditional"])
