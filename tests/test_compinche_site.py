from types import SimpleNamespace

from automation.compinche_site import CompincheSite, FlowRoot
from core.models import LocalConfig, ProcessExecutionRequest, ReservedPhoto, SiteExecutionResult
from services.process_run_context import ProcessRunContext


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
        page_name="Compinche",
        action_name="He llegado",
        phone_number="8095551234",
        password="secret",
        agent_name="Agente Local",
        execution_mode=execution_mode,
    )


def test_compinche_execute_traditional_routes_to_private_traditional_pipeline() -> None:
    site = CompincheSite()
    calls: list[tuple[str, str]] = []

    def fake_execute_traditional(request, *, local_config, progress_callback):
        calls.append(("traditional", request.execution_mode))
        return SiteExecutionResult(success=True, message="ok", final_status="success", phase="done")

    site._execute_traditional = fake_execute_traditional  # type: ignore[method-assign]  # noqa: SLF001

    result = site.execute_traditional(_request(execution_mode="testing"), local_config=_local_config())

    assert result.success is True
    assert calls == [("traditional", "traditional")]


def test_compinche_execute_extension_routes_to_private_extension_pipeline() -> None:
    site = CompincheSite()
    calls: list[tuple[str, str]] = []

    def fake_execute_extension(request, *, local_config, progress_callback):
        calls.append(("extension", request.execution_mode))
        return SiteExecutionResult(success=True, message="ok", final_status="success", phase="done")

    site._execute_extension = fake_execute_extension  # type: ignore[method-assign]  # noqa: SLF001

    result = site.execute_extension(_request(execution_mode="testing"), local_config=_local_config())

    assert result.success is True
    assert calls == [("extension", "extension")]


def test_compinche_action_mapping_keeps_each_ui_action_separate() -> None:
    site = CompincheSite()

    instantaneas = site._get_action_spec("He llegado Instantaneas")  # noqa: SLF001
    he_llegado = site._get_action_spec("He llegado")  # noqa: SLF001
    selfie = site._get_action_spec("Selfie en ruta")  # noqa: SLF001

    assert instantaneas.ui_name == "He llegado Instantaneas"
    assert "i arrived snapshots" in instantaneas.phrases
    assert he_llegado.ui_name == "He llegado"
    assert selfie.ui_name == "Selfie en ruta"
    assert site._normalize_text(" He llegado\nInstantaneas ") == "he llegado instantaneas"  # noqa: SLF001
    assert site._score_action_match("he llegado", he_llegado) > 0  # noqa: SLF001
    assert site._score_action_match("he llegado instantaneas", he_llegado) == 0  # noqa: SLF001


def test_compinche_action_mapping_accepts_known_language_variants() -> None:
    site = CompincheSite()

    instantaneas = site._get_action_spec("He llegado Instantaneas")  # noqa: SLF001
    he_llegado = site._get_action_spec("He llegado")  # noqa: SLF001
    selfie = site._get_action_spec("Selfie en ruta")  # noqa: SLF001

    assert site._score_action_match("i arrived snapshots", instantaneas) >= 80  # noqa: SLF001
    assert site._score_action_match("cheguei", he_llegado) >= 80  # noqa: SLF001
    assert site._score_action_match("selfie em rota", selfie) >= 80  # noqa: SLF001


def test_compinche_action_mapping_rejects_unknown_action() -> None:
    site = CompincheSite()

    try:
        site._get_action_spec("He llegado inventado")  # noqa: SLF001
    except RuntimeError as exc:
        assert "Accion de compinche.io no soportada" in str(exc)
    else:
        raise AssertionError("Expected _get_action_spec to reject unsupported actions.")


class _FakeLoginButton:
    def __init__(self, *, text: str = "", submit_type: str | None = None) -> None:
        self._text = text
        self._submit_type = submit_type

    def inner_text(self, timeout: int = 400) -> str:
        return self._text

    def get_attribute(self, name: str):
        if name == "type":
            return self._submit_type
        return None


def test_compinche_login_button_scoring_prefers_real_submit_button() -> None:
    site = CompincheSite()

    generic = _FakeLoginButton(text="Entrar")
    submit = _FakeLoginButton(text="Entrar", submit_type="submit")

    assert site._score_login_submit_candidate(submit) > site._score_login_submit_candidate(generic)  # noqa: SLF001


class _FakeFrame:
    def __init__(self, url: str, title: str = "") -> None:
        self.url = url
        self._title = title

    def frame_element(self):
        return self

    def get_attribute(self, name: str):
        if name == "title":
            return self._title
        return None

    def locator(self, _selector: str):
        raise RuntimeError("not used in this test")


