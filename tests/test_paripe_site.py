from types import SimpleNamespace

import pytest

from automation.engines.extension import ExtensionFlowEngine
from automation.paripe_site import ParipeFlowError, ParipeSite
from core.models import LocalConfig, ProcessExecutionRequest, SiteExecutionResult


def _local_config() -> LocalConfig:
    return LocalConfig(
        agent_name="Agente Local",
        flow_engine="traditional",
        page_timeout_seconds=45,
        action_timeout_seconds=25,
        max_selfie_retries=2,
        keep_browser_open=False,
        enable_browser_extension=True,
        browser_extension_overlay=True,
    )


def _request(*, execution_mode: str = "testing") -> ProcessExecutionRequest:
    return ProcessExecutionRequest(
        page_name="Paripe",
        action_name="He llegado",
        phone_number="8095551234",
        password="secret",
        agent_name="Agente Local",
        execution_mode=execution_mode,
    )


def test_paripe_execute_traditional_routes_to_private_traditional_pipeline() -> None:
    site = ParipeSite()
    calls: list[tuple[str, str]] = []

    def fake_execute_traditional(request, *, local_config, progress_callback):
        calls.append(("traditional", request.execution_mode))
        return SiteExecutionResult(success=True, message="ok", final_status="success", phase="done")

    site._execute_traditional = fake_execute_traditional  # type: ignore[method-assign]  # noqa: SLF001

    result = site.execute_traditional(_request(execution_mode="testing"), local_config=_local_config())

    assert result.success is True
    assert calls == [("traditional", "traditional")]


def test_paripe_execute_extension_routes_to_private_extension_pipeline() -> None:
    site = ParipeSite()
    calls: list[tuple[str, str]] = []

    def fake_execute_extension(request, *, local_config, progress_callback):
        calls.append(("extension", request.execution_mode))
        return SiteExecutionResult(success=True, message="ok", final_status="success", phase="done")

    site._execute_extension = fake_execute_extension  # type: ignore[method-assign]  # noqa: SLF001

    result = site.execute_extension(_request(execution_mode="testing"), local_config=_local_config())

    assert result.success is True
    assert calls == [("extension", "extension")]


def test_paripe_action_mapping_accepts_instant_and_normal_variants() -> None:
    site = ParipeSite()

    instant = site._get_action_spec("He llegado Instantaneas")  # noqa: SLF001
    instant_accent = site._get_action_spec("He llegado instantáneo")  # noqa: SLF001
    normal = site._get_action_spec("He llegado")  # noqa: SLF001
    selfie = site._get_action_spec("Selfie en ruta")  # noqa: SLF001

    assert instant.ui_name == "He llegado instantáneo"
    assert instant_accent.ui_name == "He llegado instantáneo"
    assert normal.ui_name == "He llegado"
    assert selfie.ui_name == "Selfie en ruta"


def test_paripe_action_scoring_prefers_instant_over_normal_when_card_mentions_offers() -> None:
    site = ParipeSite()
    instant = site._get_action_spec("He llegado Instantaneas")  # noqa: SLF001
    normal = site._get_action_spec("He llegado")  # noqa: SLF001

    text = "I'm here instant offers"

    assert site._score_action_match(text, instant) > 0  # noqa: SLF001
    assert site._score_action_match(text, normal) == 0  # noqa: SLF001


def test_paripe_action_scoring_accepts_portuguese_and_spanish_instant_variants() -> None:
    site = ParipeSite()
    instant = site._get_action_spec("He llegado instantáneo")  # noqa: SLF001

    assert site._score_action_match("Eu cheguei Instantâneo", instant) > 0  # noqa: SLF001
    assert site._score_action_match("Instantáneas", instant) > 0  # noqa: SLF001


def test_build_duration_combines_range_and_hours() -> None:
    assert (
        ParipeSite._build_duration("05:00 am - 08:00 am", "3 horas")  # noqa: SLF001
        == "05:00 am - 08:00 am (3 horas)"
    )


def test_build_duration_keeps_range_when_total_hours_missing() -> None:
    assert (
        ParipeSite._build_duration("05:00 am - 08:00 am", None)  # noqa: SLF001
        == "05:00 am - 08:00 am"
    )


def test_normalize_text_removes_accents_and_whitespace() -> None:
    assert (
        ParipeSite._normalize_text("  Estoy aquí   exitoso!  ")  # noqa: SLF001
        == "estoy aqui exitoso!"
    )


def test_detect_no_block_message_identifies_unavailable_block() -> None:
    site = ParipeSite()
    assert (
        site._detect_no_block_message("no hay bloque disponible en este momento")  # noqa: SLF001
        == "Paripe.io reporto que no hay bloque disponible para completar el flujo."
    )


def test_resolve_terminal_state_prioritizes_no_block_and_error() -> None:
    site = ParipeSite()
    assert site._resolve_terminal_state("no hay bloque disponible") == "no_block"  # noqa: SLF001
    assert site._resolve_terminal_state("el sitio devolvio un error") == "error"  # noqa: SLF001
    assert site._resolve_terminal_state("he llegado exitoso") == "success"  # noqa: SLF001


