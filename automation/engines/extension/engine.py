from __future__ import annotations

from dataclasses import dataclass

from automation.engines.common import FlowEngine, ProgressEmitter, RegisteredSiteRunner
from automation.engines.extension.phase_decider import ExtensionPhaseDecider
from core.models import LocalConfig, ProcessExecutionRequest, SiteExecutionResult


@dataclass(frozen=True)
class ExtensionPhaseResolution:
    target_phase: str
    resolved: bool
    state: dict | None
    reason: str


class ExtensionFlowEngine(FlowEngine):
    mode = "extension"
    label = "Extension"
    decision_policy = ExtensionPhaseDecider()

    def execute_site(
        self,
        site: RegisteredSiteRunner,
        *,
        request: ProcessExecutionRequest,
        local_config: LocalConfig,
        progress_callback: ProgressEmitter,
    ) -> SiteExecutionResult:
        normalized_request = request.model_copy(update={"execution_mode": self.mode})
        if progress_callback is not None:
            progress_callback(
                "engine",
                "Motor extension activo. La extension es la fuente primaria de estado; cualquier degradacion se registra de forma explicita.",
            )
        return site.runner.execute_extension(
            normalized_request,
            local_config=local_config,
            progress_callback=progress_callback,
        )

    @classmethod
    def resolve_phase_signal(
        cls,
        *,
        session,
        page,
        target_phase: str,
        note: str,
    ) -> ExtensionPhaseResolution:
        state = cls._observer_state(session=session, page=page, note=note)
        if cls._declared_phase_matches(state, target_phase):
            return ExtensionPhaseResolution(
                target_phase=target_phase,
                resolved=True,
                state=state,
                reason=cls._match_reason(state, target_phase),
            )
        return ExtensionPhaseResolution(
            target_phase=target_phase,
            resolved=cls.decision_policy.resolves(state, target_phase),
            state=state,
            reason=cls._fallback_reason(state, target_phase),
        )

    @classmethod
    def resolve_block_read_ready(
        cls,
        *,
        session,
        page,
        note: str = "wait_block_read_ready",
    ) -> ExtensionPhaseResolution:
        return cls.resolve_phase_signal(
            session=session,
            page=page,
            target_phase="block_read_ready",
            note=note,
        )

    @classmethod
    def resolve_return_to_selfie(
        cls,
        *,
        session,
        page,
        note: str = "wait_return_to_selfie",
    ) -> ExtensionPhaseResolution:
        return cls.resolve_phase_signal(
            session=session,
            page=page,
            target_phase="return_to_selfie",
            note=note,
        )

    @classmethod
    def resolve_final_result_ready(
        cls,
        *,
        session,
        page,
        note: str = "wait_final_result_ready",
    ) -> ExtensionPhaseResolution:
        return cls.resolve_phase_signal(
            session=session,
            page=page,
            target_phase="final_result_ready",
            note=note,
        )

    @staticmethod
    def _observer_state(*, session, page, note: str) -> dict | None:
        if session is None:
            return None
        snapshot = session.capture_extension_debug(page=page, note=note)
        if not snapshot:
            return None
        state = snapshot.get("state")
        return state if isinstance(state, dict) else None

    @staticmethod
    def _declared_phase_matches(state: dict | None, target_phase: str) -> bool:
        if not isinstance(state, dict):
            return False
        for key in ("phase", "lastValidPhase", "last_valid_phase"):
            value = str(state.get(key) or "").strip()
            if value == target_phase:
                return True
        return False

    @staticmethod
    def _match_reason(state: dict | None, target_phase: str) -> str:
        if not isinstance(state, dict):
            return "no_state"
        for key, reason in (
            ("phase", "phase_match"),
            ("lastValidPhase", "last_valid_phase_match"),
            ("last_valid_phase", "last_valid_phase_match"),
        ):
            value = str(state.get(key) or "").strip()
            if value == target_phase:
                return reason
        return "phase_match"

    @staticmethod
    def _fallback_reason(state: dict | None, target_phase: str) -> str:
        if not isinstance(state, dict):
            return "no_state"
        phase = str(state.get("phase") or "").strip() or "unknown"
        last_valid_phase = str(state.get("lastValidPhase") or state.get("last_valid_phase") or "").strip() or "unknown"
        if phase == "unknown" and last_valid_phase == "unknown":
            return "phase_unknown"
        if phase != target_phase and last_valid_phase != target_phase:
            return "phase_mismatch"
        return "phase_unknown"
