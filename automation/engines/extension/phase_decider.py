from __future__ import annotations


class ExtensionPhaseDecider:
    governed_phases = frozenset({"return_to_selfie", "block_read_ready", "final_result_ready"})

    @classmethod
    def resolves(cls, state: dict | None, target_phase: str) -> bool:
        if not isinstance(state, dict):
            return False
        if cls._declared_phase_matches(state, target_phase):
            return True
        phase = cls._phase(state)
        signals = cls._signals(state)
        if target_phase == "return_to_selfie":
            strong_selfie = (
                bool(signals.get("fileInputVisible") or signals.get("userAvatarVisible"))
                and bool(
                    (signals.get("continueCount") or 0) > 0
                    or signals.get("selfieTextVisible")
                    or signals.get("accountOptionsVisible")
                    or signals.get("selfieStrong")
                )
            )
            no_block = not bool(
                signals.get("blockReady")
                or signals.get("blockStrong")
                or signals.get("finalSuccessVisible")
            )
            return strong_selfie and no_block
        if target_phase == "block_read_ready":
            return bool(
                signals.get("blockStrong")
                or (
                    signals.get("blockReady")
                    and signals.get("blockPrice")
                    and signals.get("blockStation")
                )
                or (
                    signals.get("blockReady")
                    and signals.get("blockDuration")
                    and signals.get("blockContainerVisible")
                )
            )
        if target_phase == "final_result_ready":
            last_valid_phase = cls._normalized_value(state, "lastValidPhase", "last_valid_phase")
            return bool(
                signals.get("finalSuccessVisible")
                or (
                    last_valid_phase == "final_submit_ready"
                    and not signals.get("finalSubmitVisible")
                    and not signals.get("blockReady")
                )
            )
        return phase == target_phase

    @staticmethod
    def _phase(state: dict) -> str:
        phase = ExtensionPhaseDecider._normalized_value(state, "phase")
        if phase != "unknown":
            return phase
        return ExtensionPhaseDecider._normalized_value(state, "lastValidPhase", "last_valid_phase")

    @staticmethod
    def _signals(state: dict) -> dict:
        signals = state.get("signals")
        return signals if isinstance(signals, dict) else {}

    @staticmethod
    def _normalized_value(state: dict, *keys: str) -> str:
        for key in keys:
            value = str(state.get(key) or "").strip()
            if value:
                return value
        return "unknown"

    @classmethod
    def _declared_phase_matches(cls, state: dict, target_phase: str) -> bool:
        return any(
            cls._normalized_value(state, key) == target_phase
            for key in ("phase", "lastValidPhase", "last_valid_phase")
        )