def test_extract_text_pairs_reads_variable_block_fields_without_hardcode() -> None:
    site = ParipeSite()
    pairs = site._extract_text_pairs(  # noqa: SLF001
        "\n".join(
            (
                "Pago",
                "$93",
                "Estacion",
                "Bronx NY (VNY2) - Sub Same-Day",
                "Horario",
                "05:00 am - 08:00 am",
                "Fecha",
                "15/04/2026",
                "Duracion",
                "3 horas",
            )
        )
    )

    assert pairs["pago"] == "$93"
    assert pairs["estacion"] == "Bronx NY (VNY2) - Sub Same-Day"
    assert pairs["horario"] == "05:00 am - 08:00 am"
    assert pairs["duracion"] == "3 horas"


def test_extract_schedule_candidates_keeps_date_and_time_lines() -> None:
    site = ParipeSite()
    candidates = site._extract_schedule_candidates(  # noqa: SLF001
        "\n".join(
            (
                "Pago",
                "$93",
                "15/04/2026 05:00 am - 08:00 am",
                "Bronx NY (VNY2) - Sub Same-Day",
            )
        )
    )

    assert candidates == ["15/04/2026 05:00 am - 08:00 am"]


def test_paripe_strong_block_signal_rejects_loading_even_with_partial_block_signals() -> None:
    site = ParipeSite()
    site._resolve_block_context = lambda flow_context, _page: flow_context  # type: ignore[method-assign]  # noqa: SLF001
    site._collect_block_signals = lambda _context, _page: {  # type: ignore[method-assign]  # noqa: SLF001
        "price_or_payment": True,
        "station": True,
        "schedule": False,
        "duration": False,
        "block_card": False,
        "final_button": False,
    }
    site._collect_selfie_return_signals = lambda _page, _context: {  # type: ignore[method-assign]  # noqa: SLF001
        "file_input": False,
        "user_avatar": False,
        "continue_button": False,
        "selfie_text": False,
        "account_options": False,
        "selfie_container": False,
    }
    site._collect_processing_signals = lambda _page, _context: {  # type: ignore[method-assign]  # noqa: SLF001
        "processing_text": True,
        "processing_ui": False,
    }

    assert site._has_strong_block_signal("dialog", object()) is False  # type: ignore[arg-type]  # noqa: SLF001


def test_paripe_strong_block_signal_accepts_selfie_residual_after_continue() -> None:
    site = ParipeSite()
    site._resolve_block_context = lambda flow_context, _page: flow_context  # type: ignore[method-assign]  # noqa: SLF001
    site._collect_block_signals = lambda _context, _page: {  # type: ignore[method-assign]  # noqa: SLF001
        "price_or_payment": True,
        "station": True,
        "schedule": True,
        "duration": False,
        "block_card": True,
        "final_button": False,
    }
    site._collect_selfie_return_signals = lambda _page, _context: {  # type: ignore[method-assign]  # noqa: SLF001
        "file_input": True,
        "user_avatar": True,
        "continue_button": True,
        "selfie_text": True,
        "account_options": False,
        "selfie_container": True,
    }
    site._collect_processing_signals = lambda _page, _context: {  # type: ignore[method-assign]  # noqa: SLF001
        "processing_text": False,
        "processing_ui": False,
    }

    assert site._has_strong_block_signal("dialog", object()) is True  # type: ignore[arg-type]  # noqa: SLF001


def test_paripe_strong_block_signal_accepts_processing_residual_when_block_is_real() -> None:
    site = ParipeSite()
    site._resolve_block_context = lambda flow_context, _page: flow_context  # type: ignore[method-assign]  # noqa: SLF001
    site._collect_block_signals = lambda _context, _page: {  # type: ignore[method-assign]  # noqa: SLF001
        "price_or_payment": True,
        "station": True,
        "schedule": False,
        "duration": True,
        "block_card": True,
        "final_button": False,
    }
    site._collect_selfie_return_signals = lambda _page, _context: {  # type: ignore[method-assign]  # noqa: SLF001
        "file_input": False,
        "user_avatar": False,
        "continue_button": False,
        "selfie_text": False,
        "account_options": False,
        "selfie_container": False,
    }
    site._collect_processing_signals = lambda _page, _context: {  # type: ignore[method-assign]  # noqa: SLF001
        "processing_text": True,
        "processing_ui": False,
    }

    assert site._has_strong_block_signal("dialog", object()) is True  # type: ignore[arg-type]  # noqa: SLF001


