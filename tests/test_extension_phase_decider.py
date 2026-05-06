from automation.engines.extension import ExtensionFlowEngine, ExtensionPhaseDecider


class _FakeSession:
    def __init__(self, state: dict | None) -> None:
        self._state = state
        self.calls: list[tuple[object, str]] = []

    def capture_extension_debug(self, *, page, note: str):
        self.calls.append((page, note))
        if self._state is None:
            return None
        return {"state": self._state}


def test_return_to_selfie_resolves_from_strong_selfie_signals_without_block() -> None:
    state = {
        "phase": "unknown",
        "lastValidPhase": "loading_after_continue",
        "signals": {
            "fileInputVisible": True,
            "userAvatarVisible": True,
            "continueCount": 1,
            "selfieTextVisible": True,
            "accountOptionsVisible": True,
            "blockReady": False,
            "blockStrong": False,
            "finalSuccessVisible": False,
        },
    }

    assert ExtensionPhaseDecider.resolves(state, "return_to_selfie") is True


def test_block_read_ready_resolves_from_strong_block_signals() -> None:
    state = {
        "phase": "unknown",
        "signals": {
            "blockReady": True,
            "blockPrice": True,
            "blockStation": True,
            "blockDuration": True,
            "blockContainerVisible": True,
        },
    }

    assert ExtensionPhaseDecider.resolves(state, "block_read_ready") is True


def test_final_result_ready_resolves_after_submit_when_block_and_button_disappear() -> None:
    state = {
        "phase": "unknown",
        "lastValidPhase": "final_submit_ready",
        "signals": {
            "finalSuccessVisible": False,
            "finalSubmitVisible": False,
            "blockReady": False,
        },
    }

    assert ExtensionPhaseDecider.resolves(state, "final_result_ready") is True


def test_return_to_selfie_does_not_resolve_when_block_is_still_strong() -> None:
    state = {
        "phase": "unknown",
        "signals": {
            "fileInputVisible": True,
            "userAvatarVisible": True,
            "continueCount": 1,
            "selfieTextVisible": True,
            "blockReady": True,
            "blockStrong": True,
        },
    }

    assert ExtensionPhaseDecider.resolves(state, "return_to_selfie") is False


def test_extension_engine_resolve_phase_signal_returns_resolved_state() -> None:
    state = {
        "phase": "unknown",
        "lastValidPhase": "final_submit_ready",
        "signals": {
            "finalSuccessVisible": False,
            "finalSubmitVisible": False,
            "blockReady": False,
        },
    }
    session = _FakeSession(state)
    page = object()

    resolution = ExtensionFlowEngine.resolve_phase_signal(
        session=session,
        page=page,
        target_phase="final_result_ready",
        note="wait_final_result_ready",
    )

    assert resolution.resolved is True
    assert resolution.state == state
    assert resolution.target_phase == "final_result_ready"
    assert session.calls == [(page, "wait_final_result_ready")]


def test_extension_engine_resolve_phase_signal_falls_back_when_snapshot_is_missing() -> None:
    session = _FakeSession(None)

    resolution = ExtensionFlowEngine.resolve_phase_signal(
        session=session,
        page=object(),
        target_phase="final_result_ready",
        note="wait_final_result_ready",
    )

    assert resolution.resolved is False
    assert resolution.state is None


def test_extension_engine_resolve_block_read_ready_returns_phase_specific_resolution() -> None:
    state = {
        "phase": "unknown",
        "signals": {
            "blockReady": True,
            "blockPrice": True,
            "blockStation": True,
            "blockDuration": False,
            "blockContainerVisible": True,
        },
    }
    session = _FakeSession(state)
    page = object()

    resolution = ExtensionFlowEngine.resolve_block_read_ready(
        session=session,
        page=page,
    )

    assert resolution.target_phase == "block_read_ready"
    assert resolution.resolved is True
    assert resolution.state == state
    assert session.calls == [(page, "wait_block_read_ready")]


def test_extension_engine_resolve_return_to_selfie_returns_phase_specific_resolution() -> None:
    state = {
        "phase": "unknown",
        "signals": {
            "fileInputVisible": True,
            "userAvatarVisible": True,
            "continueCount": 1,
            "selfieTextVisible": True,
            "blockReady": False,
            "blockStrong": False,
            "finalSuccessVisible": False,
        },
    }
    session = _FakeSession(state)
    page = object()

    resolution = ExtensionFlowEngine.resolve_return_to_selfie(
        session=session,
        page=page,
    )

    assert resolution.target_phase == "return_to_selfie"
    assert resolution.resolved is True
    assert resolution.state == state
    assert session.calls == [(page, "wait_return_to_selfie")]


def test_extension_engine_resolve_final_result_ready_returns_phase_specific_resolution() -> None:
    state = {
        "phase": "unknown",
        "lastValidPhase": "final_submit_ready",
        "signals": {
            "finalSuccessVisible": False,
            "finalSubmitVisible": False,
            "blockReady": False,
        },
    }
    session = _FakeSession(state)
    page = object()

    resolution = ExtensionFlowEngine.resolve_final_result_ready(
        session=session,
        page=page,
    )

    assert resolution.target_phase == "final_result_ready"
    assert resolution.resolved is True
    assert resolution.state == state
    assert session.calls == [(page, "wait_final_result_ready")]


def test_extension_engine_uses_marker_report_state_when_phase_is_present() -> None:
    state = {
        "stateSource": "marker_report",
        "phase": "block_read_ready",
        "lastValidPhase": "selfie_stage",
        "signals": {
            "blockReady": True,
            "blockPrice": False,
            "blockStation": False,
            "blockDuration": False,
            "blockContainerVisible": False,
        },
    }
    session = _FakeSession(state)
    page = object()

    resolution = ExtensionFlowEngine.resolve_block_read_ready(
        session=session,
        page=page,
    )

    assert resolution.resolved is True
    assert resolution.state == state
    assert session.calls == [(page, "wait_block_read_ready")]


def test_extension_engine_accepts_marker_report_state_with_unknown_site_when_phase_matches() -> None:
    state = {
        "stateSource": "marker_report",
        "site": "unknown",
        "phase": "block_read_ready",
        "lastValidPhase": "block_read_ready",
        "signals": {
            "blockReady": True,
        },
    }
    session = _FakeSession(state)

    resolution = ExtensionFlowEngine.resolve_block_read_ready(
        session=session,
        page=object(),
    )

    assert resolution.resolved is True
    assert resolution.state == state


def test_extension_engine_rejects_marker_report_state_when_phase_is_unknown() -> None:
    state = {
        "stateSource": "marker_report",
        "site": "unknown",
        "phase": "unknown",
        "lastValidPhase": "unknown",
        "signals": {
            "blockReady": False,
            "blockStrong": False,
            "blockPrice": False,
            "blockStation": False,
            "blockDuration": False,
            "blockContainerVisible": False,
        },
    }
    session = _FakeSession(state)

    resolution = ExtensionFlowEngine.resolve_block_read_ready(
        session=session,
        page=object(),
    )

    assert resolution.resolved is False
    assert resolution.state == state


def test_phase_decider_accepts_last_valid_phase_alias_for_block_ready() -> None:
    state = {
        "phase": "unknown",
        "last_valid_phase": "block_read_ready",
        "signals": {},
    }

    assert ExtensionPhaseDecider.resolves(state, "block_read_ready") is True