def test_compinche_frame_scoring_prioritizes_paripe_and_stripe_wrappers() -> None:
    site = CompincheSite()
    action = site._get_action_spec("He llegado")  # noqa: SLF001

    paripe_frame = _FakeFrame("https://paripe.io/imhere-light?token=abc", "He llegado")
    stripe_wrapper = _FakeFrame("https://js.stripe.com/v3/controller-with-preconnect.html#url=https://paripe.io/imhere-light?token=abc")

    assert site._score_frame(paripe_frame, action) >= 10  # noqa: SLF001
    assert site._score_frame(stripe_wrapper, action) >= 8  # noqa: SLF001


def test_compinche_extract_text_pairs_reads_variable_block_fields() -> None:
    site = CompincheSite()

    pairs = site._extract_text_pairs(  # noqa: SLF001
        "\n".join(
            (
                "Estacion",
                "Bronx NY (VNY2) - Sub Same-Day",
                "Precio",
                "RD$ 300",
                "Horario",
                "15/04/2026 05:00 am - 08:00 am",
                "Duracion",
                "3 horas",
            )
        )
    )

    assert pairs["estacion"] == "Bronx NY (VNY2) - Sub Same-Day"
    assert pairs["precio"] == "RD$ 300"
    assert pairs["horario"] == "15/04/2026 05:00 am - 08:00 am"
    assert pairs["duracion"] == "3 horas"


def test_compinche_extract_schedule_candidates_filters_station_like_lines() -> None:
    site = CompincheSite()

    candidates = site._extract_schedule_candidates(  # noqa: SLF001
        "\n".join(
            (
                "Bronx NY (VNY2) - Sub Same-Day",
                "15/04/2026 05:00 am - 08:00 am",
            )
        )
    )

    assert candidates == ["15/04/2026 05:00 am - 08:00 am"]


def test_compinche_primary_flow_root_keeps_detected_iframe() -> None:
    site = CompincheSite()
    iframe = _FakeFrame("https://paripe.io/imhere-light?token=abc", "He llegado")
    flow_root = FlowRoot(root=iframe, phase="iframe_entry", description="iframe", is_iframe=True)

    resolved = site._resolve_primary_flow_root(page=None, flow_root=flow_root)  # type: ignore[arg-type]  # noqa: SLF001

    assert resolved is iframe


def test_compinche_primary_flow_root_prefers_live_iframe_when_initial_root_is_not_iframe() -> None:
    site = CompincheSite()
    iframe = _FakeFrame("https://paripe.io/imhere-light?token=xyz", "He llegado")
    site._find_any_live_flow_frame = lambda _page: iframe  # type: ignore[method-assign]  # noqa: SLF001
    fallback_root = object()
    flow_root = FlowRoot(root=fallback_root, phase="modal_check", description="modal", is_iframe=False)

    resolved = site._resolve_primary_flow_root(page=object(), flow_root=flow_root)  # type: ignore[arg-type]  # noqa: SLF001

    assert resolved is iframe


def test_compinche_block_detection_does_not_accept_final_button_alone() -> None:
    site = CompincheSite()
    fake_root = object()
    site._collect_block_signals = lambda _root: {  # type: ignore[method-assign]  # noqa: SLF001
        "price_or_payment": False,
        "station": False,
        "schedule": False,
        "duration": False,
        "block_card": False,
        "final_button": True,
    }
    site._count_definition_terms = lambda _root: 0  # type: ignore[method-assign]  # noqa: SLF001

    looks_like_block = site._root_looks_like_block("he llegado", fake_root)  # noqa: SLF001

    assert looks_like_block is False


def test_compinche_result_signature_uses_only_iframe_context() -> None:
    site = CompincheSite()
    site._normalized_root_text = lambda root: "iframe success text" if root == "iframe" else "page popup text"  # type: ignore[method-assign]  # noqa: SLF001

    signature = site._result_signature("iframe")  # type: ignore[arg-type]  # noqa: SLF001

    assert signature == "iframe success text"


def test_compinche_retry_root_prefers_refreshed_iframe_when_selfie_reappears() -> None:
    site = CompincheSite()
    refreshed_iframe = _FakeFrame("https://paripe.io/imhere-light?token=retry", "He llegado")
    site._resolve_current_flow_context = lambda _page, _previous_root: "stale-root"  # type: ignore[method-assign]  # noqa: SLF001
    site._find_any_live_flow_frame = lambda _page: refreshed_iframe  # type: ignore[method-assign]  # noqa: SLF001
    site._selfie_phase_visible = lambda root: root is refreshed_iframe  # type: ignore[method-assign]  # noqa: SLF001

    resolved = site._resolve_selfie_retry_root(page=object(), previous_root="old-root")  # type: ignore[arg-type]  # noqa: SLF001

    assert resolved is refreshed_iframe