def test_paripe_strong_block_signal_requires_price_station_time_and_container() -> None:
    site = ParipeSite()
    site._resolve_block_context = lambda flow_context, _page: flow_context  # type: ignore[method-assign]  # noqa: SLF001
    site._collect_block_signals = lambda _context, _page: {  # type: ignore[method-assign]  # noqa: SLF001
        "price_or_payment": True,
        "station": True,
        "schedule": False,
        "duration": True,
        "block_card": True,
        "final_button": True,
    }
    site._collect_selfie_return_signals = lambda _page, _context: {  # type: ignore[method-assign]  # noqa: SLF001
        "file_input": False,
        "user_avatar": False,
        "continue_button": False,
        "selfie_text": False,
        "account_options": False,
        "selfie_container": False,
    }
    site._collect_processing_signals = lambda _page, _context: {  # type: ignore[method-assign]  # noqa: SLF001
        "processing_text": False,
        "processing_ui": False,
    }

    assert site._has_strong_block_signal("dialog", object()) is True  # type: ignore[arg-type]  # noqa: SLF001


def test_paripe_final_result_uses_extension_engine_signal_when_available() -> None:
    site = ParipeSite()
    progress_events: list[tuple[str, str]] = []
    recorded_sources: list[str] = []
    engine_calls: list[tuple[str, str]] = []
    original_resolver = ExtensionFlowEngine.resolve_final_result_ready

    try:
        def fake_resolve_final_result_ready(cls, *, session, page, note: str = "wait_final_result_ready"):
            engine_calls.append(("final_result_ready", note))
            return SimpleNamespace(
                target_phase="final_result_ready",
                resolved=True,
                state={"phase": "final_result_ready"},
            )

        ExtensionFlowEngine.resolve_final_result_ready = classmethod(fake_resolve_final_result_ready)
        site._count_success_messages = lambda *_args, **_kwargs: 1  # type: ignore[method-assign]  # noqa: SLF001
        site._record_engine_resolution = lambda _session, _state, *, phase, source, note: recorded_sources.append(source)  # type: ignore[method-assign]  # noqa: SLF001
        site._result_signature = lambda *_args, **_kwargs: "baseline"  # type: ignore[method-assign]  # noqa: SLF001

        result = site._detect_final_result(  # noqa: SLF001
            object(),  # dialog
            object(),  # page
            timeout_ms=5_000,
            station_name="Estacion Demo",
            block_price="$93",
            block_time="05:00 am - 08:00 am",
            block_duration="3 horas",
            selfie_retry_count=0,
            deepfakescore_activated=False,
            reserved_photo_id="photo-1",
            progress_callback=lambda phase, message: progress_events.append((phase, message)),
            session=object(),
            extension_assisted=True,
        )
    finally:
        ExtensionFlowEngine.resolve_final_result_ready = original_resolver

    assert result.success is True
    assert engine_calls == [("final_result_ready", "wait_final_result_ready")]
    assert recorded_sources == ["extension"]
    assert any("final_result_ready" in message for _, message in progress_events)


def test_paripe_final_result_falls_back_to_polling_when_extension_signal_is_not_resolved() -> None:
    site = ParipeSite()
    recorded_sources: list[str] = []
    engine_calls: list[tuple[str, str]] = []
    original_resolver = ExtensionFlowEngine.resolve_final_result_ready

    try:
        def fake_resolve_final_result_ready(cls, *, session, page, note: str = "wait_final_result_ready"):
            engine_calls.append(("final_result_ready", note))
            return SimpleNamespace(
                target_phase="final_result_ready",
                resolved=False,
                state=None,
                reason="phase_unknown",
            )

        ExtensionFlowEngine.resolve_final_result_ready = classmethod(fake_resolve_final_result_ready)
        site._count_success_messages = lambda *_args, **_kwargs: 1  # type: ignore[method-assign]  # noqa: SLF001
        site._record_engine_resolution = lambda _session, _state, *, phase, source, note: recorded_sources.append(source)  # type: ignore[method-assign]  # noqa: SLF001
        site._result_signature = lambda *_args, **_kwargs: "baseline"  # type: ignore[method-assign]  # noqa: SLF001

        result = site._detect_final_result(  # noqa: SLF001
            object(),  # dialog
            object(),  # page
            timeout_ms=5_000,
            station_name="Estacion Demo",
            block_price="$93",
            block_time="05:00 am - 08:00 am",
            block_duration="3 horas",
            selfie_retry_count=0,
            deepfakescore_activated=False,
            reserved_photo_id="photo-1",
            progress_callback=None,
            session=object(),
            extension_assisted=True,
        )
    finally:
        ExtensionFlowEngine.resolve_final_result_ready = original_resolver

    assert result.success is True
    assert engine_calls == [("final_result_ready", "wait_final_result_ready")]
    assert recorded_sources == ["extension_fallback_polling"]


def test_paripe_block_read_uses_extension_engine_signal_when_available() -> None:
    site = ParipeSite()
    progress_events: list[tuple[str, str]] = []
    recorded_sources: list[str] = []
    engine_calls: list[str] = []
    current_context = object()
    block_context = object()
    original_resolver = ExtensionFlowEngine.resolve_block_read_ready

    try:
        def fake_resolve_block_read_ready(cls, *, session, page, note: str = "wait_block_read_ready"):
            engine_calls.append(note)
            return SimpleNamespace(
                target_phase="block_read_ready",
                resolved=True,
                state={"phase": "block_read_ready"},
            )

        ExtensionFlowEngine.resolve_block_read_ready = classmethod(fake_resolve_block_read_ready)
        site._resolve_current_flow_dialog = lambda _page, _flow_context: current_context  # type: ignore[method-assign]  # noqa: SLF001
        site._resolve_block_context = lambda _context, _page: block_context  # type: ignore[method-assign]  # noqa: SLF001
        site._collect_block_signals = lambda _context, _page: {"price_or_payment": True}  # type: ignore[method-assign]  # noqa: SLF001
        site._collect_selfie_return_signals = lambda _page, _context: {"selfie_text": False}  # type: ignore[method-assign]  # noqa: SLF001
        site._collect_processing_signals = lambda _page, _context: {"processing_text": False}  # type: ignore[method-assign]  # noqa: SLF001
        site._selfie_signal_diagnostics = lambda _page, _context: {"file_inputs": 0, "user_avatar": False, "continue_buttons": 0}  # type: ignore[method-assign]  # noqa: SLF001
        site._evaluate_block_candidate = lambda *_args, **_kwargs: {"confirmed": True, "discarded_reasons": [], "residual_reasons": [], "trigger_reasons": ["block card"]}  # type: ignore[method-assign]  # noqa: SLF001
        site._describe_live_dialog = lambda _context: "dialog"  # type: ignore[method-assign]  # noqa: SLF001
        site._looks_like_body_context = lambda _context: False  # type: ignore[method-assign]  # noqa: SLF001
        site._format_active_signals = lambda _signals: "price"  # type: ignore[method-assign]  # noqa: SLF001
        site._record_engine_resolution = lambda _session, _state, *, phase, source, note: recorded_sources.append(source)  # type: ignore[method-assign]  # noqa: SLF001

        result = site._wait_for_details_dialog(  # noqa: SLF001
            flow_context=object(),  # type: ignore[arg-type]
            page=object(),  # type: ignore[arg-type]
            progress_callback=lambda phase, message: progress_events.append((phase, message)),
            timeout_ms=5_000,
            session=object(),
            extension_assisted=True,
        )
    finally:
        ExtensionFlowEngine.resolve_block_read_ready = original_resolver

    assert result is block_context
    assert engine_calls == ["wait_block_read_ready"]
    assert recorded_sources == ["extension"]
    assert any("block_read_ready" in message for _, message in progress_events)


def test_paripe_block_read_falls_back_locally_when_extension_signal_is_missing() -> None:
    site = ParipeSite()
    recorded_sources: list[str] = []
    engine_calls: list[str] = []
    current_context = object()
    block_context = object()
    original_resolver = ExtensionFlowEngine.resolve_block_read_ready
    original_return_resolver = ExtensionFlowEngine.resolve_return_to_selfie

    try:
        def fake_resolve_block_read_ready(cls, *, session, page, note: str = "wait_block_read_ready"):
            engine_calls.append(note)
            return SimpleNamespace(
                target_phase="block_read_ready",
                resolved=False,
                state=None,
                reason="phase_unknown",
            )

        def fake_resolve_return_to_selfie(cls, *, session, page, note: str = "wait_return_to_selfie"):
            return SimpleNamespace(
                target_phase="return_to_selfie",
                resolved=False,
                state=None,
                reason="phase_unknown",
            )

        ExtensionFlowEngine.resolve_block_read_ready = classmethod(fake_resolve_block_read_ready)
        ExtensionFlowEngine.resolve_return_to_selfie = classmethod(fake_resolve_return_to_selfie)
        site._resolve_current_flow_dialog = lambda _page, _flow_context: current_context  # type: ignore[method-assign]  # noqa: SLF001
        site._resolve_block_context = lambda _context, _page: block_context  # type: ignore[method-assign]  # noqa: SLF001
        site._collect_block_signals = lambda _context, _page: {"price_or_payment": True}  # type: ignore[method-assign]  # noqa: SLF001
        site._collect_selfie_return_signals = lambda _page, _context: {"selfie_text": False}  # type: ignore[method-assign]  # noqa: SLF001
        site._collect_processing_signals = lambda _page, _context: {"processing_text": False}  # type: ignore[method-assign]  # noqa: SLF001
        site._selfie_signal_diagnostics = lambda _page, _context: {"file_inputs": 0, "user_avatar": False, "continue_buttons": 0}  # type: ignore[method-assign]  # noqa: SLF001
        site._evaluate_block_candidate = lambda *_args, **_kwargs: {"confirmed": True, "discarded_reasons": [], "residual_reasons": [], "trigger_reasons": ["block card"]}  # type: ignore[method-assign]  # noqa: SLF001
        site._describe_live_dialog = lambda _context: "dialog"  # type: ignore[method-assign]  # noqa: SLF001
        site._looks_like_body_context = lambda _context: False  # type: ignore[method-assign]  # noqa: SLF001
        site._format_active_signals = lambda _signals: "price"  # type: ignore[method-assign]  # noqa: SLF001
        site._record_engine_resolution = lambda _session, _state, *, phase, source, note: recorded_sources.append(source)  # type: ignore[method-assign]  # noqa: SLF001

        result = site._wait_for_details_dialog(  # noqa: SLF001
            flow_context=object(),  # type: ignore[arg-type]
            page=object(),  # type: ignore[arg-type]
            progress_callback=None,
            timeout_ms=5_000,
            session=object(),
            extension_assisted=True,
        )
    finally:
        ExtensionFlowEngine.resolve_block_read_ready = original_resolver
        ExtensionFlowEngine.resolve_return_to_selfie = original_return_resolver

    assert result is block_context
    assert engine_calls == ["wait_block_read_ready"]
    assert recorded_sources == ["extension_fallback_polling"]