def test_compinche_processing_state_blocks_premature_block_detection() -> None:
    site = CompincheSite()
    fake_root = object()
    site._collect_processing_signals = lambda _root: {"processing_text": True, "processing_ui": False}  # type: ignore[method-assign]  # noqa: SLF001
    site._selfie_phase_visible = lambda _root: False  # type: ignore[method-assign]  # noqa: SLF001
    site._collect_block_signals = lambda _root: {  # type: ignore[method-assign]  # noqa: SLF001
        "price_or_payment": True,
        "station": False,
        "schedule": False,
        "duration": False,
        "block_card": False,
        "final_button": False,
    }

    assert site._has_strong_block_signal(fake_root) is False  # noqa: SLF001
    assert site._root_looks_like_block("precio", fake_root) is False  # noqa: SLF001


def test_compinche_strong_block_signal_accepts_processing_residual_when_block_is_real() -> None:
    site = CompincheSite()
    fake_root = object()
    site._collect_processing_signals = lambda _root: {"processing_text": True, "processing_ui": False}  # type: ignore[method-assign]  # noqa: SLF001
    site._selfie_phase_visible = lambda _root: False  # type: ignore[method-assign]  # noqa: SLF001
    site._collect_block_signals = lambda _root: {  # type: ignore[method-assign]  # noqa: SLF001
        "price_or_payment": True,
        "station": True,
        "schedule": False,
        "duration": True,
        "block_card": True,
        "final_button": False,
    }

    assert site._has_strong_block_signal(fake_root) is True  # noqa: SLF001
    assert site._root_looks_like_block("precio estacion duracion", fake_root) is True  # noqa: SLF001


def test_compinche_selfie_retry_reason_triggers_on_selfie_screen_without_block() -> None:
    site = CompincheSite()
    site._has_strong_block_signal = lambda _root: False  # type: ignore[method-assign]  # noqa: SLF001

    reason = site._selfie_retry_reason(  # noqa: SLF001
        "iframe",
        {
            "file_input": True,
            "user_avatar": True,
            "continue_button": True,
            "selfie_text": False,
            "account_options": False,
            "selfie_form": False,
        },
    )

    assert reason == "user_avatar + Continuar + texto_selfie reaparecieron sin bloque real"


def test_compinche_selfie_signals_treat_continue_count_as_real_presence() -> None:
    site = CompincheSite()
    site._count_selectors = lambda _root, selectors: 1 if "#user_avatar" in selectors or "input[type='file']" in selectors else 0  # type: ignore[method-assign]  # noqa: SLF001
    site._count_continue_buttons = lambda _root: 1  # type: ignore[method-assign]  # noqa: SLF001
    site._has_any_selector_now = lambda _root, _selectors: False  # type: ignore[method-assign]  # noqa: SLF001
    site._normalized_root_text = lambda _root: "selfie"  # type: ignore[method-assign]  # noqa: SLF001

    signals = site._collect_selfie_return_signals("iframe")  # type: ignore[arg-type]  # noqa: SLF001

    assert signals["continue_button"] is True
    assert signals["user_avatar"] is True
    assert signals["file_input"] is True


class _FakePhotoService:
    def __init__(self) -> None:
        self.consumed: list[str] = []
        self.deleted: list[str] = []

    def consume_photo(self, photo_id: str) -> None:
        self.consumed.append(photo_id)

    def delete_local_copy(self, local_path: str) -> None:
        self.deleted.append(local_path)