def test_paripe_block_read_does_not_call_extension_api_when_extension_is_disabled() -> None:
    site = ParipeSite()
    block_context = object()
    original_resolver = ExtensionFlowEngine.resolve_block_read_ready

    try:
        def fail_resolve_block_read_ready(cls, *, session, page, note: str = "wait_block_read_ready"):
            raise AssertionError("No debe llamarse la API del motor extension cuando extension_assisted es False.")

        ExtensionFlowEngine.resolve_block_read_ready = classmethod(fail_resolve_block_read_ready)
        site._resolve_current_flow_dialog = lambda _page, _flow_context: block_context  # type: ignore[method-assign]  # noqa: SLF001
        site._resolve_block_context = lambda _context, _page: block_context  # type: ignore[method-assign]  # noqa: SLF001
        site._collect_block_signals = lambda _context, _page: {"price_or_payment": True}  # type: ignore[method-assign]  # noqa: SLF001
        site._collect_selfie_return_signals = lambda _page, _context: {"selfie_text": False}  # type: ignore[method-assign]  # noqa: SLF001
        site._collect_processing_signals = lambda _page, _context: {"processing_text": False}  # type: ignore[method-assign]  # noqa: SLF001
        site._selfie_signal_diagnostics = lambda _page, _context: {"file_inputs": 0, "user_avatar": False, "continue_buttons": 0}  # type: ignore[method-assign]  # noqa: SLF001
        site._evaluate_block_candidate = lambda *_args, **_kwargs: {"confirmed": True, "discarded_reasons": [], "residual_reasons": [], "trigger_reasons": ["block card"]}  # type: ignore[method-assign]  # noqa: SLF001
        site._describe_live_dialog = lambda _context: "dialog"  # type: ignore[method-assign]  # noqa: SLF001
        site._looks_like_body_context = lambda _context: False  # type: ignore[method-assign]  # noqa: SLF001
        site._format_active_signals = lambda _signals: "price"  # type: ignore[method-assign]  # noqa: SLF001
        site._record_engine_resolution = lambda *_args, **_kwargs: None  # type: ignore[method-assign]  # noqa: SLF001

        result = site._wait_for_details_dialog(  # noqa: SLF001
            flow_context=object(),  # type: ignore[arg-type]
            page=object(),  # type: ignore[arg-type]
            progress_callback=None,
            timeout_ms=5_000,
            session=object(),
            extension_assisted=False,
        )
    finally:
        ExtensionFlowEngine.resolve_block_read_ready = original_resolver

    assert result is block_context


def test_paripe_return_to_selfie_uses_extension_engine_signal_when_available() -> None:
    site = ParipeSite()
    engine_calls: list[str] = []
    original_block_resolver = ExtensionFlowEngine.resolve_block_read_ready
    original_return_resolver = ExtensionFlowEngine.resolve_return_to_selfie

    try:
        def fake_resolve_block_read_ready(cls, *, session, page, note: str = "wait_block_read_ready"):
            return SimpleNamespace(
                target_phase="block_read_ready",
                resolved=False,
                state=None,
                reason="phase_unknown",
            )

        def fake_resolve_return_to_selfie(cls, *, session, page, note: str = "wait_return_to_selfie"):
            engine_calls.append(note)
            return SimpleNamespace(
                target_phase="return_to_selfie",
                resolved=True,
                state={"phase": "return_to_selfie"},
                reason="phase_match",
            )

        ExtensionFlowEngine.resolve_block_read_ready = classmethod(fake_resolve_block_read_ready)
        ExtensionFlowEngine.resolve_return_to_selfie = classmethod(fake_resolve_return_to_selfie)
        site._resolve_current_flow_dialog = lambda _page, _flow_context: object()  # type: ignore[method-assign]  # noqa: SLF001
        site._resolve_block_context = lambda _context, _page: _context  # type: ignore[method-assign]  # noqa: SLF001
        site._collect_block_signals = lambda _context, _page: {"price_or_payment": False}  # type: ignore[method-assign]  # noqa: SLF001
        site._collect_selfie_return_signals = lambda _page, _context: {"file_input": True, "user_avatar": True, "continue_button": True, "selfie_text": True, "account_options": False, "selfie_container": True}  # type: ignore[method-assign]  # noqa: SLF001
        site._collect_processing_signals = lambda _page, _context: {"processing_text": False}  # type: ignore[method-assign]  # noqa: SLF001
        site._selfie_signal_diagnostics = lambda _page, _context: {"file_inputs": 1, "user_avatar": True, "continue_buttons": 1}  # type: ignore[method-assign]  # noqa: SLF001
        site._evaluate_block_candidate = lambda *_args, **_kwargs: {"confirmed": False, "discarded_reasons": [], "residual_reasons": [], "trigger_reasons": []}  # type: ignore[method-assign]  # noqa: SLF001
        site._describe_live_dialog = lambda _context: "dialog"  # type: ignore[method-assign]  # noqa: SLF001
        site._looks_like_body_context = lambda _context: False  # type: ignore[method-assign]  # noqa: SLF001
        site._format_active_signals = lambda _signals: "none"  # type: ignore[method-assign]  # noqa: SLF001
        site._selfie_phase_visible = lambda _page, _context: True  # type: ignore[method-assign]  # noqa: SLF001

        try:
            site._wait_for_details_dialog(  # noqa: SLF001
                flow_context=object(),  # type: ignore[arg-type]
                page=object(),  # type: ignore[arg-type]
                progress_callback=None,
                timeout_ms=5_000,
                session=None,
                extension_assisted=True,
            )
        except Exception:
            pass
    finally:
        ExtensionFlowEngine.resolve_block_read_ready = original_block_resolver
        ExtensionFlowEngine.resolve_return_to_selfie = original_return_resolver

    assert engine_calls == ["wait_return_to_selfie"]


def test_paripe_return_to_selfie_falls_back_locally_when_extension_signal_is_missing() -> None:
    site = ParipeSite()
    engine_calls: list[str] = []
    original_block_resolver = ExtensionFlowEngine.resolve_block_read_ready
    original_return_resolver = ExtensionFlowEngine.resolve_return_to_selfie

    try:
        def fake_resolve_block_read_ready(cls, *, session, page, note: str = "wait_block_read_ready"):
            return SimpleNamespace(
                target_phase="block_read_ready",
                resolved=False,
                state=None,
                reason="phase_unknown",
            )

        def fake_resolve_return_to_selfie(cls, *, session, page, note: str = "wait_return_to_selfie"):
            engine_calls.append(note)
            return SimpleNamespace(
                target_phase="return_to_selfie",
                resolved=False,
                state=None,
                reason="phase_unknown",
            )

        ExtensionFlowEngine.resolve_block_read_ready = classmethod(fake_resolve_block_read_ready)
        ExtensionFlowEngine.resolve_return_to_selfie = classmethod(fake_resolve_return_to_selfie)
        site._resolve_current_flow_dialog = lambda _page, _flow_context: object()  # type: ignore[method-assign]  # noqa: SLF001
        site._resolve_block_context = lambda _context, _page: _context  # type: ignore[method-assign]  # noqa: SLF001
        site._collect_block_signals = lambda _context, _page: {"price_or_payment": False}  # type: ignore[method-assign]  # noqa: SLF001
        site._collect_selfie_return_signals = lambda _page, _context: {"file_input": True, "user_avatar": True, "continue_button": True, "selfie_text": True, "account_options": False, "selfie_container": True}  # type: ignore[method-assign]  # noqa: SLF001
        site._collect_processing_signals = lambda _page, _context: {"processing_text": False}  # type: ignore[method-assign]  # noqa: SLF001
        site._selfie_signal_diagnostics = lambda _page, _context: {"file_inputs": 1, "user_avatar": True, "continue_buttons": 1}  # type: ignore[method-assign]  # noqa: SLF001
        site._evaluate_block_candidate = lambda *_args, **_kwargs: {"confirmed": False, "discarded_reasons": [], "residual_reasons": [], "trigger_reasons": []}  # type: ignore[method-assign]  # noqa: SLF001
        site._describe_live_dialog = lambda _context: "dialog"  # type: ignore[method-assign]  # noqa: SLF001
        site._looks_like_body_context = lambda _context: False  # type: ignore[method-assign]  # noqa: SLF001
        site._format_active_signals = lambda _signals: "none"  # type: ignore[method-assign]  # noqa: SLF001
        site._selfie_phase_visible = lambda _page, _context: True  # type: ignore[method-assign]  # noqa: SLF001

        try:
            site._wait_for_details_dialog(  # noqa: SLF001
                flow_context=object(),  # type: ignore[arg-type]
                page=object(),  # type: ignore[arg-type]
                progress_callback=None,
                timeout_ms=5_000,
                session=None,
                extension_assisted=True,
            )
        except Exception:
            pass
    finally:
        ExtensionFlowEngine.resolve_block_read_ready = original_block_resolver
        ExtensionFlowEngine.resolve_return_to_selfie = original_return_resolver

    assert engine_calls == ["wait_return_to_selfie"]