def test_compinche_iframe_flow_moves_directly_from_block_read_to_final_submit() -> None:
    photo_service = _FakePhotoService()
    site = CompincheSite(photo_service=photo_service)
    run_context = ProcessRunContext(
        process_id="proc-1",
        page_name="Compinche",
        action_name="He llegado",
        phone_number="8095551234",
        execution_mode="traditional",
        log_service=object(),
    )
    site.attach_run_context(run_context)
    progress_events: list[tuple[str, str]] = []
    reserved_photo = ReservedPhoto(
        photo_id="photo-1",
        storage_path="bucket/photo-1.jpg",
        local_path="C:/tmp/photo-1.jpg",
        original_filename="photo-1.jpg",
    )

    site._complete_selfie_until_block = lambda *_args, **_kwargs: ("block-root", reserved_photo, 2, False)  # type: ignore[method-assign]  # noqa: SLF001
    site._read_block_data = lambda *_args, **_kwargs: ("Estacion Demo", "RD$ 300", "15/04/2026 05:00 am - 08:00 am", "3 horas")  # type: ignore[method-assign]  # noqa: SLF001
    site._resolve_block_context = lambda _page, root: f"{root}-resolved"  # type: ignore[method-assign]  # noqa: SLF001
    site._count_final_submit_buttons = lambda root: 1 if root == "block-root-resolved" else 0  # type: ignore[method-assign]  # noqa: SLF001
    site._submit_final = lambda root, **_kwargs: f"{root}-submitted"  # type: ignore[method-assign]  # noqa: SLF001
    site._detect_final_result = lambda *_args, **_kwargs: SiteExecutionResult(  # type: ignore[method-assign]  # noqa: SLF001
        success=True,
        message="OK",
        final_status="success",
        phase="final_result",
        station_name="Estacion Demo",
        block_price="RD$ 300",
        block_time="15/04/2026 05:00 am - 08:00 am",
        block_duration="3 horas",
        selfie_retry_count=2,
        reserved_photo_id="photo-1",
    )

    def fail_if_wait_called(*_args, **_kwargs) -> None:
        raise AssertionError("No debe ejecutarse una espera de estabilizacion del bloque.")

    site._wait_interval = fail_if_wait_called  # type: ignore[method-assign]  # noqa: SLF001

    result = site._execute_iframe_flow(  # noqa: SLF001
        page=object(),  # type: ignore[arg-type]
        flow_root="iframe-root",  # type: ignore[arg-type]
        progress_callback=lambda phase, message: progress_events.append((phase, message)),
        action_timeout_ms=5_000,
        block_wait_ms=30_000,
        max_selfie_retries=2,
    )

    assert result.success is True
    assert ("block_read", "Esperando estabilizacion del bloque...") not in progress_events
    assert ("block_read", "Informacion del bloque detectada.") not in progress_events
    assert ("block_read", "Bloque detectado. Leyendo informacion del bloque...") in progress_events
    assert ("final_submit", "Boton final He llegado detectado. Candidatos encontrados: 1.") in progress_events
    assert photo_service.consumed == ["photo-1"]
    assert photo_service.deleted == ["C:/tmp/photo-1.jpg"]
    recorded_events = [item["event"] for item in run_context.run_stats.export_timeline()]
    assert "final_result_started" in recorded_events
    assert "final_result_done" in recorded_events


def test_compinche_block_phase_skips_selfie_stage_in_extension_mode() -> None:
    site = CompincheSite()
    progress_events: list[tuple[str, str]] = []
    session = SimpleNamespace(
        capture_extension_debug=lambda **_kwargs: {"state": {"phase": "block_read_ready"}},
        record_engine_phase_usage=lambda **_kwargs: None,
    )

    site._resolve_block_context = lambda _page, _root: "block-root"  # type: ignore[method-assign]  # noqa: SLF001
    site._require_photo_input = lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("No debe intentar selfie_stage"))  # type: ignore[method-assign]  # noqa: SLF001

    block_context, reserved_photo, retry_count, deepfakescore_activated = site._complete_selfie_until_block(  # noqa: SLF001
        root="iframe-root",  # type: ignore[arg-type]
        page=object(),  # type: ignore[arg-type]
        progress_callback=lambda phase, message: progress_events.append((phase, message)),
        action_timeout_ms=5_000,
        block_wait_ms=5_000,
        max_selfie_retries=2,
        session=session,
        extension_assisted=True,
    )

    assert block_context == "block-root"
    assert reserved_photo is None
    assert retry_count == 0
    assert deepfakescore_activated is False
    assert any("block_read_ready" in message for _, message in progress_events)


def test_compinche_timing_summary_uses_combined_site_validation_and_block_click() -> None:
    site = CompincheSite()
    site._timing_first_by_event = {
        "process_started": {"elapsed_total_s": 0.0},
        "login_started": {"elapsed_total_s": 0.0},
        "login_done": {"elapsed_total_s": 1.0},
        "photo_prepare_started": {"elapsed_total_s": 1.0},
        "photo_prepare_done": {"elapsed_total_s": 2.0},
        "continue_clicked": {"elapsed_total_s": 5.0},
        "block_visual_detected": {"elapsed_total_s": 9.0},
        "final_click_done": {"elapsed_total_s": 11.0},
        "final_result_done": {"elapsed_total_s": 14.0},
        "process_finished": {"elapsed_total_s": 15.0},
    }

    summary = site._build_timing_summary()  # noqa: SLF001
    summary_text = site._build_timing_summary_text()  # noqa: SLF001

    assert summary["validacion_sitio"] == "4.0s"
    assert summary["bloqueclick"] == "2.0s"
    assert "selfie" not in summary
    assert "bloque 4.0s" not in summary_text
    assert "validacion sitio 4.0s" in summary_text