def test_paripe_selfie_stage_strict_mode_rejects_polling_fallback() -> None:
    site = ParipeSite()
    recorded_sources: list[str] = []
    page = SimpleNamespace(wait_for_timeout=lambda _ms: None)

    site._extension_state = lambda _session, _page, *, note: {"phase": "unknown", "diagnostics": {"note": note}}  # type: ignore[method-assign]  # noqa: SLF001
    site._extension_phase = lambda _state: "unknown"  # type: ignore[method-assign]  # noqa: SLF001
    site._dom_signature = lambda _page: ""  # type: ignore[method-assign]  # noqa: SLF001
    site._count_main_page_file_inputs = lambda _page: 1  # type: ignore[method-assign]  # noqa: SLF001
    site._page_has_continue = lambda _page: True  # type: ignore[method-assign]  # noqa: SLF001
    site._find_photo_phase_dialog = lambda _page: object()  # type: ignore[method-assign]  # noqa: SLF001
    site._dialog_has_file_input = lambda _dialog: True  # type: ignore[method-assign]  # noqa: SLF001
    site._dialog_has_continue = lambda _dialog: True  # type: ignore[method-assign]  # noqa: SLF001
    site._has_any_text = lambda _page, _markers: False  # type: ignore[method-assign]  # noqa: SLF001
    site._iframe_photo_phase_diagnostics = lambda _page: "diag"  # type: ignore[method-assign]  # noqa: SLF001
    site._record_engine_resolution = lambda _session, _state, *, phase, source, note: recorded_sources.append(source)  # type: ignore[method-assign]  # noqa: SLF001

    with pytest.raises(ParipeFlowError) as exc_info:
        site._wait_for_photo_phase(  # noqa: SLF001
            page,
            progress_callback=None,
            timeout_ms=5_000,
            session=object(),
            extension_assisted=True,
            extension_strict=True,
        )

    assert exc_info.value.final_status == "extension_incomplete"
    assert "Modo extension estricto" in exc_info.value.message
    assert recorded_sources == []


def test_paripe_block_phase_skips_selfie_stage_in_extension_mode() -> None:
    site = ParipeSite()
    progress_events: list[tuple[str, str]] = []
    session = SimpleNamespace(
        capture_extension_debug=lambda **_kwargs: {"state": {"phase": "block_read_ready"}},
        record_engine_phase_usage=lambda **_kwargs: None,
    )

    site._resolve_block_context = lambda _dialog, _page: "block-context"  # type: ignore[method-assign]  # noqa: SLF001
    site._upload_photo = lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("No debe intentar selfie_stage"))  # type: ignore[method-assign]  # noqa: SLF001

    block_context, reserved_photo, retry_count, deepfakescore_activated = site._complete_selfie_until_block(  # noqa: SLF001
        page=object(),  # type: ignore[arg-type]
        selfie_dialog=object(),  # type: ignore[arg-type]
        progress_callback=lambda phase, message: progress_events.append((phase, message)),
        action_timeout_ms=5_000,
        block_wait_ms=5_000,
        max_selfie_retries=2,
        session=session,
        extension_assisted=True,
        extension_strict=True,
    )

    assert block_context == "block-context"
    assert reserved_photo is None
    assert retry_count == 0
    assert deepfakescore_activated is False
    assert any("block_read_ready" in message for _, message in progress_events)


def test_paripe_block_read_strict_mode_rejects_polling_fallback() -> None:
    site = ParipeSite()
    recorded_sources: list[str] = []
    current_context = object()
    block_context = object()
    original_resolver = ExtensionFlowEngine.resolve_block_read_ready
    original_return_resolver = ExtensionFlowEngine.resolve_return_to_selfie

    try:
        def fake_resolve_block_read_ready(cls, *, session, page, note: str = "wait_block_read_ready"):
            return SimpleNamespace(
                target_phase="block_read_ready",
                resolved=False,
                state={"phase": "unknown"},
                reason="phase_unknown",
            )

        def fake_resolve_return_to_selfie(cls, *, session, page, note: str = "wait_return_to_selfie"):
            return SimpleNamespace(
                target_phase="return_to_selfie",
                resolved=False,
                state={"phase": "unknown"},
                reason="phase_unknown",
            )

        ExtensionFlowEngine.resolve_block_read_ready = classmethod(fake_resolve_block_read_ready)
        ExtensionFlowEngine.resolve_return_to_selfie = classmethod(fake_resolve_return_to_selfie)
        site._resolve_current_flow_dialog = lambda _page, _flow_context: current_context  # type: ignore[method-assign]  # noqa: SLF001
        site._resolve_block_context = lambda _context, _page: block_context  # type: ignore[method-assign]  # noqa: SLF001
        site._collect_block_signals = lambda _context, _page: {"price_or_payment": True}  # type: ignore[method-assign]  # noqa: SLF001
        site._collect_selfie_return_signals = lambda _page, _context: {"selfie_text": False, "user_avatar": False, "continue_button": False}  # type: ignore[method-assign]  # noqa: SLF001
        site._collect_processing_signals = lambda _page, _context: {"processing_text": False}  # type: ignore[method-assign]  # noqa: SLF001
        site._selfie_signal_diagnostics = lambda _page, _context: {"file_inputs": 0, "user_avatar": False, "continue_buttons": 0}  # type: ignore[method-assign]  # noqa: SLF001
        site._evaluate_block_candidate = lambda *_args, **_kwargs: {"confirmed": True, "discarded_reasons": [], "residual_reasons": [], "trigger_reasons": ["block card"]}  # type: ignore[method-assign]  # noqa: SLF001
        site._describe_live_dialog = lambda _context: "dialog"  # type: ignore[method-assign]  # noqa: SLF001
        site._looks_like_body_context = lambda _context: False  # type: ignore[method-assign]  # noqa: SLF001
        site._format_active_signals = lambda _signals: "price"  # type: ignore[method-assign]  # noqa: SLF001
        site._selfie_phase_visible = lambda _page, _context: False  # type: ignore[method-assign]  # noqa: SLF001
        site._record_engine_resolution = lambda _session, _state, *, phase, source, note: recorded_sources.append(source)  # type: ignore[method-assign]  # noqa: SLF001

        with pytest.raises(ParipeFlowError) as exc_info:
            site._wait_for_details_dialog(  # noqa: SLF001
                flow_context=object(),  # type: ignore[arg-type]
                page=object(),  # type: ignore[arg-type]
                progress_callback=None,
                timeout_ms=5_000,
                session=object(),
                extension_assisted=True,
                extension_strict=True,
            )
    finally:
        ExtensionFlowEngine.resolve_block_read_ready = original_resolver
        ExtensionFlowEngine.resolve_return_to_selfie = original_return_resolver

    assert exc_info.value.final_status == "extension_incomplete"
    assert "block_read_ready" in exc_info.value.message
    assert recorded_sources == []


def test_paripe_final_result_strict_mode_rejects_polling_fallback() -> None:
    site = ParipeSite()
    recorded_sources: list[str] = []
    original_resolver = ExtensionFlowEngine.resolve_final_result_ready

    try:
        def fake_resolve_final_result_ready(cls, *, session, page, note: str = "wait_final_result_ready"):
            return SimpleNamespace(
                target_phase="final_result_ready",
                resolved=False,
                state={"phase": "unknown"},
                reason="phase_unknown",
            )

        ExtensionFlowEngine.resolve_final_result_ready = classmethod(fake_resolve_final_result_ready)
        site._count_success_messages = lambda *_args, **_kwargs: 1  # type: ignore[method-assign]  # noqa: SLF001
        site._record_engine_resolution = lambda _session, _state, *, phase, source, note: recorded_sources.append(source)  # type: ignore[method-assign]  # noqa: SLF001
        site._result_signature = lambda *_args, **_kwargs: "baseline"  # type: ignore[method-assign]  # noqa: SLF001

        with pytest.raises(ParipeFlowError) as exc_info:
            site._detect_final_result(  # noqa: SLF001
                object(),
                object(),
                timeout_ms=5_000,
                station_name="Estacion Demo",
                block_price="$93",
                block_time="05:00 am - 08:00 am",
                block_duration="3 horas",
                selfie_retry_count=0,
                deepfakescore_activated=False,
                reserved_photo_id="photo-1",
                progress_callback=None,
                session=object(),
                extension_assisted=True,
                extension_strict=True,
            )
    finally:
        ExtensionFlowEngine.resolve_final_result_ready = original_resolver

    assert exc_info.value.final_status == "extension_incomplete"
    assert "final_result_ready" in exc_info.value.message
    assert recorded_sources == []


def test_paripe_final_submit_strict_mode_rejects_polling_fallback() -> None:
    site = ParipeSite()
    recorded_sources: list[str] = []

    class _FakeButton:
        def wait_for(self, *, state, timeout):
            return None

        def click(self, *, timeout):
            return None

    site._find_final_submit_button = lambda _dialog: _FakeButton()  # type: ignore[method-assign]  # noqa: SLF001
    site._extension_state = lambda _session, _page, *, note: {"phase": "unknown", "diagnostics": {"note": note}}  # type: ignore[method-assign]  # noqa: SLF001
    site._extension_phase = lambda _state: "unknown"  # type: ignore[method-assign]  # noqa: SLF001
    site._record_engine_resolution = lambda _session, _state, *, phase, source, note: recorded_sources.append(source)  # type: ignore[method-assign]  # noqa: SLF001

    with pytest.raises(ParipeFlowError) as exc_info:
        site._submit_final(  # noqa: SLF001
            object(),  # type: ignore[arg-type]
            object(),  # type: ignore[arg-type]
            timeout_ms=5_000,
            progress_callback=None,
            session=object(),
            extension_assisted=True,
            extension_strict=True,
        )

    assert exc_info.value.final_status == "extension_incomplete"
    assert "final_submit_ready" in exc_info.value.message
    assert recorded_sources == []
