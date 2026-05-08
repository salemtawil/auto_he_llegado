from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import datetime
from time import monotonic, sleep
import re
import unicodedata

from automation.base_site import BaseSite, ProgressCallback
from automation.browser_manager import BrowserManager
from automation.engines.extension import ExtensionFlowEngine, ExtensionPhaseDecider
from core.models import LocalConfig, ProcessExecutionRequest, ReservedPhoto, SiteExecutionResult
from services.process_photo_service import ProcessPhotoService

from playwright.sync_api import Locator, Page
from contextlib import suppress

_WHITESPACE_RE = re.compile(r"\s+")
_TIME_RANGE_RE = re.compile(
    r"\b\d{1,2}:\d{2}\s*(?:am|pm)\s*-\s*\d{1,2}:\d{2}\s*(?:am|pm)\b",
    re.IGNORECASE,
)
_DURATION_RE = re.compile(
    r"\b\d+(?:[.,]\d+)?\s*(?:horas?|hours?|hrs?)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ParipeSelectors:
    login_phone: tuple[str, ...] = (
    'input[name="phone-number"]',
    'input[id="phone-number"]',
    'input[type="tel"]',
    'input[placeholder*="teléfono" i]',
    'input[placeholder*="telefono" i]',
    'input[placeholder*="phone" i]',
    )
    login_password: tuple[str, ...] = (
    'input[name="password"]',
    'input[id="password"]',
    'input[type="password"]',
    'input[placeholder*="contraseña" i]',
    'input[placeholder*="contrasena" i]',
    'input[placeholder*="password" i]',
    )
    login_submit: tuple[str, ...] = (
        'button[type="submit"]:has-text("Ingresar")',
        'button[type="submit"]',
    )
    login_failure_texts: tuple[str, ...] = (
        "credenciales incorrectas",
        "contrasena incorrecta",
        "contraseña incorrecta",
        "telefono o contrasena incorrectos",
        "teléfono o contraseña incorrectos",
        "error al iniciar sesion",
    )
    dashboard_texts: tuple[str, ...] = (
        "Cuenta prestada",
        "Cuenta propia",
        "He llegado",
        "I'm here",
        "I've arrived",
        "Eu cheguei",
        "Selfie en ruta",
        "In route selfie",
        "Route selfie",
        "Selfie na rota",
    )
    account_switch: str = 'button[role="switch"]'
    borrowed_account_texts: tuple[str, ...] = ("Cuenta prestada", "Borrowed account", "Conta emprestada")
    own_account_texts: tuple[str, ...] = ("Cuenta propia", "Own account", "Personal account", "Conta propria", "Conta própria")
    selfie_dialog: str = '[role="dialog"][aria-modal="true"]'
    file_input: str = '#user_avatar, input[type="file"]'
    continue_texts: tuple[str, ...] = ("Continuar", "Continue", "Prosseguir")
    details_dialog: str = '[role="dialog"][aria-modal="true"]'
    selfie_instruction_texts: tuple[str, ...] = (
        "para continuar, selecciona una opcion y tomate una foto tipo selfie",
        "para continuar",
        "selecciona una opcion",
        "foto tipo selfie",
        "tomate una foto tipo selfie",
        "toma una foto tipo selfie",
        "to continue, select an option and take a selfie",
        "take a selfie",
        "to continue",
        "select an option",
        "para continuar, selecione uma opcao e tire uma foto tipo selfie",
        "para continuar, selecione uma opção e tire uma foto tipo selfie",
        "tire uma foto tipo selfie",
        "selecione uma opcao",
        "selecione uma opção",
        "selfie",
    )
    selfie_option_texts: tuple[str, ...] = (
        "cuenta propia",
        "cuenta prestada",
        "own account",
        "personal account",
        "borrowed account",
        "conta propria",
        "conta própria",
        "conta emprestada",
    )
    processing_texts: tuple[str, ...] = (
        "validamos su foto",
        "validando",
        "validating",
        "validacao",
        "subiendo foto",
        "uploading",
        "procesando",
        "processing",
        "processando",
        "cargando",
        "loading",
        "carregando",
        "verificando",
        "verifying",
    )
    processing_selectors: tuple[str, ...] = (
        "[aria-busy='true']",
        "[role='progressbar']",
        "[class*='loading']",
        "[class*='spinner']",
        "[class*='progress']",
        "[class*='validating']",
    )
    final_submit_texts: tuple[str, ...] = ("He llegado", "I'm here", "I've arrived", "I arrived", "Eu cheguei", "Cheguei")
    success_markers: tuple[str, ...] = (
        "estoy aqui exitoso",
        "estoy aquí exitoso",
        "proceso exitoso",
        "he llegado exitoso",
    )
    success_markers: tuple[str, ...] = (
        "estoy aqui exitoso",
        "estoy aquÃ­ exitoso",
        "proceso exitoso",
        "he llegado exitoso",
        "i'm here successful",
        "i've arrived successful",
        "eu cheguei com sucesso",
    )
    failure_markers: tuple[str, ...] = (
        "error",
        "fallo",
        "intenta de nuevo",
        "no pudimos",
    )


@dataclass(frozen=True)
class ParipeActionSpec:
    ui_name: str
    aliases: tuple[str, ...]
    phrases: tuple[str, ...]
    required_token_groups: tuple[tuple[str, ...], ...]
    forbidden_tokens: tuple[str, ...] = ()


class ParipeFlowError(RuntimeError):
    def __init__(self, phase: str, message: str, *, final_status: str = "failed") -> None:
        super().__init__(message)
        self.phase = phase
        self.message = message
        self.final_status = final_status


@dataclass
class BackgroundPhotoPreparation:
    process_id: str | None
    ready_event: threading.Event = field(default_factory=threading.Event)
    reserved_photo: ReservedPhoto | None = None
    error: Exception | None = None
    consumed: bool = False


class ParipeSite(BaseSite):
    site_name = "paripe.io"
    _ENTRY_URL = "https://paripe.io/login"
    _SHORT_WAIT_MS = 75
    _POST_ACTION_WAIT_MS = 12_000
    _POST_ACTION_MAX_WAIT_MS = 18_000
    _DOM_STABLE_GRACE_MS = 700
    _PARTIAL_SIGNAL_GRACE_MS = 1_200
    _SELFIE_REBOUND_WAIT_MS = 12_000
    _SELFIE_REBOUND_STABLE_MS = 1_200
    _BLOCK_WAIT_POLL_MS = 75

    def __init__(
        self,
        browser_manager: BrowserManager | None = None,
        photo_service: ProcessPhotoService | None = None,
        selectors: ParipeSelectors | None = None,
    ) -> None:
        self._browser_manager = browser_manager or BrowserManager()
        self._photo_service = photo_service or ProcessPhotoService()
        self._selectors = selectors or ParipeSelectors()
        self._process_timeline: list[dict[str, object]] = []
        self._phase_timings: list[dict[str, object]] = []
        self._timing_started_at: float | None = None
        self._timing_last_event_at: float | None = None
        self._timing_first_by_event: dict[str, dict[str, object]] = {}
        self._timing_lock = threading.Lock()
        self._last_final_button_candidate: dict[str, object] | None = None
        self._last_process_debug_export: dict[str, object] = {}
        self._active_flow_context: Locator | None = None

    def _reset_process_debug_state(self) -> None:
        self._process_timeline = []
        self._phase_timings = []
        self._timing_started_at = None
        self._timing_last_event_at = None
        self._timing_first_by_event = {}
        self._last_final_button_candidate = None
        self._last_process_debug_export = {}
        self._active_flow_context = None

    def _record_timeline_event(self, event: str, **payload: object) -> None:
        self._process_timeline.append(
            {
                "event": event,
                "recorded_at": datetime.now().isoformat(),
                **payload,
            }
        )

    def _mark_phase_timing(self, event: str, **payload: object) -> None:
        with self._timing_lock:
            now = monotonic()
            if self._timing_started_at is None:
                self._timing_started_at = now
            elapsed_total_s = round(now - self._timing_started_at, 3)
            elapsed_since_previous_s = (
                0.0
                if self._timing_last_event_at is None
                else round(now - self._timing_last_event_at, 3)
            )
            elapsed_ms = int(elapsed_total_s * 1000)
            delta_ms = int(elapsed_since_previous_s * 1000)
            entry = {
                "event": event,
                "timestamp": datetime.now().isoformat(),
                "elapsed_ms": elapsed_ms,
                "delta_ms": delta_ms,
                "elapsed_total_s": elapsed_total_s,
                "elapsed_since_previous_s": elapsed_since_previous_s,
                **payload,
            }
            self._phase_timings.append(entry)
            self._timing_last_event_at = now
            self._timing_first_by_event.setdefault(event, dict(entry))
        self._record_timeline_event(
            event,
            timestamp=entry["timestamp"],
            elapsed_ms=elapsed_ms,
            delta_ms=delta_ms,
            elapsed_total_s=elapsed_total_s,
            elapsed_since_previous_s=elapsed_since_previous_s,
            **payload,
        )

    def _timing_delta(self, start_event: str, end_event: str) -> float | None:
        start_entry = self._timing_first_by_event.get(start_event)
        end_entry = self._timing_first_by_event.get(end_event)
        if not start_entry or not end_entry:
            return None
        return round(float(end_entry["elapsed_total_s"]) - float(start_entry["elapsed_total_s"]), 1)

    @staticmethod
    def _format_timing_value(value: float | None) -> str | None:
        if value is None:
            return None
        return f"{value:.1f}s"

    def _build_timing_summary(self) -> dict[str, str]:
        summary = {
            "total": self._format_timing_value(self._timing_delta("process_started", "process_finished")),
            "login": self._format_timing_value(self._timing_delta("login_started", "login_done")),
            "photo_prepare": self._format_timing_value(self._timing_delta("photo_prepare_started", "photo_prepare_done")),
            "selfie_input_to_upload": self._format_timing_value(self._timing_delta("selfie_input_detected", "photo_upload_started")),
            "photo_upload": self._format_timing_value(self._timing_delta("photo_upload_started", "photo_upload_done")),
            "site_selfie_processing": self._format_timing_value(self._timing_delta("continue_clicked", "block_visual_detected")),
            "block_visible_to_click": self._format_timing_value(self._timing_delta("block_visual_detected", "final_click_done")),
        }
        return {key: value for key, value in summary.items() if value is not None}

    def _build_timing_summary_text(self) -> str:
        summary = self._build_timing_summary()
        parts: list[str] = []
        label_map = {
            "login": "login",
            "photo_prepare": "foto prep",
            "selfie_input_to_upload": "inputupload",
            "photo_upload": "photo upload",
            "site_selfie_processing": "validacion sitio",
            "block_visible_to_click": "bloqueclick",
            "total": "total",
        }
        for key in ("login", "photo_prepare", "selfie_input_to_upload", "site_selfie_processing", "block_visible_to_click", "total"):
            value = summary.get(key)
            if value:
                parts.append(f"{label_map[key]} {value}")
        return "Resumen tiempos: " + " | ".join(parts) if parts else ""

    def _emit_timing_summary(self, progress_callback: ProgressCallback | None) -> None:
        summary = self._build_timing_summary_text()
        if summary:
            self.emit_progress(progress_callback, phase="timing", message=summary)

    def export_process_debug_state(self) -> dict[str, object]:
        return {
            "site": self.site_name,
            "timeline": [dict(item) for item in self._process_timeline],
            "phase_timings": [dict(item) for item in self._phase_timings],
            "timing_summary": self._build_timing_summary(),
            "timing_summary_text": self._build_timing_summary_text(),
            "last_final_button_candidate": dict(self._last_final_button_candidate or {}),
            "last_process_debug_export": dict(self._last_process_debug_export),
        }

    def _start_background_photo_preparation(
        self,
        *,
        process_id: str | None,
        progress_callback: ProgressCallback | None,
    ) -> BackgroundPhotoPreparation:
        preparation = BackgroundPhotoPreparation(process_id=process_id)
        self._mark_phase_timing("photo_prepare_future_created", process_id=process_id)
        self.emit_progress(progress_callback, phase="photo_prepare", message="preparando foto en background tras login")

        def worker() -> None:
            try:
                self._mark_phase_timing("photo_prepare_started", process_id=process_id, source="background")
                preparation.reserved_photo = self._photo_service.reserve_photo(process_id=process_id)
                self._mark_phase_timing(
                    "photo_prepare_done",
                    process_id=process_id,
                    photo_id=preparation.reserved_photo.photo_id if preparation.reserved_photo else None,
                )
                self.emit_progress(progress_callback, phase="photo_prepare", message="foto preparada antes del input selfie")
            except Exception as exc:
                preparation.error = exc
                self._mark_phase_timing("photo_prepare_failed", process_id=process_id, error=str(exc))
            finally:
                preparation.ready_event.set()

        threading.Thread(target=worker, daemon=True).start()
        return preparation

    def _await_background_photo(
        self,
        preparation: BackgroundPhotoPreparation | None,
        *,
        progress_callback: ProgressCallback | None,
        process_id: str | None,
    ) -> tuple[ReservedPhoto, bool]:
        if preparation is None:
            self._record_timeline_event("photo_prepare_future_missing_at_selfie_input", process_id=process_id)
            self.emit_progress(progress_callback, phase="photo_prepare", message="photo_prepare_future_missing_at_selfie_input")
            self._mark_phase_timing("photo_future_wait_started", process_id=process_id, fallback=True)
            reserved_photo = self._photo_service.reserve_photo(process_id=process_id)
            self._mark_phase_timing("photo_future_wait_done", process_id=process_id, fallback=True)
            self._mark_phase_timing("photo_prepare_done", process_id=process_id, photo_id=reserved_photo.photo_id)
            return reserved_photo, False

        ready_before_input = preparation.ready_event.is_set()
        self._record_timeline_event("photo_ready_before_input", ready=ready_before_input, process_id=process_id)
        if ready_before_input:
            self.emit_progress(progress_callback, phase="photo_prepare", message="input selfie detectado: usando foto ya preparada")
        else:
            self.emit_progress(progress_callback, phase="photo_prepare", message="esperando future de foto existente")
            self._mark_phase_timing("photo_future_wait_started", process_id=process_id)
            preparation.ready_event.wait()
            self._mark_phase_timing("photo_future_wait_done", process_id=process_id)
        if preparation.error is not None:
            self.emit_progress(progress_callback, phase="photo_prepare", message=f"photo_prepare_failed: {preparation.error}")
            raise preparation.error
        if preparation.reserved_photo is None:
            raise RuntimeError("La preparación de foto en background terminó sin una foto reservada.")
        preparation.consumed = True
        return preparation.reserved_photo, ready_before_input

    def _discard_background_photo(self, preparation: BackgroundPhotoPreparation | None) -> None:
        if preparation is None or not preparation.ready_event.is_set() or preparation.consumed:
            return
        reserved_photo = preparation.reserved_photo
        if reserved_photo is None:
            return
        with suppress(Exception):
            self._photo_service.release_photo(reserved_photo.photo_id)
        with suppress(Exception):
            self._photo_service.delete_local_copy(reserved_photo.local_path)

    def _set_active_flow_context(
        self,
        context: Locator | None,
        *,
        page: Page | None,
        source: str,
    ) -> Locator | None:
        if context is None:
            return None
        if self._looks_like_body_context(context):
            self._record_timeline_event("dashboard_body_discarded_as_flow_context", source=source)
            return None
        reacquired = self._active_flow_context is None
        self._active_flow_context = context
        if reacquired and "start" not in source and "detected" not in source:
            self._record_timeline_event("flow_context_reacquired", source=source, url=page.url if page is not None else "")
        self._record_timeline_event(
            "flow_context_detected",
            source=source,
            url=page.url if page is not None else "",
            context_summary=self._describe_live_dialog(context),
        )
        return context

    def _get_active_flow_context(self, page: Page) -> Locator | None:
        context = self._active_flow_context
        if context is None:
            return None
        if self._locator_is_live(context):
            return context
        self._record_timeline_event("flow_context_lost", url=page.url)
        self._active_flow_context = None
        return None

    def _get_supported_action_specs(self) -> tuple[ParipeActionSpec, ...]:
        return (
            ParipeActionSpec(
                "He llegado instantáneo",
                (
                    "He llegado instantáneo",
                    "He llegado Instantáneo",
                    "He llegado instantaneo",
                    "He llegado Instantáneas",
                    "He llegado instantaneas",
                    "He llegado Instantaneo",
                    "He llegado Instantaneas",
                    "Instantáneo",
                    "Instantáneas",
                    "Instantaneo",
                    "Instantaneas",
                    "I'm here instant offers",
                    "I've arrived instant",
                    "Instant offers",
                    "Eu cheguei Instantâneo",
                    "Eu cheguei Instantaneo",
                    "Eu cheguei instantaneo",
                ),
                (
                    "he llegado instantaneo",
                    "he llegado instantaneas",
                    "instantaneo",
                    "instantaneas",
                    "i'm here instant offers",
                    "i've arrived instant",
                    "instant offers",
                    "eu cheguei instantaneo",
                ),
                (
                    ("instantaneas", "instantaneo", "instant", "offers"),
                ),
                ("selfie", "ruta", "route", "rota"),
            ),
            ParipeActionSpec(
                "He llegado",
                ("He llegado", "I'm here", "I've arrived", "I arrived", "Eu cheguei", "Cheguei"),
                ("he llegado", "i'm here", "i've arrived", "i arrived", "eu cheguei", "cheguei"),
                (("he llegado", "i'm here", "i've arrived", "i arrived", "eu cheguei", "cheguei"),),
                ("instantaneas", "instantaneo", "instant", "offers", "selfie", "ruta", "route", "rota"),
            ),
            ParipeActionSpec(
                "Selfie en ruta",
                ("Selfie en ruta", "In route selfie", "Route selfie", "Selfie on route", "Selfie na rota", "Selfie em rota"),
                ("selfie en ruta", "in route selfie", "route selfie", "selfie on route", "selfie on the way", "selfie na rota", "selfie em rota"),
                (("selfie",), ("ruta", "route", "way", "rota")),
            ),
        )

    def _get_action_spec(self, action_name: str) -> ParipeActionSpec:
        normalized_name = self._normalize_text(action_name)
        specs = self._get_supported_action_specs()
        for spec in specs:
            aliases = {self._normalize_text(spec.ui_name), *(self._normalize_text(alias) for alias in spec.aliases)}
            if normalized_name in aliases:
                return spec
        allowed = ", ".join(spec.ui_name for spec in specs)
        raise ParipeFlowError("initial_action", f"Accion de paripe.io no soportada: '{action_name}'. Opciones validas: {allowed}")

    def _score_action_match(self, text: str, action_spec: ParipeActionSpec) -> int:
        normalized_text = self._normalize_text(text)
        if not normalized_text:
            return 0
        if any(token and token in normalized_text for token in action_spec.forbidden_tokens):
            return 0
        score = 0
        normalized_aliases = tuple(self._normalize_text(alias) for alias in action_spec.aliases)
        for alias in normalized_aliases:
            if not alias:
                continue
            if normalized_text == alias:
                score = max(score, 120)
            elif alias in normalized_text:
                score = max(score, 95)
        for phrase in action_spec.phrases:
            if phrase and phrase in normalized_text:
                score = max(score, 85)
        for group in action_spec.required_token_groups:
            if any(token and token in normalized_text for token in group):
                score += 35
            else:
                return 0
        return score

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
        normalized_request = request.model_copy(update={"execution_mode": "traditional"})
        return self._execute_traditional(
            normalized_request,
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
        normalized_request = request.model_copy(update={"execution_mode": "extension"})
        return self._execute_extension(
            normalized_request,
            local_config=local_config,
            progress_callback=progress_callback,
        )

    def _execute_traditional(
        self,
        request: ProcessExecutionRequest,
        *,
        local_config: LocalConfig,
        progress_callback: ProgressCallback | None = None,
    ) -> SiteExecutionResult:
        return self._execute_pipeline(
            request,
            local_config=local_config,
            progress_callback=progress_callback,
        )

    def _execute_extension(
        self,
        request: ProcessExecutionRequest,
        *,
        local_config: LocalConfig,
        progress_callback: ProgressCallback | None = None,
    ) -> SiteExecutionResult:
        return self._execute_pipeline(
            request,
            local_config=local_config,
            progress_callback=progress_callback,
        )

    def _execute_pipeline(
        self,
        request: ProcessExecutionRequest,
        *,
        local_config: LocalConfig,
        progress_callback: ProgressCallback | None = None,
    ) -> SiteExecutionResult:
        self._reset_process_debug_state()
        self._mark_phase_timing("process_started", process_id=getattr(request, "process_id", None))
        self._photo_service.validate_atomic_reservation_support()
        extension_engine_requested = self._use_extension_engine(local_config, request)
        extension_strict = str(request.execution_mode or "").strip().lower() == "extension"
        self._mark_phase_timing("browser_open_started", engine="extension" if extension_engine_requested else "traditional")
        session = self._browser_manager.open_clean_session(
            keep_open=local_config.keep_browser_open,
            enable_extension=extension_engine_requested,
            extension_overlay=local_config.browser_extension_overlay,
        )
        self._mark_phase_timing("browser_open_done", extension_loaded=session.extension_loaded)
        reserved_photo: ReservedPhoto | None = None
        prepared_photo: BackgroundPhotoPreparation | None = None
        selfie_retry_count = 0
        deepfakescore_activated = False
        self._final_submit_already_clicked = False
        self._final_submit_fast_clicked_at = None
        self._latest_block_snapshot_text = ""
        self._active_flow_context = None
        page = session.page
        page_timeout_ms = max(local_config.page_timeout_seconds, 1) * 1000
        action_timeout_ms = max(local_config.action_timeout_seconds, 1) * 1000
        block_wait_ms = max(getattr(local_config, "paripe_block_wait_seconds", 120), 1) * 1000
        try:
            self.emit_progress(
                progress_callback,
                phase="engine",
                message="creando sesion limpia para paripe.io",
            )
            self.emit_progress(
                progress_callback,
                phase="engine",
                message="cache-only no disponible, usando modo limpio",
            )
            self.emit_progress(
                progress_callback,
                phase="engine",
                message=f"Motor de flujo activo: {'Extensión' if extension_engine_requested else 'Tradicional'}.",
            )
            if extension_engine_requested and not session.extension_loaded:
                self.emit_progress(
                    progress_callback,
                    phase="engine",
                    message="La extensión no quedó cargada. Fallback automático al flujo tradicional.",
                )
            elif extension_engine_requested:
                self.emit_progress(
                    progress_callback,
                    phase="engine",
                    message="Extensión cargada. Se usarán señales publicadas para acelerar detección de fases cuando estén disponibles.",
                )
            if extension_engine_requested:
                self.emit_progress(
                    progress_callback,
                    phase="engine",
                    message="sesion previa limpiada. contexto nuevo listo",
                )
            self.emit_progress(progress_callback, phase="login", message="Abriendo paripe.io/login...")
            self._mark_phase_timing("login_started", url=self._ENTRY_URL)
            self._open_login(page, timeout_ms=page_timeout_ms)
            cleanup_report = session.clear_auth_state(page=page)
            self._record_timeline_event("session_state_cleared", **cleanup_report)
            self.emit_progress(progress_callback, phase="login", message="estado de sesión limpiado")
            self.emit_progress(progress_callback, phase="login", message="login limpio confirmado")
            session.capture_extension_debug(page=page, note="login_page_opened")
            self._perform_login(
                page,
                request=request,
                progress_callback=progress_callback,
                timeout_ms=page_timeout_ms,
            )
            self._mark_phase_timing("login_done", url=page.url)
            session.capture_extension_debug(page=page, note="login_completed")
            self.emit_progress(
                progress_callback,
                phase="account_selection",
                message="Validacion de cuenta omitida. Continuando directo al flujo.",
            )
            session.capture_extension_debug(page=page, note="account_selection_skipped")
            prepared_photo = self._start_background_photo_preparation(
                process_id=getattr(request, "process_id", None),
                progress_callback=progress_callback,
            )

            action_spec = self._get_action_spec(request.action_name)
            self.emit_progress(progress_callback, phase="initial_action", message=f"Ejecutando accion '{action_spec.ui_name}'...")
            self._mark_phase_timing("initial_action_started", action=action_spec.ui_name)
            self._click_initial_action(page, request.action_name, timeout_ms=action_timeout_ms)
            self._mark_phase_timing("initial_action_clicked", action=action_spec.ui_name, url=page.url)
            session.capture_extension_debug(page=page, note="initial_action_clicked")
            self.emit_progress(progress_callback, phase="initial_action", message="Accion inicial presionada.")
            self._mark_phase_timing("iframe_wait_started", source="photo_phase")
            selfie_dialog = self._wait_for_photo_phase(
                page,
                progress_callback=progress_callback,
                timeout_ms=max(action_timeout_ms, self._POST_ACTION_WAIT_MS),
                session=session,
                extension_assisted=extension_engine_requested and session.extension_loaded,
                extension_strict=extension_strict,
            )
            self._set_active_flow_context(selfie_dialog, page=page, source="photo_phase_detected")
            self._mark_phase_timing("iframe_detected", source="photo_phase", url=page.url)
            session.capture_extension_debug(page=page, note="photo_phase_detected")
            self._record_timeline_event("photo_phase_detected", url=page.url)
            details_context, reserved_photo, selfie_retry_count, deepfakescore_activated = self._complete_selfie_until_block(
                page,
                selfie_dialog=selfie_dialog,
                progress_callback=progress_callback,
                action_timeout_ms=action_timeout_ms,
                block_wait_ms=block_wait_ms,
                max_selfie_retries=local_config.max_selfie_retries,
                process_id=getattr(request, "process_id", None),
                prepared_photo=prepared_photo,
                session=session,
                extension_assisted=extension_engine_requested and session.extension_loaded,
                extension_strict=extension_strict,
            )
            self._set_active_flow_context(details_context, page=page, source="block_context_ready")
            session.capture_extension_debug(page=page, note="block_ready_after_selfie")
            self._record_timeline_event("block_read_ready", url=page.url)
            block_ready_at = monotonic()
            snapshot_text = getattr(self, "_latest_block_snapshot_text", "") or self._capture_block_snapshot_text(details_context, page)
            self._latest_block_snapshot_text = ""
            payment = station = schedule = duration = "N/A"
            final_submit_already_clicked = bool(getattr(self, "_final_submit_already_clicked", False))
            active_context = self._get_active_flow_context(page)
            fast_snapshot = (
                self._fast_context_snapshot(active_context)
                if active_context is not None
                else self._fast_block_snapshot(page)
            )
            snapshot_selfie_active = bool(
                fast_snapshot.get("hasSelfieInput", False)
                or fast_snapshot.get("hasSelfieText", False)
                or fast_snapshot.get("hasContinueButton", False)
            )
            snapshot_processing_active = bool(fast_snapshot.get("hasProcessingText", False))
            fast_block_signal_count = sum(
                1
                for enabled in (
                    fast_snapshot.get("hasPaymentText", False),
                    fast_snapshot.get("hasStationText", False),
                    fast_snapshot.get("hasScheduleText", False),
                    fast_snapshot.get("hasDurationText", False),
                    fast_snapshot.get("hasBlockCardLike", False),
                )
                if enabled
            )
            final_button_visible = (
                fast_snapshot.get("hasFinalButton", False)
                and fast_block_signal_count >= 3
                and not fast_snapshot.get("hasSelfieInput", False)
                and not fast_snapshot.get("hasSelfieText", False)
                and not fast_snapshot.get("hasProcessingText", False)
            )
            if final_submit_already_clicked:
                self.emit_progress(progress_callback, phase="final_submit", message="botón final visible: click inmediato")
            elif final_button_visible:
                self.emit_progress(progress_callback, phase="final_submit", message="botón final visible: click inmediato")
            else:
                self.emit_progress(progress_callback, phase="block_read", message="Leyendo informacion del bloque...")
                payment, station, schedule, duration = self._read_block_details(
                    details_context,
                    page=page,
                    progress_callback=progress_callback,
                )
                self._record_timeline_event(
                    "block_details_read",
                    payment=payment,
                    station=station,
                    schedule=schedule,
                    duration=duration,
                )
                self.emit_progress(
                    progress_callback,
                    phase="block_read",
                    message=(
                        f"Bloque detectado. Pago: {payment}. Estacion: {station}. "
                        f"Horario: {schedule}. Duracion: {duration}."
                    ),
                )
                self.emit_progress(
                    progress_callback,
                    phase="block_read",
                    message="Datos del bloque guardados para resultado final y process_logs.",
                )
            self.emit_progress(progress_callback, phase="block_read", message=f"Reintentos de selfie: {selfie_retry_count}.")
            if not final_submit_already_clicked:
                self._submit_final(
                    details_context,
                    page,
                    timeout_ms=min(action_timeout_ms, 1_000),
                    progress_callback=progress_callback,
                    session=session,
                    extension_assisted=extension_engine_requested and session.extension_loaded,
                    extension_strict=extension_strict,
                )
            click_elapsed_ms = int(
                ((getattr(self, "_final_submit_fast_clicked_at", 0.0) or monotonic()) - block_ready_at) * 1000
            ) if final_submit_already_clicked else int((monotonic() - block_ready_at) * 1000)
            self.emit_progress(
                progress_callback,
                phase="final_submit",
                message=f"Tiempo block_read -> click final: {click_elapsed_ms} ms",
            )
            if final_submit_already_clicked or final_button_visible:
                payment, station, schedule, duration = self._read_block_details_from_snapshot_text(snapshot_text)
                if (
                    not final_submit_already_clicked
                    and payment == "N/A"
                    and station == "N/A"
                    and schedule == "N/A"
                    and duration == "N/A"
                ) and not snapshot_selfie_active and not snapshot_processing_active:
                    try:
                        self.emit_progress(progress_callback, phase="block_read", message="Leyendo informacion del bloque...")
                        payment, station, schedule, duration = self._read_block_details(
                            details_context,
                            page=page,
                            progress_callback=progress_callback,
                        )
                    except Exception:
                        pass
                self.emit_progress(
                    progress_callback,
                    phase="block_read",
                    message=(
                        f"Bloque detectado. Pago: {payment}. Estacion: {station}. "
                        f"Horario: {schedule}. Duracion: {duration}."
                    ),
                )
                self.emit_progress(
                    progress_callback,
                    phase="block_read",
                    message="Datos del bloque guardados para resultado final y process_logs.",
                )
                self._record_timeline_event(
                    "block_details_read",
                    payment=payment,
                    station=station,
                    schedule=schedule,
                    duration=duration,
                )
            session.capture_extension_debug(page=page, note="final_submit_clicked")
            self._record_timeline_event("final_button_clicked", url=page.url)
            self.emit_progress(progress_callback, phase="final_submit", message="Boton final He llegado presionado.")
            self.emit_progress(progress_callback, phase="final_result", message="Esperando confirmacion final...")
            self._mark_phase_timing("final_result_started", url=page.url)
            result = self._detect_final_result(
                details_context,
                page,
                timeout_ms=block_wait_ms,
                station_name=station,
                block_price=payment,
                block_time=schedule,
                block_duration=duration,
                selfie_retry_count=selfie_retry_count,
                deepfakescore_activated=deepfakescore_activated,
                reserved_photo_id=reserved_photo.photo_id if reserved_photo else None,
                progress_callback=progress_callback,
                session=session,
                extension_assisted=extension_engine_requested and session.extension_loaded,
                extension_strict=extension_strict,
            )
            self._mark_phase_timing("final_result_done", success=result.success, final_status=result.final_status, url=page.url)
            session.capture_extension_debug(page=page, note="final_result_detected")
            self._record_timeline_event(
                "final_result_detected",
                success=result.success,
                final_status=result.final_status,
                url=page.url,
            )
            self._last_process_debug_export = {
                "last_url": page.url,
                "final_status": result.final_status,
                "success": result.success,
                "timing_summary": self._build_timing_summary(),
                "timing_summary_text": self._build_timing_summary_text(),
            }
            self._mark_phase_timing("process_finished", success=result.success, final_status=result.final_status)
            self._emit_timing_summary(progress_callback)
            return result
        except ParipeFlowError as exc:
            self._mark_phase_timing("process_finished", success=False, final_status=exc.final_status, phase=exc.phase)
            self._emit_timing_summary(progress_callback)
            return SiteExecutionResult(
                success=False,
                message=exc.message,
                final_status=exc.final_status,
                phase=exc.phase,
                selfie_retry_count=selfie_retry_count,
                deepfakescore_activated=deepfakescore_activated,
                reserved_photo_id=reserved_photo.photo_id if reserved_photo else None,
            )
        except Exception as exc:
            self._mark_phase_timing("process_finished", success=False, final_status="failed", phase="unexpected")
            self._emit_timing_summary(progress_callback)
            return SiteExecutionResult(
                success=False,
                message=f"Fallo en flujo real de paripe.io: {exc}",
                final_status="failed",
                phase="unexpected",
                selfie_retry_count=selfie_retry_count,
                deepfakescore_activated=deepfakescore_activated,
                reserved_photo_id=reserved_photo.photo_id if reserved_photo else None,
            )
        finally:
            try:
                with suppress(Exception):
                    cleanup_report = session.clear_auth_state(page=page)
                    self._record_timeline_event("session_state_cleared_on_finish", **cleanup_report)
                self._discard_background_photo(prepared_photo)
                if reserved_photo is not None:
                    self._photo_service.consume_photo(reserved_photo.photo_id)
                    self._photo_service.delete_local_copy(reserved_photo.local_path)
            finally:
                session.close()

    def _open_login(self, page: Page, *, timeout_ms: int) -> None:
        def _navigate_to_login_defensively() -> None:
            # With real Chrome over CDP, navigation can remain "loading" even when the login page is already usable.
            try:
                page.goto(self._ENTRY_URL, wait_until="commit", timeout=10_000)
            except Exception:
                with suppress(Exception):
                    page.goto(self._ENTRY_URL, timeout=10_000)

        print(f"Paripe traditional initial_url={self._ENTRY_URL}")
        _navigate_to_login_defensively()

        page.wait_for_timeout(3_000)

        if "paripe.io/login" not in page.url:
            _navigate_to_login_defensively()
            page.wait_for_timeout(3_000)

        phone_input = self._first_visible(page, self._selectors.login_phone, timeout_ms=8_000)
        password_input = self._first_visible(page, self._selectors.login_password, timeout_ms=8_000)
        print(
            "Paripe traditional login_inputs_found "
            f"phone={phone_input is not None} password={password_input is not None} current_url={page.url}"
        )

    def _perform_login(
        self,
        page: Page,
        *,
        request: ProcessExecutionRequest,
        progress_callback: ProgressCallback | None,
        timeout_ms: int,
    ) -> None:
        self._fill_first(page, self._selectors.login_phone, request.phone_number)
        self._fill_first(page, self._selectors.login_password, request.password)
        self.emit_progress(progress_callback, phase="login", message="Credenciales completadas.")
        submit = self._first_visible(page, self._selectors.login_submit, timeout_ms=2_500)
        self._click_locator_resilient(
            submit,
            phase="login",
            error_message="No se pudo presionar el boton de ingreso en paripe.io.",
        )
        self.emit_progress(progress_callback, phase="login", message="Formulario enviado. Esperando dashboard...")
        outcome = self._wait_for_login_outcome(page, timeout_ms=timeout_ms)
        if outcome == "success":
            self.emit_progress(progress_callback, phase="login", message="Login exitoso. Dashboard detectado.")
            return
        if outcome == "failure":
            raise ParipeFlowError(
                "login",
                "Login fallido: paripe.io no acepto el telefono o la contrasena.",
                final_status="login_failed",
            )
        raise ParipeFlowError(
            "login",
            "Login fallido: no aparecio el dashboard de paripe.io despues de enviar las credenciales.",
            final_status="login_failed",
        )

    def _wait_for_login_outcome(self, page: Page, *, timeout_ms: int) -> str:
        deadline = monotonic() + (timeout_ms / 1000)
        while monotonic() < deadline:
            if "/app" in page.url and self._has_any_text(page, self._selectors.dashboard_texts):
                return "success"
            if self._has_any_text(page, self._selectors.login_failure_texts):
                return "failure"
            page.wait_for_timeout(self._SHORT_WAIT_MS)
        return "timeout"

    def _ensure_borrowed_account_selected(
        self,
        page: Page,
        *,
        timeout_ms: int,
        progress_callback: ProgressCallback | None = None,
    ) -> None:
        borrowed = self._find_button_by_labels(page.locator("body").first, self._selectors.borrowed_account_texts)
        own = self._find_button_by_labels(page.locator("body").first, self._selectors.own_account_texts)
        switch = page.locator(self._selectors.account_switch).first
        if borrowed is None or own is None:
            raise ParipeFlowError("account_selection", "No se localizaron las opciones de cuenta en paripe.io.")
        borrowed.wait_for(state="visible", timeout=timeout_ms)
        own.wait_for(state="visible", timeout=timeout_ms)
        switch.wait_for(state="visible", timeout=timeout_ms)
        initial_state = self._account_selection_state(page)
        self.emit_progress(
            progress_callback,
            phase="account_selection",
            message=f"Cuenta detectada inicialmente: {initial_state}.",
        )
        if initial_state == "borrowed":
            return
        self.emit_progress(
            progress_callback,
            phase="account_selection",
            message="Intento de cambio a Cuenta prestada.",
        )
        targets = [borrowed, switch]
        for target in targets:
            try:
                self._click_locator_resilient(
                    target,
                    phase="account_selection",
                    error_message="No se pudo seleccionar Cuenta prestada en paripe.io.",
                )
            except Exception:
                continue
            try:
                self._wait_for(
                    lambda: self._account_selection_state(page) == "borrowed",
                    timeout_ms=min(timeout_ms, 2_000),
                    phase="account_selection",
                    error_message="retry",
                )
                break
            except ParipeFlowError:
                continue
        self._wait_for(
            lambda: self._account_selection_state(page) == "borrowed",
            timeout_ms=timeout_ms,
            phase="account_selection",
            error_message=(
                "No se pudo confirmar la seleccion de 'Cuenta prestada'. "
                "Selector fino a revisar: button[role='switch'] y estados visuales de la tarjeta."
            ),
        )
        self.emit_progress(
            progress_callback,
            phase="account_selection",
            message="Validacion final del cambio: Cuenta prestada activa.",
        )

    def _is_borrowed_account_selected(self, page: Page) -> bool:
        return self._account_selection_state(page) == "borrowed"

    def _account_selection_state(self, page: Page) -> str:
        switch = page.locator(self._selectors.account_switch).first
        borrowed = self._find_button_by_labels(page.locator("body").first, self._selectors.borrowed_account_texts)
        own = self._find_button_by_labels(page.locator("body").first, self._selectors.own_account_texts)
        if borrowed is None or own is None:
            return "unknown"
        try:
            switch_state = (switch.get_attribute("aria-checked") or "").strip().lower()
        except Exception:
            switch_state = ""
        borrowed_classes = self._normalize_text(borrowed.get_attribute("class") or "")
        own_classes = self._normalize_text(own.get_attribute("class") or "")
        if (
            switch_state == "false"
            or "text-primary-500" in borrowed_classes
            or ("font-semibold" in borrowed_classes and "text-gray-500" in own_classes)
        ):
            return "borrowed"
        if (
            switch_state == "true"
            or "text-primary-500" in own_classes
            or ("font-semibold" in own_classes and "text-gray-500" in borrowed_classes)
        ):
            return "own"
        return "unknown"

    def _click_initial_action(self, page: Page, action_name: str, *, timeout_ms: int) -> None:
        action_spec = self._get_action_spec(action_name)
        buttons = page.locator("body").first.locator("button, [role='button'], a")
        deadline = monotonic() + (timeout_ms / 1000)
        best_button: Locator | None = None
        best_score = 0
        last_seen_texts: list[str] = []
        while monotonic() < deadline:
            try:
                count = buttons.count()
            except Exception:
                count = 0
            for index in range(count):
                button = buttons.nth(index)
                try:
                    if not self._locator_is_clickable_candidate(button):
                        continue
                except Exception:
                    continue
                text = self._safe_text(button)
                if text:
                    last_seen_texts.append(text.strip())
                score = self._score_action_match(text, action_spec)
                if score > best_score:
                    best_score = score
                    best_button = button
            if best_button is not None and best_score >= 80:
                self._click_locator_resilient(
                    best_button,
                    phase="initial_action",
                    error_message=f"No se pudo presionar la accion '{action_spec.ui_name}' en paripe.io.",
                )
                return
            page.wait_for_timeout(self._SHORT_WAIT_MS)
        if best_button is not None and best_score > 0:
            self._click_locator_resilient(
                best_button,
                phase="initial_action",
                error_message=f"No se pudo presionar la accion '{action_spec.ui_name}' en paripe.io.",
            )
            return
        seen = ", ".join(dict.fromkeys(filter(None, last_seen_texts[:10]))) or "sin textos visibles"
        raise ParipeFlowError(
            "initial_action",
            f"No se encontro la accion '{action_spec.ui_name}' con variantes por idioma en paripe.io. Textos visibles: {seen}",
        )

    def _find_button_by_labels(self, context: Locator, labels: tuple[str, ...]) -> Locator | None:
        buttons = context.locator("button, [role='button'], a")
        try:
            count = buttons.count()
        except Exception:
            return None
        normalized_labels = tuple(self._normalize_text(label) for label in labels)
        best_button: Locator | None = None
        best_score = 0
        for index in range(count):
            button = buttons.nth(index)
            try:
                if not self._locator_is_clickable_candidate(button):
                    continue
            except Exception:
                continue
            text = self._safe_normalized_text(button)
            score = 0
            for label in normalized_labels:
                if not label:
                    continue
                if text == label:
                    score = max(score, 100)
                elif label in text:
                    score = max(score, 90)
            if score > best_score:
                best_score = score
                best_button = button
        return best_button if best_score > 0 else None

    def _wait_for_selfie_dialog(self, page: Page, *, timeout_ms: int) -> Locator:
        deadline = monotonic() + (timeout_ms / 1000)
        while monotonic() < deadline:
            dialog = page.locator(self._selectors.selfie_dialog).filter(
                has=page.locator(self._selectors.file_input)
            ).last
            try:
                dialog.wait_for(state="visible", timeout=400)
                return dialog
            except Exception:
                pass
            page.wait_for_timeout(self._SHORT_WAIT_MS)
        raise ParipeFlowError(
            "photo_upload",
            "No aparecieron el input file y el boton Continuar despues de la accion inicial.",
        )

    def _wait_for_photo_phase(
        self,
        page: Page,
        *,
        progress_callback: ProgressCallback | None,
        timeout_ms: int,
        session=None,
        extension_assisted: bool = False,
        extension_strict: bool = False,
    ) -> Locator:
        minimum_deadline = monotonic() + (max(timeout_ms, self._POST_ACTION_WAIT_MS) / 1000)
        hard_deadline = monotonic() + (max(timeout_ms, self._POST_ACTION_MAX_WAIT_MS) / 1000)
        last_dom_signature = ""
        last_dom_change_at = monotonic()
        continue_reported = False
        file_reported = False
        waiting_reported = False
        page_diagnostics_reported = False
        iframe_diagnostics_reported = False
        partial_signal_at: float | None = None
        resolution_logged = False
        while monotonic() < hard_deadline:
            if not waiting_reported:
                self.emit_progress(
                    progress_callback,
                    phase="photo_upload",
                    message="Esperando fase de carga de foto...",
                )
                waiting_reported = True
            if extension_assisted:
                extension_state = self._extension_state(session, page, note="wait_photo_phase")
                extension_phase = self._extension_phase(extension_state)
                if extension_state is not None and extension_phase in {"iframe_entry", "selfie_stage"}:
                    dialog = self._find_photo_phase_dialog(page)
                    if dialog is not None:
                        self.emit_progress(
                            progress_callback,
                            phase="photo_upload",
                            message=f"Extensión detectó fase {extension_state.get('phase')}. Revalidando selfie_stage con prioridad.",
                        )
                        self._record_engine_resolution(session, extension_state, phase=extension_phase, source="extension", note="photo_phase")
                        self.emit_progress(progress_callback, phase="photo_upload", message=f"{extension_phase} resuelto por extensión")
                        resolution_logged = True
                        return dialog
                elif extension_state is not None and self._extension_phase_action(extension_phase) != "unknown":
                    dialog = self._find_photo_phase_dialog(page)
                    self.emit_progress(
                        progress_callback,
                        phase="photo_upload",
                        message=f"ExtensiÃ³n reporta fase actual {extension_phase}. Se evita esperar selfie_stage de forma rÃ­gida.",
                    )
                    return dialog or page.locator("body").first
            dom_signature = self._dom_signature(page)
            if dom_signature and dom_signature != last_dom_signature:
                last_dom_signature = dom_signature
                last_dom_change_at = monotonic()
            main_file_inputs = self._count_main_page_file_inputs(page)
            main_has_continue = self._page_has_continue(page)
            if not page_diagnostics_reported:
                self.emit_progress(
                    progress_callback,
                    phase="photo_upload",
                    message=(
                        "Buscando fase de foto en page principal. "
                        f"input[type=file] en page: {main_file_inputs}. "
                        f"Continuar en page: {'si' if main_has_continue else 'no'}."
                    ),
                )
                page_diagnostics_reported = True
            dialog = self._find_photo_phase_dialog(page)
            if main_file_inputs > 0 and self._dialog_has_file_input(dialog):
                if not file_reported:
                    self.emit_progress(
                        progress_callback,
                        phase="photo_upload",
                        message=f"Input file detectado en page principal. Total en page: {main_file_inputs}.",
                    )
                    file_reported = True
                    partial_signal_at = monotonic()
                if main_has_continue and self._dialog_has_continue(dialog):
                    if not continue_reported:
                        self.emit_progress(
                            progress_callback,
                            phase="photo_upload",
                            message="Continuar detectado en page principal.",
                        )
                        continue_reported = True
                    if not resolution_logged:
                        if extension_strict:
                            raise self._build_extension_strict_error(
                                phase="selfie_stage",
                                reason="phase_unknown",
                                state=self._extension_state(session, page, note="wait_photo_phase"),
                            )
                        self._record_engine_resolution(session, None, phase="selfie_stage", source="polling tradicional", note="photo_phase")
                        self.emit_progress(progress_callback, phase="photo_upload", message="selfie_stage detectado por polling tradicional")
                        resolution_logged = True
                    self.emit_progress(progress_callback, phase="photo_upload", message="flow context detectado")
                    return dialog
            elif main_has_continue and self._dialog_has_continue(dialog):
                if not continue_reported:
                    self.emit_progress(
                        progress_callback,
                        phase="photo_upload",
                        message="Continuar detectado en page principal.",
                    )
                    continue_reported = True
                    partial_signal_at = monotonic()
            elif not iframe_diagnostics_reported and main_file_inputs == 0 and not main_has_continue:
                self.emit_progress(
                    progress_callback,
                    phase="photo_upload",
                    message=self._iframe_photo_phase_diagnostics(page),
                )
                iframe_diagnostics_reported = True
            if self._has_any_text(page, self._selectors.failure_markers):
                if monotonic() - last_dom_change_at >= 1.2:
                    raise ParipeFlowError(
                        "photo_upload",
                        "Paripe.io mostro un error antes de habilitar la carga de foto.",
                    )
            now = monotonic()
            dom_still_changing = (now - last_dom_change_at) < (self._DOM_STABLE_GRACE_MS / 1000)
            waiting_for_other_signal = (
                partial_signal_at is not None
                and (now - partial_signal_at) < (self._PARTIAL_SIGNAL_GRACE_MS / 1000)
            )
            if now >= minimum_deadline and not dom_still_changing and not waiting_for_other_signal:
                break
            page.wait_for_timeout(self._SHORT_WAIT_MS)
        while monotonic() < hard_deadline:
            dialog = self._find_photo_phase_dialog(page)
            main_file_inputs = self._count_main_page_file_inputs(page)
            main_has_continue = self._page_has_continue(page)
            if main_file_inputs > 0 and main_has_continue and self._dialog_has_file_input(dialog) and self._dialog_has_continue(dialog):
                if not file_reported:
                    self.emit_progress(
                        progress_callback,
                        phase="photo_upload",
                        message=f"Input file detectado en page principal. Total en page: {main_file_inputs}.",
                    )
                if not continue_reported:
                    self.emit_progress(
                        progress_callback,
                        phase="photo_upload",
                        message="Continuar detectado en page principal.",
                    )
                if not resolution_logged:
                    if extension_strict:
                        raise self._build_extension_strict_error(
                            phase="selfie_stage",
                            reason="phase_unknown",
                            state=self._extension_state(session, page, note="wait_photo_phase"),
                        )
                    self._record_engine_resolution(session, None, phase="selfie_stage", source="polling tradicional", note="photo_phase")
                    self.emit_progress(progress_callback, phase="photo_upload", message="selfie_stage detectado por polling tradicional")
                    resolution_logged = True
                self.emit_progress(progress_callback, phase="photo_upload", message="flow context detectado")
                return dialog
            now = monotonic()
            dom_signature = self._dom_signature(page)
            if dom_signature and dom_signature != last_dom_signature:
                last_dom_signature = dom_signature
                last_dom_change_at = now
            dom_still_changing = (now - last_dom_change_at) < (self._DOM_STABLE_GRACE_MS / 1000)
            if not dom_still_changing:
                break
            page.wait_for_timeout(self._SHORT_WAIT_MS)
        if continue_reported or file_reported:
            raise ParipeFlowError(
                "photo_upload",
                (
                    "La fase de carga de foto quedo incompleta: se detectaron señales parciales, "
                    "pero no aparecieron juntos el input file y Continuar."
                ),
            )
        raise ParipeFlowError(
            "photo_upload",
            "No aparecieron el input file y el boton Continuar despues de esperar la transicion real tras la accion inicial.",
        )

    def _find_photo_phase_dialog(self, page: Page) -> Locator | None:
        active_context = self._get_active_flow_context(page)
        if active_context is not None and (
            self._dialog_has_file_input(active_context) or self._dialog_has_continue(active_context)
        ):
            return active_context
        dialogs = page.locator(self._selectors.selfie_dialog)
        try:
            count = dialogs.count()
        except Exception:
            return None
        for index in range(count - 1, -1, -1):
            dialog = dialogs.nth(index)
            try:
                dialog.wait_for(state="visible", timeout=400)
                text = self._normalize_text(dialog.inner_text(timeout=400))
                if self._dialog_has_file_input(dialog) or self._dialog_has_continue(dialog):
                    return dialog
                if "continuar" in text or "foto tipo selfie" in text or "selfie" in text:
                    return dialog
            except Exception:
                pass
        if self._count_main_page_file_inputs(page) > 0 or self._page_has_continue(page):
            return page.locator("body").first
        return None

    def _upload_photo(self, dialog: Locator, reserved_photo: ReservedPhoto, *, timeout_ms: int) -> None:
        file_input = dialog.locator(self._selectors.file_input).first
        file_input.wait_for(state="attached", timeout=timeout_ms)
        file_input.set_input_files(reserved_photo.local_path, timeout=timeout_ms)
        self._wait_for(
            lambda: self._locator_has_files(file_input),
            timeout_ms=timeout_ms,
            phase="photo_upload",
            error_message=(
                "El input file no reflejo la carga local. "
                "Selector fino a revisar: #user_avatar / input[type='file']."
            ),
        )

    def _click_continue(self, dialog: Locator, *, timeout_ms: int) -> None:
        button = self._find_button_by_labels(dialog, self._selectors.continue_texts)
        if button is None:
            raise ParipeFlowError("continue_submit", "No se encontro el boton Continuar con variantes por idioma en paripe.io.")
        button.wait_for(state="visible", timeout=timeout_ms)
        self._click_locator_resilient(
            button,
            phase="continue_submit",
            error_message="No se pudo presionar el boton Continuar en paripe.io.",
        )

    def _complete_selfie_until_block(
        self,
        page: Page,
        *,
        selfie_dialog: Locator,
        progress_callback: ProgressCallback | None,
        action_timeout_ms: int,
        block_wait_ms: int,
        max_selfie_retries: int,
        process_id: str | None = None,
        prepared_photo: BackgroundPhotoPreparation | None = None,
        session=None,
        extension_assisted: bool = False,
        extension_strict: bool = False,
    ) -> tuple[Locator, ReservedPhoto | None, int, bool]:
        deepfakescore_activated = False
        current_dialog = selfie_dialog
        attempt = 1
        while True:
            self._set_active_flow_context(current_dialog, page=page, source="selfie_attempt")
            if extension_assisted:
                extension_state = self._extension_state(session, page, note="dispatch_selfie_loop")
                extension_phase = self._extension_phase(extension_state)
                phase_action = self._extension_phase_action(extension_phase)
                if phase_action in {"loading", "block", "final"}:
                    self._record_engine_resolution(
                        session,
                        extension_state,
                        phase=extension_phase,
                        source="extension",
                        note=f"dispatch:{extension_phase}",
                    )
                    self.emit_progress(
                        progress_callback,
                        phase="processing_after_continue" if phase_action == "loading" else "block_read",
                        message=f"ExtensiÃ³n reporta fase actual {extension_phase}. Se omiten fases anteriores.",
                    )
                    if phase_action == "loading":
                        details_context = self._wait_for_details_dialog(
                            current_dialog,
                            page,
                            progress_callback=progress_callback,
                            timeout_ms=block_wait_ms,
                            continue_clicked_at=None,
                            session=session,
                            extension_assisted=extension_assisted,
                            extension_strict=extension_strict,
                        )
                        return details_context, None, max(attempt - 1, 0), deepfakescore_activated
                    block_context = self._resolve_block_context(current_dialog, page) or current_dialog
                    return block_context, None, max(attempt - 1, 0), deepfakescore_activated
            attempt_label = self._format_retry_attempt_label(attempt, max_selfie_retries)
            self.emit_progress(progress_callback, phase="photo_upload", message=f"Intento {attempt_label} de selfie.")
            if attempt >= 2:
                self.emit_progress(progress_callback, phase="photo_upload", message="Selfie subida mas de una vez. Marca de multiples selfies activada.")
                self.emit_progress(progress_callback, phase="photo_upload", message=f"Reintentando con nueva foto. Intento {attempt_label}.")
            self.emit_progress(progress_callback, phase="photo_upload", message="Modal de selfie detectado. Preparando subida...")
            self._mark_phase_timing("selfie_input_detected", attempt=attempt, url=page.url)
            selfie_input_detected_at = monotonic()
            reserved_photo, photo_ready_before_input = self._await_background_photo(
                prepared_photo,
                progress_callback=progress_callback,
                process_id=process_id,
            )
            prepared_photo = None
            try:
                self.emit_progress(progress_callback, phase="photo_upload", message="Foto reservada y descargada localmente.")
                self.emit_progress(progress_callback, phase="photo_upload", message=f"Foto usada en intento {attempt}: {reserved_photo.original_filename}.")
                self._record_timeline_event(
                    "photo_ready_before_input",
                    attempt=attempt,
                    ready=photo_ready_before_input,
                    photo_id=reserved_photo.photo_id,
                )
                self._mark_phase_timing("photo_upload_started", attempt=attempt, file_name=reserved_photo.original_filename)
                self._record_timeline_event(
                    "selfie_input_to_upload_ms",
                    attempt=attempt,
                    value=int(max(monotonic() - selfie_input_detected_at, 0.0) * 1000),
                )
                self._upload_photo(current_dialog, reserved_photo, timeout_ms=action_timeout_ms)
                self.emit_progress(progress_callback, phase="photo_upload", message="Foto cargada.")
                self._mark_phase_timing("photo_upload_done", attempt=attempt, file_name=reserved_photo.original_filename)
                self._record_timeline_event("photo_uploaded", file_name=reserved_photo.original_filename)
                self.emit_progress(progress_callback, phase="continue_submit", message="Presionando Continuar...")
                self._click_continue(current_dialog, timeout_ms=action_timeout_ms)
                continue_clicked_at = monotonic()
                self._mark_phase_timing("continue_clicked", attempt=attempt, url=page.url)
                self._record_timeline_event("continue_clicked", url=page.url)
                self.emit_progress(progress_callback, phase="continue_submit", message="Continuar presionado.")
                resolution_source = "polling tradicional"
                if extension_assisted:
                    extension_state = self._extension_state(session, page, note="wait_loading_after_continue")
                    extension_phase = self._extension_phase(extension_state)
                    if self._extension_phase_is_at_least(extension_phase, "loading_after_continue") or extension_phase == "return_to_selfie":
                        resolution_source = "extension"
                        self._record_engine_resolution(session, extension_state, phase=extension_phase, source="extension", note="loading_after_continue")
                        self.emit_progress(
                            progress_callback,
                            phase="processing_after_continue",
                            message="espera selfie_stage -> loading_after_continue resuelta por extensión",
                        )
                    elif extension_strict:
                        raise self._build_extension_strict_error(
                            phase="loading_after_continue",
                            reason="phase_unknown" if extension_phase == "unknown" else "phase_mismatch",
                            state=extension_state,
                        )
                if resolution_source == "polling tradicional":
                    self._record_engine_resolution(session, None, phase="loading_after_continue", source="polling tradicional", note="loading_after_continue")
                    self.emit_progress(
                        progress_callback,
                        phase="processing_after_continue",
                        message="espera selfie_stage -> loading_after_continue resuelta por polling tradicional",
                    )
                self.emit_progress(progress_callback, phase="processing_after_continue", message="Esperando validacion de selfie.")
                self.emit_progress(progress_callback, phase="processing_after_continue", message="Esperando aparicion del bloque.")
                self._mark_phase_timing("selfie_validation_started", attempt=attempt, url=page.url)
                self._mark_phase_timing("block_wait_started", attempt=attempt, url=page.url)
                details_context = self._wait_for_details_dialog(
                    current_dialog,
                    page,
                    progress_callback=progress_callback,
                    timeout_ms=block_wait_ms,
                    continue_clicked_at=continue_clicked_at,
                    session=session,
                    extension_assisted=extension_assisted,
                    extension_strict=extension_strict,
                )
                self._set_active_flow_context(details_context, page=page, source="block_detected")
                self._mark_phase_timing("block_detected", attempt=attempt, url=page.url)
                if attempt >= 2:
                    self.emit_progress(progress_callback, phase="block_read", message="Retry exitoso, bloque detectado.")
                    self.emit_progress(progress_callback, phase="block_read", message="Reenganchando al flujo normal desde retry/selfie hacia block_read.")
                else:
                    self.emit_progress(progress_callback, phase="block_read", message="Bloque detectado en primer intento.")
                return details_context, reserved_photo, max(attempt - 1, 0), deepfakescore_activated
            except ParipeFlowError as exc:
                if exc.final_status == "selfie_retry":
                    self._record_timeline_event("return_to_selfie_detected", url=page.url, message=exc.message)
                    self.emit_progress(progress_callback, phase="photo_upload", message="Retorno a selfie detectado.")
                    if not deepfakescore_activated:
                        self.emit_progress(progress_callback, phase="photo_upload", message="deepfakescore activado | reintentos: 1")
                        deepfakescore_activated = True
                    else:
                        self.emit_progress(progress_callback, phase="photo_upload", message=f"deepfakescore activado | reintentos: {attempt}")
                    self.emit_progress(progress_callback, phase="photo_upload", message=exc.message)
                    self.emit_progress(progress_callback, phase="photo_upload", message="Reintentando con nueva foto.")
                    self._finalize_reserved_photo(reserved_photo)
                    reserved_photo = None
                    if self._retry_limit_reached(attempt, max_selfie_retries):
                        self.emit_progress(progress_callback, phase="photo_upload", message="Maximo de intentos de selfie agotado.")
                        raise ParipeFlowError(
                            "photo_upload",
                            "Maximo de reintentos alcanzado tras volver a la pantalla de selfie.",
                            final_status="timeout",
                        )
                    rebound_dialog = self._find_photo_phase_dialog(page)
                    current_dialog = rebound_dialog or current_dialog
                    self._record_timeline_event("return_to_selfie", attempt=attempt, url=page.url)
                    self._set_active_flow_context(current_dialog, page=page, source="return_to_selfie")
                    prepared_photo = self._start_background_photo_preparation(
                        process_id=process_id,
                        progress_callback=progress_callback,
                    )
                    attempt += 1
                    continue
                raise
            except Exception:
                if reserved_photo is not None:
                    self._finalize_reserved_photo(reserved_photo)
                self._discard_background_photo(prepared_photo)
                raise

    def _selfie_phase_visible(self, page: Page, dialog: Locator | None) -> bool:
        if dialog is None:
            return False
        if self._has_strong_block_signal(dialog, page):
            return False
        signals = self._collect_selfie_return_signals(page, dialog)
        structural_signals = (
            signals["file_input"],
            signals["user_avatar"],
            signals["continue_button"],
            signals["selfie_container"] or signals["account_options"],
        )
        structural_ready = sum(1 for enabled in structural_signals if enabled) >= 3
        textual_confirmation = signals["selfie_text"] or signals["account_options"]
        return structural_ready and textual_confirmation

    def _finalize_reserved_photo(self, reserved_photo: ReservedPhoto) -> None:
        self._photo_service.consume_photo(reserved_photo.photo_id)
        self._photo_service.delete_local_copy(reserved_photo.local_path)
    def _fast_mark_block_context_from_button(self, page: Page) -> Locator | None:
        script = """
        ({ finalLabels, continueLabels }) => {
            const normalize = (value) =>
                (value || "")
                    .normalize("NFKD")
                    .replace(/[\\u0300-\\u036f]/g, "")
                    .replace(/\\s+/g, " ")
                    .trim()
                    .toLowerCase();

            const hasAny = (text, tokens) =>
                tokens.some((token) => text.includes(normalize(token)));

            const isVisible = (element) => {
                if (!element) return false;
                const style = window.getComputedStyle(element);
                if (!style || style.display === "none" || style.visibility === "hidden") return false;
                const rect = element.getBoundingClientRect();
                return rect.width >= 2 && rect.height >= 2;
            };

            const textOf = (element) =>
                normalize(
                    element.innerText ||
                    element.value ||
                    element.getAttribute("aria-label") ||
                    element.textContent ||
                    ""
                );

            document
                .querySelectorAll("[data-auto-he-block-context='1']")
                .forEach((node) => node.removeAttribute("data-auto-he-block-context"));

            const buttons = Array.from(
                document.querySelectorAll("button, [role='button'], input[type='button'], input[type='submit'], a")
            ).filter(isVisible);

            const finalButtons = buttons.filter((button) => {
                const text = textOf(button);
                return finalLabels.some((label) => {
                    const normalizedLabel = normalize(label);
                    return text === normalizedLabel || text.includes(normalizedLabel);
                });
            });

            for (const button of finalButtons) {
                let node = button;

                for (let depth = 0; depth < 8 && node && node !== document.body; depth += 1) {
                    const rawText = node.innerText || node.textContent || "";
                    const text = normalize(rawText);

                    const hasPayment = hasAny(text, ["pago", "precio", "price", "valor", "monto"]);
                    const hasStation = hasAny(text, ["estacion", "station", "estacao"]);
                    const hasTime = hasAny(text, [
                        "horario", "hora", "schedule", "time", "fecha", "slot",
                        "duracion", "duration", "horas", "hours"
                    ]);

                    const hasCard =
                        node.querySelectorAll("dt").length > 0 ||
                        (hasPayment && hasStation && hasTime);

                    const hasSelfieInput = Boolean(node.querySelector("input[type='file'], #user_avatar"));

                    const hasContinueButton = Array.from(
                        node.querySelectorAll("button, [role='button'], input[type='button'], input[type='submit'], a")
                    )
                        .filter(isVisible)
                        .some((candidate) => {
                            const candidateText = textOf(candidate);
                            return continueLabels.some((label) => candidateText.includes(normalize(label)));
                        });

                    const looksLikeDashboard = hasAny(text, [
                        "bienvenido",
                        "instant offers",
                        "selfie en ruta",
                        "cuenta prestada",
                        "cuenta propia"
                    ]) && !hasPayment;

                    if (
                        hasPayment &&
                        hasStation &&
                        hasTime &&
                        hasCard &&
                        !hasSelfieInput &&
                        !hasContinueButton &&
                        !looksLikeDashboard
                    ) {
                        node.setAttribute("data-auto-he-block-context", "1");
                        return {
                            found: true,
                            text: rawText.slice(0, 300),
                        };
                    }

                    node = node.parentElement;
                }
            }

            return { found: false };
        }
        """

        payload = {
            "finalLabels": list(self._selectors.final_submit_texts),
            "continueLabels": list(self._selectors.continue_texts),
        }

        for frame_index, frame in enumerate(page.frames):
            try:
                result = frame.evaluate(script, payload)
            except Exception:
                continue

            if isinstance(result, dict) and result.get("found"):
                self._record_timeline_event(
                    "fast_block_context_found",
                    frame_index=frame_index,
                    frame_url=getattr(frame, "url", ""),
                    text_preview=str(result.get("text", ""))[:300],
                )
                return frame.locator("[data-auto-he-block-context='1']").last

        return None
    def _wait_for_details_dialog(
        self,
        flow_context: Locator,
        page: Page,
        *,
        progress_callback: ProgressCallback | None,
        timeout_ms: int,
        continue_clicked_at: float | None,
        session=None,
        extension_assisted: bool = False,
        extension_strict: bool = False,
    ) -> Locator:
        method_started_at = monotonic()
        grace_seconds = 0.8
        deadline = monotonic() + (timeout_ms / 1000)
        self._set_active_flow_context(flow_context, page=page, source="wait_for_details_dialog_start")
        waiting_reported = False
        poll_iteration = 0
        extension_block_hint = False
        extension_return_hint = False
        extension_state = None
        fallback_reason = "phase_unknown"
        first_block_signal_at: float | None = None
        first_block_confirmed_at: float | None = None
        last_timing_log_at = 0.0
        last_poll_signature = ""
        last_discard_signature = ""
        grace_reported = False
        loading_reported = False
        self.emit_progress(
            progress_callback,
            phase="processing_after_continue",
            message=f"timing block wait started: timeout={timeout_ms}ms",
        )
        while monotonic() < deadline:
            poll_iteration += 1
            poll_started_at = monotonic()
            extension_phase = "unknown"
            if extension_assisted:
                extension_state = self._extension_state(session, page, note="wait_block_read_ready")
                extension_phase = self._extension_phase(extension_state)
                if self._extension_phase_is_at_least(extension_phase, "block_read_ready"):
                    extension_block_hint = True
                    fallback_reason = f"phase_{extension_phase}"
                    self.emit_progress(
                        progress_callback,
                        phase="processing_after_continue",
                        message="ExtensiÃ³n detectÃ³ block_read_ready. Se usa como fuente primaria.",
                    )
                elif extension_phase == "return_to_selfie":
                    extension_return_hint = True
                    fallback_reason = "phase_return_to_selfie"
                elif extension_phase != "unknown":
                    fallback_reason = f"phase_{extension_phase}"
            if extension_assisted and extension_phase == "unknown":
                extension_resolution = ExtensionFlowEngine.resolve_block_read_ready(
                    session=session,
                    page=page,
                    note="wait_block_read_ready",
                )
                extension_state = extension_resolution.state
                if extension_resolution.resolved:
                    extension_block_hint = True
                    self.emit_progress(
                        progress_callback,
                        phase="processing_after_continue",
                        message="Extensión detectó block_read_ready. Se usa como fuente primaria.",
                    )
                else:
                    fallback_reason = extension_resolution.reason
                    extension_resolution = ExtensionFlowEngine.resolve_return_to_selfie(
                        session=session,
                        page=page,
                        note="wait_return_to_selfie",
                    )
                    extension_state = extension_resolution.state
                    if extension_resolution.resolved:
                        extension_return_hint = True
                    else:
                        fallback_reason = extension_resolution.reason
            if not waiting_reported:
                self.emit_progress(
                    progress_callback,
                    phase="processing_after_continue",
                    message="Esperando aparicion del bloque...",
                )
                self.emit_progress(
                    progress_callback,
                    phase="processing_after_continue",
                    message="leyendo solo contexto activo del flujo",
                )
                waiting_reported = True
            snapshot_context = self._get_active_flow_context(page) or flow_context
            fast_snapshot = self._fast_context_snapshot(snapshot_context)
            grace_active = continue_clicked_at is not None and (monotonic() - continue_clicked_at) < grace_seconds
            snapshot_selfie_active = bool(
                fast_snapshot.get("hasSelfieInput", False)
                or fast_snapshot.get("hasSelfieText", False)
                or fast_snapshot.get("hasContinueButton", False)
            )
            snapshot_processing_active = bool(fast_snapshot.get("hasProcessingText", False))
            if grace_active and not grace_reported:
                grace_reported = True
                self.emit_progress(
                    progress_callback,
                    phase="processing_after_continue",
                    message="post-continue grace: esperando procesamiento de selfie",
                )
            if snapshot_processing_active and not loading_reported:
                loading_reported = True
                self._record_timeline_event("loading_detected", url=page.url)
                self.emit_progress(
                    progress_callback,
                    phase="processing_after_continue",
                    message="loading detectado tras Continuar",
                )
            if fast_snapshot.get("hasSelfieInput", False) and fast_snapshot.get("hasContinueButton", False):
                self._record_timeline_event("return_to_selfie_detected", url=page.url, source="wait_for_details_dialog")
                self.emit_progress(
                    progress_callback,
                    phase="photo_upload",
                    message="selfie rechazada: return_to_selfie detectado",
                )
                raise ParipeFlowError(
                    "photo_upload",
                    "Retorno a selfie detectado tras la validacion. El flujo volvio a mostrar input file y Continuar.",
                    final_status="selfie_retry",
                )
            fast_block_signal_count = sum(
                1
                for enabled in (
                    fast_snapshot.get("hasPaymentText", False),
                    fast_snapshot.get("hasStationText", False),
                    fast_snapshot.get("hasScheduleText", False),
                    fast_snapshot.get("hasDurationText", False),
                    fast_snapshot.get("hasBlockCardLike", False),
                )
                if enabled
            )
            if grace_active:
                page.wait_for_timeout(self._BLOCK_WAIT_POLL_MS)
                continue

            snapshot_context = self._fast_mark_block_context_from_button(page)
            if snapshot_context is not None:
                final_button = self._find_button_by_labels(
                    snapshot_context,
                    self._selectors.final_submit_texts,
                )
                if final_button is not None and self._try_fast_click_final_from_block_candidate(
                    page,
                    snapshot_context,
                    final_button,
                    progress_callback,
                    source="wait_for_details_dialog_fast_iframe_click",
                ):
                    return snapshot_context

                self._mark_phase_timing("block_visual_detected", source="fast_button_context", url=page.url)
                self._latest_block_snapshot_text = self._capture_block_snapshot_text(snapshot_context, page)
                self._set_active_flow_context(snapshot_context, page=page, source="fast_button_context")
                self.emit_progress(
                    progress_callback,
                    phase="block_read",
                    message="bloque detectado por boton final dentro de iframe/contexto real",
                )
                return snapshot_context
            
            resolve_context_started_at = monotonic()
            current_context = self._resolve_current_flow_dialog(page, flow_context)
            self._set_active_flow_context(current_context, page=page, source="wait_for_details_dialog_poll")
            resolve_context_elapsed_ms = int((monotonic() - resolve_context_started_at) * 1000)
            resolve_block_started_at = monotonic()
            block_context = self._resolve_block_context(current_context, page) or current_context
            resolve_block_elapsed_ms = int((monotonic() - resolve_block_started_at) * 1000)
            # Fast-path seguro: solo avanzamos si el bloque ya muestra el boton
            # final y texto real del bloque en el mismo contexto visible.
            if self._count_final_submit_buttons(block_context) > 0:
                normalized_text = self._safe_normalized_text(block_context)
                if any(
                    token in normalized_text
                    for token in ("pago", "precio", "estacion", "station", "duracion", "duration", "horario", "schedule")
                ) and not snapshot_selfie_active and not snapshot_processing_active:
                    final_button = self._find_final_submit_button(block_context, page=page)
                    if final_button is not None and self._try_fast_click_final_from_block_candidate(
                        page,
                        block_context,
                        final_button,
                        progress_callback,
                        source="wait_for_details_dialog_fast_iframe_click",
                    ):
                        return block_context
            collect_block_started_at = monotonic()
            block_signals = self._collect_block_signals(block_context, page)
            collect_block_elapsed_ms = int((monotonic() - collect_block_started_at) * 1000)
            collect_selfie_started_at = monotonic()
            selfie_signals = self._collect_selfie_return_signals(page, current_context)
            collect_selfie_elapsed_ms = int((monotonic() - collect_selfie_started_at) * 1000)
            collect_processing_started_at = monotonic()
            processing_signals = self._collect_processing_signals(page, current_context)
            collect_processing_elapsed_ms = int((monotonic() - collect_processing_started_at) * 1000)
            diagnostics = self._selfie_signal_diagnostics(page, current_context)
            selfie_active = any(
                selfie_signals.get(name, False)
                for name in ("file_input", "user_avatar", "continue_button", "selfie_text", "account_options")
            )
            processing_active = any(processing_signals.values())
            if any(block_signals.values()) and first_block_signal_at is None:
                first_block_signal_at = monotonic()
                self.emit_progress(
                    progress_callback,
                    phase="processing_after_continue",
                    message=f"block signals detected after {int((first_block_signal_at - method_started_at) * 1000)} ms",
                )
            if self._count_final_submit_buttons(block_context) > 0:
                strong_block_signal_count = sum(
                    1
                    for name in ("price_or_payment", "station", "schedule", "duration", "block_card")
                    if block_signals.get(name, False)
                )

                if strong_block_signal_count >= 3 and not selfie_active and not processing_active:
                    final_button = self._find_final_submit_button(block_context, page=page)
                    if final_button is not None and self._try_fast_click_final_from_block_candidate(
                        page,
                        block_context,
                        final_button,
                        progress_callback,
                        source="wait_for_details_dialog_fast_iframe_click",
                    ):
                        return block_context
                    self._mark_phase_timing("block_visual_detected", source="wait_for_details_dialog_poll", url=page.url)
                    self._latest_block_snapshot_text = self._capture_block_snapshot_text(block_context, page)
                    return block_context
            
            if extension_block_hint:
                self._record_engine_resolution(
                    session,
                    extension_state,
                    phase="block_read_ready",
                    source="extension",
                    note="block_read:phase_match",
                )
                self.emit_progress(
                    progress_callback,
                    phase="block_read",
                    message="espera de bloque resuelta por extensión",
                )
                return block_context
            if extension_return_hint:
                structural_sources = [
                    name
                    for name in ("file_input", "user_avatar", "continue_button", "selfie_container", "account_options")
                    if selfie_signals.get(name, False)
                ]
                textual_sources = [
                    name
                    for name in ("selfie_text", "account_options")
                    if selfie_signals.get(name, False)
                ]
                self._record_engine_resolution(
                    session,
                    extension_state,
                    phase="return_to_selfie",
                    source="extension",
                    note="selfie_retry:phase_match",
                )
                self.emit_progress(
                    progress_callback,
                    phase="photo_upload",
                    message="return_to_selfie resuelto por extensión",
                )
                raise ParipeFlowError(
                    "photo_upload",
                    (
                        "Retorno a selfie detectado. "
                        f"user_avatar={'si' if selfie_signals['user_avatar'] else 'no'}, "
                        f"Continuar={'si' if selfie_signals['continue_button'] else 'no'}, "
                        f"texto_selfie={'si' if selfie_signals['selfie_text'] else 'no'}, "
                        "sin senales de bloque activas. "
                        f"Senales: {self._format_active_signals(selfie_signals)}. "
                        f"Activadores deepfakescore estructurales: {', '.join(structural_sources) if structural_sources else 'ninguno'}. "
                        f"textuales: {', '.join(textual_sources) if textual_sources else 'ninguno'}."
                    ),
                    final_status="selfie_retry",
                )
            evaluate_block_started_at = monotonic()
            block_evaluation = self._evaluate_block_candidate(
                block_context,
                page,
                current_context=current_context,
                block_signals=block_signals,
                selfie_signals=selfie_signals,
                processing_signals=processing_signals,
            )
            evaluate_block_elapsed_ms = int((monotonic() - evaluate_block_started_at) * 1000)
            poll_elapsed_ms = int((monotonic() - poll_started_at) * 1000)
            discard_signature = "|".join(block_evaluation["discarded_reasons"])
            poll_signature = "|".join(
                (
                    self._format_active_signals(block_signals),
                    self._format_active_signals(selfie_signals),
                    self._format_active_signals(processing_signals),
                    discard_signature or "confirmed",
                )
            )
            should_log_timing = (monotonic() - last_timing_log_at) >= 0.35 or poll_signature != last_poll_signature
            if should_log_timing:
                last_timing_log_at = monotonic()
                last_poll_signature = poll_signature
                self.emit_progress(
                    progress_callback,
                    phase="processing_after_continue",
                    message=(
                        "timing block poll: "
                        f"poll={poll_iteration}, elapsed={poll_elapsed_ms}ms, "
                        f"resolve_context={resolve_context_elapsed_ms}ms, "
                        f"block_context={resolve_block_elapsed_ms}ms, "
                        f"signals={collect_block_elapsed_ms + collect_selfie_elapsed_ms + collect_processing_elapsed_ms}ms, "
                        f"block_signals={collect_block_elapsed_ms}ms, "
                        f"selfie_signals={collect_selfie_elapsed_ms}ms, "
                        f"processing_signals={collect_processing_elapsed_ms}ms, "
                        f"evaluation={evaluate_block_elapsed_ms}ms"
                    ),
                )
                self.emit_progress(
                    progress_callback,
                    phase="processing_after_continue",
                    message=(
                        f"Revisando iframe / contexto actual. Poll {poll_iteration}. "
                        f"Contexto: {self._describe_live_dialog(current_context)}. "
                        f"fuente={'body' if self._looks_like_body_context(current_context) else 'iframe/dialog'}. "
                        f"input[type=file]={diagnostics['file_inputs']}. "
                        f"user_avatar={'si' if diagnostics['user_avatar'] else 'no'}. "
                        f"Continuar={diagnostics['continue_buttons']}. "
                        f"texto_selfie={'si' if selfie_signals['selfie_text'] else 'no'}. "
                        f"loading={self._format_active_signals(processing_signals)}. "
                        f"senales_bloque={self._format_active_signals(block_signals)}."
                    ),
                )
            if block_evaluation["discarded_reasons"] and discard_signature != last_discard_signature:
                last_discard_signature = discard_signature
                self.emit_progress(
                    progress_callback,
                    phase="processing_after_continue",
                    message=f"block candidate discarded: {', '.join(block_evaluation['discarded_reasons'])}",
                )
            if block_evaluation["confirmed"] and first_block_confirmed_at is None:
                first_block_confirmed_at = monotonic()
                self.emit_progress(
                    progress_callback,
                    phase="block_read",
                    message=f"block confirmed after {int((first_block_confirmed_at - method_started_at) * 1000)} ms",
                )
            if block_context is not current_context and block_evaluation["confirmed"]:
                self.emit_progress(
                    progress_callback,
                    phase="block_read",
                    message="Bloque detectado en contexto nuevo tras el retry. Se prioriza block_read normal.",
                )
            if block_evaluation["confirmed"]:
                if extension_strict:
                    raise self._build_extension_strict_error(
                        phase="block_read_ready",
                        reason=fallback_reason,
                        state=extension_state,
                        extra={"blockPayloadMissing": True},
                    )
                self._record_engine_resolution(
                    session,
                    None,
                    phase="block_read_ready",
                    source="extension_fallback_polling",
                    note=f"block_read:{fallback_reason}",
                )
                self.emit_progress(
                    progress_callback,
                    phase="block_read",
                    message="block_read resuelto por fallback tradicional",
                )
                self._mark_phase_timing("block_visual_detected", source="wait_for_details_dialog_poll", url=page.url)
                if block_evaluation["residual_reasons"]:
                    self.emit_progress(
                        progress_callback,
                        phase="block_read",
                        message=(
                            "Senales de selfie/loading residuales detectadas, pero bloque real confirmado: "
                            f"{'; '.join(block_evaluation['residual_reasons'])}."
                        ),
                    )
                self.emit_progress(
                    progress_callback,
                    phase="block_read",
                    message=(
                        "Bloque detectado. "
                        f"Senales confirmadas: {', '.join(block_evaluation['trigger_reasons'])}."
                    ),
                )
                return block_context
            if self._selfie_phase_visible(page, current_context):
                if extension_strict:
                    raise self._build_extension_strict_error(
                        phase="return_to_selfie",
                        reason=fallback_reason,
                        state=extension_state,
                    )
                structural_sources = [
                    name
                    for name in ("file_input", "user_avatar", "continue_button", "selfie_container", "account_options")
                    if selfie_signals.get(name, False)
                ]
                textual_sources = [
                    name
                    for name in ("selfie_text", "account_options")
                    if selfie_signals.get(name, False)
                ]
                self._record_engine_resolution(
                    session,
                    None,
                    phase="return_to_selfie",
                    source="extension_fallback_polling",
                    note=f"selfie_retry:{fallback_reason}",
                )
                raise ParipeFlowError(
                    "photo_upload",
                    (
                        "Retorno a selfie detectado. "
                        f"user_avatar={'si' if selfie_signals['user_avatar'] else 'no'}, "
                        f"Continuar={'si' if selfie_signals['continue_button'] else 'no'}, "
                        f"texto_selfie={'si' if selfie_signals['selfie_text'] else 'no'}, "
                        "sin senales de bloque activas. "
                        f"Senales: {self._format_active_signals(selfie_signals)}. "
                        f"Activadores deepfakescore estructurales: {', '.join(structural_sources) if structural_sources else 'ninguno'}. "
                        f"textuales: {', '.join(textual_sources) if textual_sources else 'ninguno'}."
                    ),
                    final_status="selfie_retry",
                )
            body_text = self._safe_normalized_text(page.locator("body").first)
            no_block_message = self._detect_no_block_message(body_text)
            if no_block_message is not None:
                raise ParipeFlowError("block_read", no_block_message, final_status="no_block")
            if any(processing_signals.values()):
                # Si ya existe botón final o datos de bloque, no seguir esperando solo por texto residual de loading.
                if self._count_final_submit_buttons(block_context) > 0 or any(block_signals.values()):
                    pass
                else:
                    page.wait_for_timeout(self._BLOCK_WAIT_POLL_MS)
                    continue
            page.wait_for_timeout(self._BLOCK_WAIT_POLL_MS)
            continue
            if self._has_any_text(page, self._selectors.failure_markers):
                raise ParipeFlowError(
                    "block_read",
                    "Paripe.io devolvio un error antes de mostrar la informacion del bloque.",
                )
            page.wait_for_timeout(self._SHORT_WAIT_MS)
        raise ParipeFlowError(
            "block_read",
            "No aparecio la informacion del bloque despues de Continuar dentro del mismo contexto del flujo. Ultimo paso exitoso: continue_submit.",
            final_status="timeout",
        )

    def _resolve_current_flow_dialog(self, page: Page, previous_context: Locator) -> Locator:
        candidates: list[Locator] = []
        active_context = self._get_active_flow_context(page)
        if active_context is not None:
            candidates.append(active_context)
        if self._locator_is_live(previous_context) and not self._looks_like_body_context(previous_context):
            candidates.append(previous_context)
        dialog = self._find_photo_phase_dialog(page)
        if dialog is not None:
            candidates.append(dialog)
        dialogs = page.locator(self._selectors.details_dialog)
        try:
            count = dialogs.count()
        except Exception:
            count = 0
        for index in range(count):
            candidate = dialogs.nth(index)
            if self._locator_is_live(candidate):
                candidates.append(candidate)
        if not candidates:
            candidates.append(page.locator("body").first)
        best_context = previous_context
        best_score = -1
        for candidate in candidates:
            score = self._score_live_dialog(candidate)
            if score > best_score:
                best_score = score
                best_context = candidate
        if best_context is not None and not self._looks_like_body_context(best_context):
            self._active_flow_context = best_context
        return best_context

    def _score_live_dialog(self, dialog: Locator) -> int:
        score = 0
        selfie_signals = self._collect_selfie_return_signals_from_dialog(dialog)
        block_signals = self._collect_block_signals_from_dialog(dialog)
        score += sum(2 for enabled in selfie_signals.values() if enabled)
        score += sum(2 for enabled in block_signals.values() if enabled)
        text = self._safe_normalized_text(dialog)
        if self._detect_no_block_message(text) is not None:
            score += 2
        if self._looks_like_body_context(dialog):
            score -= 6
        elif selfie_signals["selfie_container"] or block_signals["block_card"] or block_signals["final_button"]:
            score += 6
        return score

    def _score_block_context(self, dialog: Locator) -> int:
        signals = self._collect_block_signals_from_dialog(dialog)
        score = 0
        for key, weight in (
            ("price_or_payment", 8),
            ("station", 8),
            ("duration", 7),
            ("schedule", 4),
            ("block_card", 7),
            ("final_button", 9),
        ):
            if signals.get(key, False):
                score += weight
        if not self._looks_like_body_context(dialog):
            score += 4
        return score

    def _locator_is_live(self, locator: Locator) -> bool:
        try:
            locator.wait_for(state="attached", timeout=100)
            return True
        except Exception:
            return False

    def _locator_is_clickable_candidate(self, locator: Locator) -> bool:
        try:
            if not locator.is_visible():
                return False
            box = locator.bounding_box()
        except Exception:
            return False
        if box is None:
            return False
        return float(box.get("width") or 0) >= 2 and float(box.get("height") or 0) >= 2

    def _click_locator_resilient(self, locator: Locator, *, phase: str, error_message: str) -> None:
        try:
            locator.wait_for(state="visible", timeout=1_000)
            locator.scroll_into_view_if_needed(timeout=1_000)
        except Exception:
            pass
        try:
            locator.click(timeout=2_000)
            return
        except Exception:
            pass
        try:
            locator.click(timeout=2_000, force=True)
            return
        except Exception:
            pass
        try:
            locator.press("Space")
            return
        except Exception:
            pass
        try:
            locator.press("Enter")
            return
        except Exception as exc:
            raise ParipeFlowError(phase, error_message) from exc

    def _describe_live_dialog(self, dialog: Locator) -> str:
        try:
            tag_name = dialog.evaluate("node => node.tagName.toLowerCase()")
        except Exception:
            tag_name = "desconocido"
        return tag_name

    def _looks_like_body_context(self, dialog: Locator) -> bool:
        try:
            return dialog.evaluate("node => node.tagName.toLowerCase() === 'body'")
        except Exception:
            return False

    def _collect_selfie_return_signals(self, page: Page, dialog: Locator | None) -> dict[str, bool]:
        if dialog is None:
            return {
                "file_input": self._count_main_page_file_inputs(page) > 0,
                "user_avatar": page.locator("#user_avatar").count() > 0,
                "continue_button": self._page_has_continue(page),
                "selfie_text": self._normalized_contains_any(
                    self._safe_normalized_text(page.locator("body").first),
                    self._selectors.selfie_instruction_texts,
                ),
                "account_options": self._normalized_contains_any(
                    self._safe_normalized_text(page.locator("body").first),
                    self._selectors.selfie_option_texts,
                ),
                "selfie_container": False,
            }
        dialog_text = self._safe_normalized_text(dialog) if dialog is not None else ""
        body_text = ""
        if dialog is None or self._looks_like_body_context(dialog):
            body_text = self._safe_normalized_text(page.locator("body").first)
        combined_text = f"{dialog_text} {body_text}".strip()
        user_avatar_in_dialog = False
        if dialog is not None:
            try:
                user_avatar_in_dialog = dialog.locator("#user_avatar").count() > 0
            except Exception:
                user_avatar_in_dialog = False
        return {
            "file_input": self._count_main_page_file_inputs(page) > 0 or self._dialog_has_file_input(dialog),
            "user_avatar": page.locator("#user_avatar").count() > 0 or user_avatar_in_dialog,
            "continue_button": self._page_has_continue(page) or self._dialog_has_continue(dialog),
            "selfie_text": self._normalized_contains_any(combined_text, self._selectors.selfie_instruction_texts),
            "account_options": self._normalized_contains_any(combined_text, self._selectors.selfie_option_texts),
            "selfie_container": dialog is not None,
        }

    def _collect_selfie_return_signals_from_dialog(self, dialog: Locator) -> dict[str, bool]:
        text = self._safe_normalized_text(dialog)
        return {
            "file_input": self._dialog_has_file_input(dialog),
            "user_avatar": self._count_locator(dialog, ("#user_avatar",)) > 0,
            "continue_button": self._dialog_has_continue(dialog),
            "selfie_text": self._normalized_contains_any(text, self._selectors.selfie_instruction_texts),
            "account_options": self._normalized_contains_any(text, self._selectors.selfie_option_texts),
            "selfie_container": True,
        }

    def _collect_block_signals(self, flow_context: Locator, page: Page) -> dict[str, bool]:
        candidate = self._resolve_block_context(flow_context, page) or flow_context
        text = self._safe_normalized_text(candidate)
        return {
            "price_or_payment": any(token in text for token in ("pago", "precio", "price", "valor", "monto")),
            "station": any(token in text for token in ("estacion", "station", "estacao")),
            "schedule": any(token in text for token in ("horario", "hora", "schedule", "time", "fecha", "slot")),
            "duration": any(token in text for token in ("duracion", "duration", "horas", "hours")),
            "block_card": self._count_definition_terms(candidate) > 0,
            "final_button": self._count_final_submit_buttons(candidate) > 0,
        }

    def _collect_processing_signals(self, page: Page, dialog: Locator | None) -> dict[str, bool]:
        dialog_text = self._safe_normalized_text(dialog) if dialog is not None else ""
        body_text = ""
        if dialog is None or self._looks_like_body_context(dialog):
            body_text = self._safe_normalized_text(page.locator("body").first)
        combined_text = f"{dialog_text} {body_text}".strip()
        has_processing_ui = False
        roots = (dialog,) if dialog is not None and not self._looks_like_body_context(dialog) else (dialog, page.locator("body").first)
        for root in roots:
            if root is None:
                continue
            if self._has_any_selector(root, self._selectors.processing_selectors):
                has_processing_ui = True
                break
        return {
            "processing_text": any(token in combined_text for token in self._selectors.processing_texts),
            "processing_ui": has_processing_ui,
        }

    def _evaluate_block_candidate(
        self,
        flow_context: Locator,
        page: Page,
        *,
        current_context: Locator | None = None,
        block_signals: dict[str, bool] | None = None,
        selfie_signals: dict[str, bool] | None = None,
        processing_signals: dict[str, bool] | None = None,
    ) -> dict[str, object]:
        candidate = self._resolve_block_context(flow_context, page) or flow_context
        signals = block_signals or self._collect_block_signals(candidate, page)
        selfie = selfie_signals or self._collect_selfie_return_signals(page, current_context or candidate)
        processing = processing_signals or self._collect_processing_signals(page, current_context or candidate)
        has_price = signals.get("price_or_payment", False)
        has_station = signals.get("station", False)
        has_time_detail = signals.get("duration", False) or signals.get("schedule", False)
        has_structured_container = signals.get("block_card", False)
        trigger_reasons: list[str] = []
        discarded_reasons: list[str] = []
        residual_reasons: list[str] = []
        selfie_active = any(
            selfie.get(name, False)
            for name in ("file_input", "user_avatar", "continue_button", "selfie_text", "account_options")
        )
        processing_active = any(processing.values())
        if not has_price:
            discarded_reasons.append("faltaba pago/precio real")
        else:
            trigger_reasons.append("pago/precio")
        if not has_station:
            discarded_reasons.append("faltaba estacion real")
        else:
            trigger_reasons.append("estacion")
        if not has_time_detail:
            discarded_reasons.append("faltaba horario/duracion real")
        else:
            trigger_reasons.append("horario/duracion")
        if not has_structured_container:
            discarded_reasons.append("faltaba contenedor estructurado del bloque")
        else:
            trigger_reasons.append("contenedor/tarjeta del bloque")
        confirmed = not discarded_reasons
        if selfie_active:
            selfie_reason = "el flujo seguia mostrando selfie/retorno a selfie: " + self._format_active_signals(selfie)
            if confirmed:
                residual_reasons.append(selfie_reason)
            else:
                discarded_reasons.append(selfie_reason)
        if processing_active:
            processing_reason = "el flujo seguia en validacion/carga: " + self._format_active_signals(processing)
            if confirmed:
                residual_reasons.append(processing_reason)
            else:
                discarded_reasons.append(processing_reason)
        return {
            "candidate": candidate,
            "confirmed": confirmed,
            "trigger_reasons": trigger_reasons,
            "discarded_reasons": discarded_reasons,
            "residual_reasons": residual_reasons,
            "block_signals": signals,
            "selfie_signals": selfie,
            "processing_signals": processing,
        }

    def _has_strong_block_signal(self, flow_context: Locator, page: Page) -> bool:
        evaluation = self._evaluate_block_candidate(flow_context, page)
        return bool(evaluation["confirmed"])

    def _collect_block_signals_from_dialog(self, dialog: Locator) -> dict[str, bool]:
        text = self._safe_normalized_text(dialog)
        return {
            "price_or_payment": any(token in text for token in ("pago", "precio", "price", "valor", "monto")),
            "station": any(token in text for token in ("estacion", "station", "estacao")),
            "schedule": any(token in text for token in ("horario", "hora", "schedule", "time", "fecha", "slot")),
            "duration": any(token in text for token in ("duracion", "duration", "horas", "hours")),
            "block_card": self._count_definition_terms(dialog) > 0,
            "final_button": self._count_final_submit_buttons(dialog) > 0,
        }

    def _selfie_signal_diagnostics(self, page: Page, dialog: Locator | None) -> dict[str, int | bool]:
        return {
            "file_inputs": self._count_main_page_file_inputs(page) + (self._count_locator(dialog, ("input[type='file']", "#user_avatar")) if dialog is not None else 0),
            "user_avatar": page.locator("#user_avatar").count() > 0 or (self._count_locator(dialog, ("#user_avatar",)) > 0 if dialog is not None else False),
            "continue_buttons": self._count_continue_buttons(page) + (self._count_continue_buttons(dialog) if dialog is not None else 0),
        }

    def _count_locator(self, locator: Locator | None, selectors: tuple[str, ...]) -> int:
        if locator is None:
            return 0
        total = 0
        for selector in selectors:
            try:
                total += locator.locator(selector).count()
            except Exception:
                continue
        return total

    def _has_any_selector(self, locator: Locator | None, selectors: tuple[str, ...]) -> bool:
        return self._count_locator(locator, selectors) > 0

    def _count_continue_buttons(self, root: Page | Locator) -> int:
        locator = root.locator("body").first if isinstance(root, Page) else root
        return 1 if self._find_button_by_labels(locator, self._selectors.continue_texts) is not None else 0

    @staticmethod
    def _retry_limit_reached(attempt: int, max_selfie_retries: int) -> bool:
        return max_selfie_retries > 0 and attempt >= max_selfie_retries

    @staticmethod
    def _format_retry_attempt_label(attempt: int, max_selfie_retries: int) -> str:
        if max_selfie_retries > 0:
            return f"{attempt} de {max_selfie_retries}"
        return f"{attempt} (sin limite)"

    @staticmethod
    def _format_active_signals(signals: dict[str, bool]) -> str:
        active = [name for name, enabled in signals.items() if enabled]
        return ", ".join(active) if active else "sin senales activas"

    def _has_any_text(self, page: Page, texts: tuple[str, ...]) -> bool:
        try:
            body_text = self._normalize_text(page.locator("body").inner_text(timeout=400))
        except Exception:
            return False
        return any(self._normalize_text(text) in body_text for text in texts)

    def _normalized_contains_any(self, normalized_text: str, texts: tuple[str, ...]) -> bool:
        return any(self._normalize_text(text) in normalized_text for text in texts)

    def _first_visible(self, page: Page, selectors: tuple[str, ...], *, timeout_ms: int) -> Locator:
        for selector in selectors:
            locator = page.locator(selector).first
            try:
                locator.wait_for(state="visible", timeout=timeout_ms)
                return locator
            except Exception:
                continue
        raise ParipeFlowError("login", f"No se encontro un selector valido de Paripe para: {selectors[0]}.")

    def _fill_first(self, page: Page, selectors: tuple[str, ...], value: str) -> None:
        locator = self._first_visible(page, selectors, timeout_ms=2_500)
        try:
            locator.click(timeout=2_000)
            locator.fill(value, timeout=3_000)
            return
        except Exception:
            locator.evaluate(
                """(node, value) => {
                    node.focus();
                    node.value = value;
                    node.dispatchEvent(new Event('input', { bubbles: true }));
                    node.dispatchEvent(new Event('change', { bubbles: true }));
                }""",
                value,
            )
    def _wait_for(
        self,
        predicate,
        *,
        timeout_ms: int,
        phase: str,
        error_message: str,
    ) -> None:
        deadline = monotonic() + (timeout_ms / 1000)
        while monotonic() < deadline:
            if predicate():
                return
            sleep(self._SHORT_WAIT_MS / 1000)
        raise ParipeFlowError(phase, error_message)

    @staticmethod
    def _locator_has_files(locator: Locator) -> bool:
        try:
            return bool(locator.evaluate("node => Boolean(node.files && node.files.length > 0)"))
        except Exception:
            return False

    def _dialog_has_file_input(self, dialog: Locator | None) -> bool:
        if dialog is None:
            return False
        try:
            return dialog.locator(self._selectors.file_input).count() > 0
        except Exception:
            return False

    def _dialog_has_continue(self, dialog: Locator | None) -> bool:
        if dialog is None:
            return False
        return self._find_button_by_labels(dialog, self._selectors.continue_texts) is not None

    def _count_main_page_file_inputs(self, page: Page) -> int:
        try:
            return page.locator(self._selectors.file_input).count()
        except Exception:
            return 0

    def _page_has_continue(self, page: Page) -> bool:
        return self._find_button_by_labels(page.locator("body").first, self._selectors.continue_texts) is not None

    def _iframe_photo_phase_diagnostics(self, page: Page) -> str:
        parts: list[str] = []
        for index, frame in enumerate(page.frames[1:], start=1):
            try:
                frame_url = (frame.url or "").strip() or "-"
            except Exception:
                frame_url = "-"
            try:
                file_inputs = frame.locator(self._selectors.file_input).count()
            except Exception:
                file_inputs = 0
            try:
                has_continue = self._find_button_by_labels(frame.locator("body").first, self._selectors.continue_texts) is not None
            except Exception:
                has_continue = False
            parts.append(
                f"iframe[{index}] url={frame_url} input[type=file]={file_inputs} continuar={'si' if has_continue else 'no'}"
            )
        if not parts:
            return "Sin iframes adicionales relevantes. La busqueda del input file sigue priorizando el DOM principal."
        return (
            "Sin señales en page principal por ahora. Diagnostico de iframes: "
            + " | ".join(parts[:4])
        )

    def _read_block_details(
        self,
        dialog: Locator,
        *,
        page: Page,
        progress_callback: ProgressCallback | None = None,
    ) -> tuple[str, str, str, str]:
        started_at = monotonic()
        self.emit_progress(progress_callback, phase="block_read", message="block_read timing started")
        full_text = self._safe_text(dialog)
        pairs = self._extract_block_pairs(dialog, full_text=full_text)
        payment = self._pick_detail_value(pairs, ("pago", "precio", "price", "valor", "monto"))
        station = self._pick_detail_value(pairs, ("estacion", "station", "estacao"))
        schedule = self._read_schedule(dialog, page=page, pairs=pairs, full_text=full_text)
        duration = self._read_duration(pairs, full_text=full_text)
        if payment == "N/A" and station == "N/A" and duration == "N/A" and schedule == "N/A":
            raise ParipeFlowError(
                "block_read",
                "Aparecio el bloque, pero no se pudieron leer sus detalles por estructura.",
            )
        missing_fields = [
            label
            for label, value in (
                ("pago", payment),
                ("estacion", station),
                ("horario", schedule),
                ("duracion", duration),
            )
            if value == "N/A"
        ]
        if len(missing_fields) >= 3:
            raise ParipeFlowError(
                "block_read",
                "Aparecio el bloque, pero la lectura quedo demasiado incompleta. "
                f"Campos faltantes: {', '.join(missing_fields)}.",
            )
        self.emit_progress(
            progress_callback,
            phase="block_read",
            message=f"block_read details parsed after {int((monotonic() - started_at) * 1000)} ms",
        )
        return payment, station, schedule, duration

    def _read_schedule(
        self,
        dialog: Locator,
        *,
        page: Page,
        pairs: dict[str, str] | None = None,
        full_text: str | None = None,
    ) -> str:
        extracted_pairs = pairs or self._extract_block_pairs(dialog, full_text=full_text)
        time_range = self._extract_time_range(full_text or self._safe_text(dialog))
        if time_range is not None:
            return time_range
        from_pairs = self._pick_detail_value(
            extracted_pairs,
            ("horario", "fecha", "schedule", "hora", "turno", "slot"),
        )
        if from_pairs != "N/A" and self._looks_like_time_range(from_pairs):
            return from_pairs
        for root in (dialog, page.locator("body").first):
            for selector in ('p.text-sm.text-gray-500', '[id*="description"]', '[aria-describedby]'):
                locator = root.locator(selector).first
                try:
                    locator.wait_for(state="visible", timeout=400)
                    text = locator.inner_text(timeout=400).strip()
                    normalized = self._normalize_text(text)
                    if text and any(char.isdigit() for char in text) and (":" in text or "/" in text or "am" in normalized or "pm" in normalized):
                        extracted = self._extract_time_range(text)
                        if extracted is not None:
                            return extracted
                except Exception:
                    continue
        text_candidates = self._extract_schedule_candidates(full_text or self._safe_text(dialog))
        if text_candidates:
            return text_candidates[0]
        return "N/A"

    def _extract_time_range(self, text: str) -> str | None:
        match = _TIME_RANGE_RE.search(text or "")
        if match is None:
            return None
        return match.group(0).replace("(He llegado)", "").strip()

    def _extract_duration_text(self, text: str) -> str:
        match = _DURATION_RE.search(text or "")
        if match is None:
            return "N/A"
        return match.group(0).strip()

    @staticmethod
    def _looks_like_time_range(text: str) -> bool:
        return _TIME_RANGE_RE.search(text or "") is not None

    @staticmethod
    def _looks_like_duration_text(text: str) -> bool:
        return _DURATION_RE.search(text or "") is not None
    def _find_block_context_snapshot(self, page: Page) -> Locator | None:
        candidates = page.locator('[role="dialog"][aria-modal="true"], div:has(button:has-text("He llegado"))')
        try:
            count = candidates.count()
        except Exception:
            return None

        best: Locator | None = None
        best_score = 0

        for index in range(count - 1, -1, -1):
            candidate = candidates.nth(index)
            try:
                text = candidate.inner_text(timeout=100).lower()
            except Exception:
                continue
            if not text:
                continue

            score = 0
            if any(t in text for t in ("pago", "precio", "monto")):
                score += 3
            if any(t in text for t in ("estacion", "station")):
                score += 3
            if any(t in text for t in ("duracion", "horas", "horario", "schedule")):
                score += 3
            if self._find_button_by_labels(candidate, self._selectors.final_submit_texts) is not None:
                score += 5
            if self._count_definition_terms(candidate) > 0:
                score += 2

            if score > best_score:
                best_score = score
                best = candidate

        return best if best_score >= 11 else None

    def _try_fast_click_final_from_block_candidate(
        self,
        page: Page,
        context: Locator,
        button: Locator,
        progress_callback: ProgressCallback | None,
        *,
        source: str,
    ) -> bool:
        if self._looks_like_body_context(context):
            self._record_timeline_event("dashboard_body_discarded_as_block_context", source=source, url=page.url)
            self.emit_progress(progress_callback, phase="block_read", message="dashboard/body descartado como contexto de bloque")
            return False
        self._latest_block_snapshot_text = self._capture_block_snapshot_text(context, page)
        self._set_active_flow_context(context, page=page, source=source)
        self._remember_final_button_candidate(
            context=context,
            button=button,
            page=page,
            source=source,
        )
        self._mark_phase_timing("block_visual_detected", source=source, url=page.url)
        self._record_timeline_event("block_visual_detected", source=source, url=page.url)
        self.emit_progress(progress_callback, phase="final_submit", message="bloque detectado por boton final: click inmediato")
        self._mark_phase_timing("final_click_started", source=source, url=page.url)
        try:
            button.click(timeout=400)
        except Exception:
            try:
                button.click(timeout=700, force=True)
            except Exception:
                try:
                    button.evaluate("node => node.click()")
                except Exception:
                    return False
        self._final_submit_already_clicked = True
        self._final_submit_fast_clicked_at = monotonic()
        self._mark_phase_timing("final_click_done", source=source, url=page.url)
        self._record_timeline_event("final_button_clicked", source=source, url=page.url)
        self.emit_progress(progress_callback, phase="final_submit", message="boton final presionado directamente desde deteccion iframe")
        return True
        
    def _submit_final(
        self,
        dialog: Locator,
        page: Page,
        *,
        timeout_ms: int,
        progress_callback: ProgressCallback | None = None,
        session=None,
        extension_assisted: bool = False,
        extension_strict: bool = False,
    ) -> None:
        if bool(getattr(self, "_final_submit_already_clicked", False)):
            return
        started_at = monotonic()
        resolution_reported = False
        button_detected_reported = False
        self._mark_phase_timing("final_click_started", source="_submit_final", url=page.url)
        self.emit_progress(progress_callback, phase="final_submit", message="final_submit timing started")
        snapshot_context = self._find_block_context_snapshot(page)
        if snapshot_context is not None:
            button = self._find_button_by_labels(snapshot_context, self._selectors.final_submit_texts)
            if button is not None:
                self._remember_final_button_candidate(
                    context=snapshot_context,
                    button=button,
                    page=page,
                    source="_find_block_context_snapshot",
                )
                self.emit_progress(progress_callback, phase="final_submit", message="snapshot block button found")
                button.click(timeout=500)
                self._mark_phase_timing("final_click_done", source="_submit_final_snapshot", url=page.url)
                return
        if extension_assisted:
            extension_state = self._extension_state(session, page, note="wait_final_submit_ready")
            extension_phase = self._extension_phase(extension_state)
            if self._extension_phase_is_at_least(extension_phase, "final_submit_ready"):
                resolution_reported = True
                self._record_engine_resolution(session, extension_state, phase=extension_phase, source="extension", note="final_submit")
                self.emit_progress(
                    progress_callback,
                    phase="final_submit",
                    message="espera block_read_ready -> final_submit_ready resuelta por extensión",
                )
            elif extension_strict and extension_phase == "unknown":
                raise self._build_extension_strict_error(
                    phase="final_submit_ready",
                    reason="phase_unknown",
                    state=extension_state,
                )

        for attempt in range(1, 4):
            button = self._find_final_submit_button(dialog, page=page)

            if button is None:
                resolved_context = self._resolve_block_context(dialog, page)
                if resolved_context is not None:
                    button = self._find_final_submit_button(resolved_context, page=page)
                    if button is not None:
                        dialog = resolved_context

            if button is None:
                raise ParipeFlowError(
                    "final_submit",
                    "Se leyo el bloque, pero no aparecio el boton final 'He llegado' en el mismo contexto.",
                )

            try:
                button.wait_for(state="visible", timeout=min(timeout_ms, 400))

                if not button_detected_reported:
                    button_detected_reported = True
                    self.emit_progress(progress_callback, phase="final_submit", message="final_submit block button found")

                self._remember_final_button_candidate(
                    context=dialog,
                    button=button,
                    page=page,
                    source="_submit_final",
                )

                if not resolution_reported:
                    self._record_engine_resolution(session, None, phase="final_submit_ready", source="polling tradicional", note="final_submit")
                    self.emit_progress(
                        progress_callback,
                        phase="final_submit",
                        message="final_submit_ready resuelto por polling tradicional",
                    )
                    resolution_reported = True

                if attempt == 1:
                    button.click(timeout=400)
                elif attempt == 2:
                    button.click(timeout=700, force=True)
                else:
                    button.evaluate("node => node.click()")

                self._record_timeline_event("final_button_clicked", source=f"locator_attempt_{attempt}", url=page.url)
                self._mark_phase_timing("final_click_done", source=f"_submit_final_attempt_{attempt}", url=page.url)
                page.wait_for_timeout(500)

                self.emit_progress(
                    progress_callback,
                    phase="final_submit",
                    message=f"final_submit clicked after {int((monotonic() - started_at) * 1000)} ms",
                )
                return

            except ParipeFlowError:
                raise
            except Exception:
                if attempt == 3:
                    raise ParipeFlowError(
                        "final_submit",
                        "El boton final 'He llegado' fue detectado, pero no respondio despues de varios intentos.",
                    )
                sleep(min(self._SHORT_WAIT_MS, 150) / 1000)
                continue

    def _detect_final_result(
        self,
        dialog: Locator,
        page: Page,
        *,
        timeout_ms: int,
        station_name: str,
        block_price: str,
        block_time: str,
        block_duration: str,
        selfie_retry_count: int,
        deepfakescore_activated: bool,
        reserved_photo_id: str | None,
        progress_callback: ProgressCallback | None,
        session=None,
        extension_assisted: bool = False,
        extension_strict: bool = False,
    ) -> SiteExecutionResult:
        deadline = monotonic() + (timeout_ms / 1000)
        last_successful_step = "final_submit"
        baseline_signature = self._result_signature(dialog, page)
        inferred_success_since: float | None = None
        extension_final_hint = False
        extension_state = None
        fallback_reason = "phase_unknown"
        while monotonic() < deadline:
            extension_phase = "unknown"
            if extension_assisted:
                extension_state = self._extension_state(session, page, note="wait_final_result_ready")
                extension_phase = self._extension_phase(extension_state)
                if extension_phase == "final_result_ready":
                    extension_final_hint = True
                    fallback_reason = "phase_final_result_ready"
                    self.emit_progress(
                        progress_callback,
                        phase="final_result",
                        message="ExtensiÃ³n detectÃ³ final_result_ready. Se usa como fuente primaria.",
                    )
                elif extension_phase != "unknown":
                    fallback_reason = f"phase_{extension_phase}"
            if extension_assisted and extension_phase == "unknown":
                extension_resolution = ExtensionFlowEngine.resolve_final_result_ready(
                    session=session,
                    page=page,
                    note="wait_final_result_ready",
                )
                extension_state = extension_resolution.state
                if extension_resolution.resolved:
                    extension_final_hint = True
                    self.emit_progress(
                        progress_callback,
                        phase="final_result",
                        message="Extensión detectó final_result_ready. Se usa como fuente primaria.",
                    )
                else:
                    fallback_reason = extension_resolution.reason
            if extension_final_hint:
                self._record_engine_resolution(
                    session,
                    extension_state,
                    phase="final_result_ready",
                    source="extension",
                    note="final_result:phase_match",
                )
                self.emit_progress(
                    progress_callback,
                    phase="final_result",
                    message="final_result_ready resuelto por extensión",
                )
                return SiteExecutionResult(
                    success=True,
                    message=(
                        "Proceso completado correctamente en paripe.io. "
                        f"Pago: {block_price}. Estacion: {station_name}. "
                        f"Horario: {block_time}. Duracion: {block_duration}."
                    ),
                    final_status="success",
                    phase="final_result",
                    station_name=station_name,
                    block_price=block_price,
                    block_time=block_time,
                    block_duration=block_duration,
                    selfie_retry_count=selfie_retry_count,
                    deepfakescore_retries=selfie_retry_count,
                    deepfakescore_activated=deepfakescore_activated,
                    reserved_photo_id=reserved_photo_id,
                )
            success_count = self._count_success_messages(dialog, page)
            if success_count > 0:
                if extension_strict:
                    raise self._build_extension_strict_error(
                        phase="final_result_ready",
                        reason=fallback_reason,
                        state=extension_state,
                    )
                self._record_engine_resolution(
                    session,
                    None,
                    phase="final_result_ready",
                    source="extension_fallback_polling",
                    note=f"final_result:{fallback_reason}",
                )
                self.emit_progress(
                    progress_callback,
                    phase="final_result",
                    message="final_result_ready resuelto por fallback tradicional",
                )
                self.emit_progress(
                    progress_callback,
                    phase="final_result",
                    message=f"Confirmacion final detectada. Mensajes de exito encontrados: {success_count}.",
                )
                return SiteExecutionResult(
                    success=True,
                    message=(
                        "Proceso completado correctamente en paripe.io. "
                        f"Pago: {block_price}. Estacion: {station_name}. "
                        f"Horario: {block_time}. Duracion: {block_duration}."
                    ),
                    final_status="success",
                    phase="final_result",
                    station_name=station_name,
                    block_price=block_price,
                    block_time=block_time,
                    block_duration=block_duration,
                    selfie_retry_count=selfie_retry_count,
                    deepfakescore_retries=selfie_retry_count,
                    deepfakescore_activated=deepfakescore_activated,
                    reserved_photo_id=reserved_photo_id,
                )
            body_text = self._safe_normalized_text(page.locator("body").first)
            terminal_state = self._resolve_terminal_state(body_text)
            if terminal_state == "error":
                raise ParipeFlowError(
                    "final_result",
                    "Se presiono 'He llegado', pero el sitio devolvio un error antes de la confirmacion final. Ultimo paso exitoso: final_submit.",
                )
            if terminal_state == "no_block":
                raise ParipeFlowError(
                    "final_result",
                    "El bloque desaparecio o quedo indisponible antes de la confirmacion final. Ultimo paso exitoso: final_submit.",
                    final_status="no_block",
                )
            if "procesando" in body_text or "validando" in body_text or "cargando" in body_text:
                last_successful_step = "final_submit"
            final_button = self._find_final_submit_button(dialog)
            button_missing = final_button is None
            button_disabled = False
            if final_button is not None:
                try:
                    button_disabled = final_button.is_disabled()
                except Exception:
                    button_disabled = False
            signature_changed = self._result_signature(dialog, page) != baseline_signature
            if (button_missing or button_disabled) and signature_changed:
                if inferred_success_since is None:
                    inferred_success_since = monotonic()
                    self.emit_progress(
                        progress_callback,
                        phase="final_result",
                        message="Cambio final de DOM detectado despues del click. Verificando confirmacion final...",
                    )
                elif monotonic() - inferred_success_since >= 1.5:
                    if extension_strict:
                        raise self._build_extension_strict_error(
                            phase="final_result_ready",
                            reason=fallback_reason,
                            state=extension_state,
                        )
                    self._record_engine_resolution(
                        session,
                        None,
                        phase="final_result_ready",
                        source="extension_fallback_polling",
                        note=f"final_result:{fallback_reason}",
                    )
                    self.emit_progress(
                        progress_callback,
                        phase="final_result",
                        message="final_result_ready resuelto por fallback tradicional",
                    )
                    self.emit_progress(
                        progress_callback,
                        phase="final_result",
                        message="Confirmacion final detectada por cambio de estado del flujo.",
                    )
                    return SiteExecutionResult(
                        success=True,
                        message=(
                            "Proceso completado correctamente en paripe.io. "
                            f"Pago: {block_price}. Estacion: {station_name}. "
                            f"Horario: {block_time}. Duracion: {block_duration}."
                        ),
                        final_status="success",
                        phase="final_result",
                        station_name=station_name,
                        block_price=block_price,
                        block_time=block_time,
                        block_duration=block_duration,
                        selfie_retry_count=selfie_retry_count,
                        deepfakescore_retries=selfie_retry_count,
                        deepfakescore_activated=deepfakescore_activated,
                        reserved_photo_id=reserved_photo_id,
                    )
            else:
                inferred_success_since = None
            page.wait_for_timeout(self._SHORT_WAIT_MS)
        raise ParipeFlowError(
            "final_result",
            "Se presiono 'He llegado', pero no aparecio una confirmacion final de exito dentro del timeout esperado. "
            f"Ultimo paso exitoso: {last_successful_step}.",
            final_status="timeout",
        )

    def _resolve_block_context(self, flow_context: Locator, page: Page) -> Locator | None:
        candidates: list[Locator] = []
        active_context = self._get_active_flow_context(page)
        for candidate in (active_context, flow_context, self._find_photo_phase_dialog(page)):
            if candidate is None:
                continue
            if self._locator_is_live(candidate):
                candidates.append(candidate)
        dialogs = page.locator(self._selectors.details_dialog)
        try:
            count = dialogs.count()
        except Exception:
            count = 0
        for index in range(count):
            candidate = dialogs.nth(index)
            if self._locator_is_live(candidate):
                candidates.append(candidate)
        best_context: Locator | None = None
        best_score = -1
        for candidate in candidates:
            if self._looks_like_body_context(candidate):
                self._record_timeline_event("dashboard_body_discarded_as_block_context", url=page.url)
                continue
            if not self._context_looks_like_block(candidate):
                continue
            score = self._score_block_context(candidate)
            if score > best_score:
                best_score = score
                best_context = candidate
        if best_context is not None:
            self._active_flow_context = best_context
        return best_context

    def _context_looks_like_block(self, context: Locator) -> bool:
        text = self._safe_normalized_text(context)
        if not text:
            return False
        signals = self._collect_block_signals_from_dialog(context)
        has_price = signals.get("price_or_payment", False)
        has_station = signals.get("station", False)
        has_time_detail = signals.get("duration", False) or signals.get("schedule", False)
        has_structured_container = signals.get("block_card", False)
        return has_price and has_station and has_time_detail and has_structured_container

    def _count_block_candidates(self, flow_context: Locator, page: Page) -> int:
        total = 1 if self._context_looks_like_block(flow_context) else 0
        dialogs = page.locator(self._selectors.details_dialog)
        try:
            count = dialogs.count()
        except Exception:
            count = 0
        for index in range(count):
            if self._context_looks_like_block(dialogs.nth(index)):
                total += 1
        return total

    def _count_definition_terms(self, context: Locator) -> int:
        try:
            return context.locator("dt").count()
        except Exception:
            return 0

    def _extract_definition_pairs(self, context: Locator) -> dict[str, str]:
        pairs: dict[str, str] = {}
        terms = context.locator("dt")
        try:
            count = terms.count()
        except Exception:
            return pairs
        for index in range(count):
            term = terms.nth(index)
            try:
                label = term.inner_text(timeout=300).strip()
                value = term.locator("xpath=following-sibling::dd[1]").inner_text(timeout=300).strip()
            except Exception:
                continue
            normalized_label = self._normalize_text(label)
            if normalized_label and value:
                pairs[normalized_label] = value
        return pairs

    def _extract_block_pairs(self, context: Locator, *, full_text: str | None = None) -> dict[str, str]:
        pairs = self._extract_definition_pairs(context)
        text_pairs = self._extract_text_pairs(full_text or self._safe_text(context))
        pairs.update({key: value for key, value in text_pairs.items() if value})
        return pairs

    def _extract_text_pairs(self, text: str) -> dict[str, str]:
        pairs: dict[str, str] = {}
        lines = [line.strip(" -:\t") for line in text.splitlines() if line.strip()]
        aliases = {
            "pago": ("pago", "precio", "price", "monto", "valor"),
            "estacion": ("estacion", "station", "estacao"),
            "horario": ("horario", "fecha", "schedule", "hora", "turno", "slot"),
            "duracion": ("duracion", "duration", "tiempo estimado"),
            "horas": ("horas", "hours"),
        }
        for line in lines:
            if ":" not in line:
                continue
            raw_label, raw_value = line.split(":", 1)
            normalized_label = self._normalize_text(raw_label)
            value = raw_value.strip()
            if not normalized_label or not value:
                continue
            for canonical, variants in aliases.items():
                if any(self._normalize_text(variant) in normalized_label for variant in variants):
                    pairs[canonical] = value
        for index, line in enumerate(lines[:-1]):
            normalized_line = self._normalize_text(line)
            next_line = lines[index + 1]
            if len(normalized_line) > 40 or not next_line:
                continue
            for canonical, variants in aliases.items():
                if canonical in pairs:
                    continue
                if any(self._normalize_text(variant) in normalized_line for variant in variants):
                    pairs[canonical] = next_line
                    break
        return pairs

    def _capture_block_snapshot_text(self, context: Locator, page: Page) -> str:
        snapshot_text = self._safe_text(context)
        if snapshot_text:
            return snapshot_text
        if self._looks_like_body_context(context):
            self._record_timeline_event("dashboard_body_discarded_as_block_context", url=page.url, source="snapshot_text")
            return ""
        return self._safe_text(page.locator("body").first)

    def _read_block_details_from_snapshot_text(self, snapshot_text: str) -> tuple[str, str, str, str]:
        pairs = self._extract_text_pairs(snapshot_text)
        payment = self._pick_detail_value(pairs, ("pago", "precio", "price", "valor", "monto"))
        station = self._pick_detail_value(pairs, ("estacion", "station", "estacao"))
        schedule = self._extract_time_range(snapshot_text) or self._pick_detail_value(
            pairs,
            ("horario", "fecha", "schedule", "hora", "turno", "slot"),
        )
        if schedule != "N/A":
            schedule = schedule.replace("(He llegado)", "").strip()
        if schedule == "N/A":
            text_candidates = self._extract_schedule_candidates(snapshot_text)
            if text_candidates:
                schedule = text_candidates[0]
        duration = self._read_duration(pairs, full_text=snapshot_text)
        return payment, station, schedule, duration

    def _read_duration(self, pairs: dict[str, str], *, full_text: str) -> str:
        for candidate in (
            self._pick_detail_value(pairs, ("horas", "hours")),
            self._pick_detail_value(pairs, ("duracion", "duration", "tiempo estimado")),
            self._extract_duration_text(full_text),
        ):
            if candidate != "N/A" and self._looks_like_duration_text(candidate):
                return candidate
        return "N/A"

    def _pick_detail_value(self, pairs: dict[str, str], aliases: tuple[str, ...]) -> str:
        for alias in aliases:
            if alias in pairs and pairs[alias]:
                return pairs[alias]
        for alias in aliases:
            normalized_alias = self._normalize_text(alias)
            for label, value in pairs.items():
                if normalized_alias in label:
                    return value
        return "N/A"

    def _context_has_block_details(self, context: Locator) -> bool:
        text = self._safe_normalized_text(context)
        if not text:
            return False
        has_price = any(token in text for token in ("pago", "precio", "price", "valor", "monto"))
        has_station = any(token in text for token in ("estacion", "station", "estacao"))
        has_time_detail = any(token in text for token in ("horario", "hora", "schedule", "time", "fecha", "slot", "duracion", "duration", "horas", "hours"))
        has_structured_container = self._count_definition_terms(context) > 0
        return has_price and has_station and has_time_detail and has_structured_container

    def _block_signal_snapshot(self, context: Locator) -> dict[str, bool]:
        text = self._safe_normalized_text(context)
        return {
            "price_or_payment": any(token in text for token in ("pago", "precio", "price", "valor", "monto")),
            "station": any(token in text for token in ("estacion", "station", "estacao")),
            "schedule": any(token in text for token in ("horario", "hora", "schedule", "time", "fecha", "slot")),
            "duration": any(token in text for token in ("duracion", "duration", "horas", "hours")),
            "block_card": self._count_definition_terms(context) > 0,
        }

    def _remember_final_button_candidate(
        self,
        *,
        context: Locator,
        button: Locator | None,
        page: Page | None,
        source: str,
    ) -> dict[str, object]:
        context_text_preview = self._safe_text(context)[:500]
        context_is_block = self._context_has_block_details(context)
        block_signals = self._block_signal_snapshot(context)
        try:
            outer_html = button.evaluate("(node) => (node.outerHTML || '').slice(0, 300)") if button is not None else ""
        except Exception:
            outer_html = ""
        try:
            bounding_box = button.bounding_box() if button is not None else None
        except Exception:
            bounding_box = None
        body_text_preview = ""
        current_url = ""
        if page is not None:
            with suppress(Exception):
                body_text_preview = self._safe_text(page.locator("body").first)[:500]
            with suppress(Exception):
                current_url = page.url
        payload = {
            "recorded_at": datetime.now().isoformat(),
            "source": source,
            "text": self._safe_text(button) if button is not None else "",
            "outer_html": outer_html,
            "bounding_box": bounding_box,
            "context_summary": self._describe_live_dialog(context),
            "context_text_preview": context_text_preview,
            "body_text_preview": body_text_preview,
            "context_is_block": context_is_block,
            "block_signals": block_signals,
            "looks_like_dashboard_initial": self._looks_like_body_context(context) and not context_is_block,
            "url": current_url,
        }
        self._last_final_button_candidate = payload
        self._record_timeline_event("final_button_candidate_found", **payload)
        return payload

    def _fast_final_button_probe(self, page: Page, *, click: bool) -> dict[str, object]:
        return page.evaluate(
            """
            ({ labels, click }) => {
                const normalize = (value) =>
                    (value || "")
                        .normalize("NFKD")
                        .replace(/[\\u0300-\\u036f]/g, "")
                        .replace(/\\s+/g, " ")
                        .trim()
                        .toLowerCase();
                const hasAnyText = (text, tokens) => tokens.some((token) => text.includes(normalize(token)));
                const normalizedLabels = labels.map((label) => normalize(label)).filter(Boolean);
                const isVisible = (element) => {
                    if (!element) {
                        return false;
                    }
                    const style = window.getComputedStyle(element);
                    if (!style || style.visibility === "hidden" || style.display === "none") {
                        return false;
                    }
                    const rect = element.getBoundingClientRect();
                    return rect.width >= 2 && rect.height >= 2;
                };
                const candidates = Array.from(
                    document.querySelectorAll("button, [role='button'], input[type='button'], input[type='submit'], a")
                );
                let best = null;
                let bestScore = 0;
                for (const element of candidates) {
                    if (!isVisible(element)) {
                        continue;
                    }
                    const text = normalize(
                        element.innerText || element.value || element.getAttribute("aria-label") || element.textContent || ""
                    );
                    if (!text) {
                        continue;
                    }
                    let score = 0;
                    for (const label of normalizedLabels) {
                        if (text === label) {
                            score = Math.max(score, 100);
                        } else if (text.includes(label)) {
                            score = Math.max(score, 90);
                        }
                    }
                    if (score > bestScore) {
                        bestScore = score;
                        best = { element, text };
                    }
                }
                if (!best) {
                    return { found: false, clicked: false, text: "" };
                }
                const contextElement =
                    best.element.closest("[role='dialog'][aria-modal='true'], dl, section, article, main") || document.body;
                const contextText = (contextElement.innerText || "").trim();
                const normalizedContextText = normalize(contextText);
                const bbox = best.element.getBoundingClientRect();
                const hasPrice = hasAnyText(normalizedContextText, ["pago", "precio", "price", "valor", "monto"]);
                const hasStation = hasAnyText(normalizedContextText, ["estacion", "station", "estacao"]);
                const hasTimeDetail = hasAnyText(normalizedContextText, ["horario", "hora", "schedule", "time", "fecha", "slot", "duracion", "duration", "horas", "hours"]);
                const hasBlockCard = contextElement.querySelectorAll("dt").length > 0;
                const invalidDashboardCandidate = contextElement === document.body && !(hasPrice && hasStation && hasTimeDetail && hasBlockCard);
                if (click) {
                    best.element.click();
                }
                return {
                    found: true,
                    clicked: Boolean(click),
                    text: (best.element.innerText || best.element.value || best.element.getAttribute("aria-label") || best.element.textContent || "").trim(),
                    outer_html: (best.element.outerHTML || "").slice(0, 300),
                    bounding_box: {
                        x: Math.round(bbox.x),
                        y: Math.round(bbox.y),
                        width: Math.round(bbox.width),
                        height: Math.round(bbox.height),
                    },
                    context_text: contextText.slice(0, 500),
                    url: window.location.href,
                    invalid_dashboard_candidate: invalidDashboardCandidate,
                };
            }
            """,
            {"labels": ["He llegado", "I'm here", "I've arrived", "Eu cheguei"], "click": click},
        )

    def _find_final_submit_button(self, context: Locator, page: Page | None = None) -> Locator | None:
        if not self._context_has_block_details(context):
            return None
        button = self._find_button_by_labels(context, self._selectors.final_submit_texts)
        if button is not None:
            self._remember_final_button_candidate(
                context=context,
                button=button,
                page=page,
                source="_find_final_submit_button",
            )
        return button

    def _count_final_submit_buttons(self, context: Locator) -> int:
        return 1 if self._find_final_submit_button(context) is not None else 0

    def _count_success_messages(self, dialog: Locator, page: Page) -> int:
        roots = (dialog, page.locator("body").first)
        total = 0
        for root in roots:
            text = self._safe_normalized_text(root)
            if not text:
                continue
            for marker in self._selectors.success_markers:
                normalized_marker = self._normalize_text(marker)
                if normalized_marker and normalized_marker in text:
                    total += 1
        return total

    def _fast_block_snapshot(self, page: Page) -> dict[str, object]:
        return page.evaluate(
            """
            ({ finalSubmitTexts, continueTexts, selfieInstructionTexts, selfieOptionTexts, processingTexts }) => {
                const normalize = (value) =>
                    (value || "")
                        .normalize("NFKD")
                        .replace(/[\\u0300-\\u036f]/g, "")
                        .replace(/\\s+/g, " ")
                        .trim()
                        .toLowerCase();
                const isVisible = (element) => {
                    if (!element) {
                        return false;
                    }
                    const style = window.getComputedStyle(element);
                    if (!style || style.visibility === "hidden" || style.display === "none") {
                        return false;
                    }
                    const rect = element.getBoundingClientRect();
                    return rect.width >= 2 && rect.height >= 2;
                };
                const body = document.body;
                const bodyText = normalize(body ? body.innerText : "");
                const hasAnyText = (tokens) => tokens.some((token) => bodyText.includes(normalize(token)));
                const visibleElements = Array.from(document.querySelectorAll("button, [role='button'], input[type='button'], input[type='submit'], a"));
                const hasVisibleButtonText = (labels) =>
                    visibleElements.some((element) => {
                        if (!isVisible(element)) {
                            return false;
                        }
                        const candidateText = normalize(
                            element.innerText || element.value || element.getAttribute("aria-label") || element.textContent || ""
                        );
                        return labels.some((label) => candidateText.includes(normalize(label)));
                    });
                const detailsDialogs = Array.from(document.querySelectorAll("[role='dialog'][aria-modal='true']"));
                const hasVisibleBlockCardLike =
                    document.querySelectorAll("dt").length > 0 ||
                    detailsDialogs.some((element) => isVisible(element) && /(?:pago|precio|station|estacion|duracion|duration|horario|schedule)/i.test(element.innerText || "")) ||
                    Array.from(document.querySelectorAll("[id*='description'], dl, [class*='card'], [class*='block']")).some((element) => isVisible(element));
                const hasSelfieInput = Array.from(document.querySelectorAll("input[type='file'], #user_avatar")).some(isVisible);
                return {
                    bodyText,
                    hasFinalButton: hasVisibleButtonText(finalSubmitTexts),
                    hasPaymentText: hasAnyText(["pago", "precio", "price", "valor", "monto"]),
                    hasStationText: hasAnyText(["estacion", "station", "estacao"]),
                    hasScheduleText: hasAnyText(["horario", "hora", "schedule", "time", "fecha", "slot"]),
                    hasDurationText: hasAnyText(["duracion", "duration", "horas", "hours"]),
                    hasBlockCardLike: hasVisibleBlockCardLike,
                    hasSelfieInput,
                    hasContinueButton: hasVisibleButtonText(continueTexts),
                    hasProcessingText: hasAnyText(processingTexts),
                    hasSelfieText: hasAnyText(selfieInstructionTexts) || hasAnyText(selfieOptionTexts),
                };
            }
            """,
            {
                "finalSubmitTexts": list(self._selectors.final_submit_texts),
                "continueTexts": list(self._selectors.continue_texts),
                "selfieInstructionTexts": list(self._selectors.selfie_instruction_texts),
                "selfieOptionTexts": list(self._selectors.selfie_option_texts),
                "processingTexts": list(self._selectors.processing_texts),
            },
        )

    def _fast_context_snapshot(self, context: Locator) -> dict[str, bool]:
        text = self._safe_normalized_text(context)
        return {
            "hasFinalButton": self._find_button_by_labels(context, self._selectors.final_submit_texts) is not None,
            "hasPaymentText": any(token in text for token in ("pago", "precio", "price", "valor", "monto")),
            "hasStationText": any(token in text for token in ("estacion", "station", "estacao")),
            "hasScheduleText": any(token in text for token in ("horario", "hora", "schedule", "time", "fecha", "slot")) or self._looks_like_time_range(text),
            "hasDurationText": any(token in text for token in ("duracion", "duration", "horas", "hours")) or self._looks_like_duration_text(text),
            "hasBlockCardLike": self._count_definition_terms(context) > 0,
            "hasSelfieInput": self._dialog_has_file_input(context),
            "hasContinueButton": self._dialog_has_continue(context),
            "hasProcessingText": any(token in text for token in self._selectors.processing_texts) or self._has_any_selector(context, self._selectors.processing_selectors),
            "hasSelfieText": self._normalized_contains_any(text, self._selectors.selfie_instruction_texts) or self._normalized_contains_any(text, self._selectors.selfie_option_texts),
        }

    def _safe_normalized_text(self, locator: Locator) -> str:
        try:
            return self._normalize_text(locator.inner_text(timeout=400))
        except Exception:
            return ""

    def _safe_text(self, locator: Locator) -> str:
        try:
            return locator.inner_text(timeout=400).strip()
        except Exception:
            return ""

    def _dom_signature(self, page: Page) -> str:
        try:
            text = page.locator("body").inner_text(timeout=250)
        except Exception:
            return ""
        normalized = self._normalize_text(text)
        return normalized[:500]

    def _resolve_terminal_state(self, normalized_text: str) -> str | None:
        if not normalized_text:
            return None
        if self._detect_no_block_message(normalized_text) is not None:
            return "no_block"
        if any(self._normalize_text(text) in normalized_text for text in self._selectors.failure_markers):
            return "error"
        if any(self._normalize_text(text) in normalized_text for text in self._selectors.success_markers):
            return "success"
        return None

    def _extract_schedule_candidates(self, text: str) -> list[str]:
        candidates: list[str] = []
        for line in [part.strip() for part in text.splitlines() if part.strip()]:
            normalized = self._normalize_text(line)
            if self._looks_like_duration_text(line):
                continue
            has_time_signal = ":" in line or bool(re.search(r"\b(?:am|pm)\b", normalized))
            has_date_signal = bool(re.search(r"\b\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?\b", line))
            if has_time_signal or has_date_signal:
                cleaned = line.replace("(He llegado)", "").strip()
                candidates.append(cleaned)
        return candidates

    def _detect_no_block_message(self, normalized_text: str) -> str | None:
        markers = (
            "no hay bloque",
            "sin bloque",
            "bloque no disponible",
            "no blocks available",
            "no block available",
            "nenhum bloco disponivel",
            "sem bloco disponivel",
        )
        if any(marker in normalized_text for marker in markers):
            return "Paripe.io reporto que no hay bloque disponible para completar el flujo."
        return None

    def _is_same_final_step(self, dialog: Locator) -> bool:
        try:
            button = self._find_final_submit_button(dialog)
            return button is not None and button.is_visible()
        except Exception:
            return False

    def _result_signature(self, dialog: Locator, page: Page) -> str:
        dialog_text = self._safe_normalized_text(dialog)
        body_text = self._safe_normalized_text(page.locator("body").first)
        return f"{dialog_text[:400]}|{body_text[:400]}"


    @classmethod
    def _build_duration(cls, duration_range: str, duration_hours: str | None) -> str:
        if duration_range == "N/A":
            return duration_hours or "N/A"
        if duration_hours:
            return f"{duration_range} ({duration_hours})"
        return duration_range

    @staticmethod
    def _normalize_text(text: str) -> str:
        normalized = unicodedata.normalize("NFKD", text)
        ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
        compact = _WHITESPACE_RE.sub(" ", ascii_text).strip()
        return compact.lower()

    @staticmethod
    def _use_extension_engine(local_config: LocalConfig, request: ProcessExecutionRequest) -> bool:
        request_mode = (request.execution_mode or "").strip().lower()
        config_mode = (local_config.flow_engine or "").strip().lower()
        return local_config.enable_browser_extension and (request_mode == "extension" or config_mode == "extension")

    @staticmethod
    def _build_extension_strict_error(*, phase: str, reason: str, state: dict | None, extra: dict | None = None) -> ParipeFlowError:
        state = state if isinstance(state, dict) else {}
        diagnostics = state.get("diagnostics") if isinstance(state.get("diagnostics"), dict) else {}
        payload = {
            "reason": reason,
            "observer_state": {
                "phase": state.get("phase"),
                "last_valid_phase": state.get("lastValidPhase") or state.get("last_valid_phase"),
                "site": state.get("site"),
                "href": state.get("href"),
                "stateSource": state.get("stateSource"),
                "signals": state.get("signals"),
            },
            "diagnostics": diagnostics,
        }
        if extra:
            payload.update(extra)
        return ParipeFlowError(
            phase,
            f"Modo extension estricto: la extension no resolvio {phase}. Diagnostico: {payload}",
            final_status="extension_incomplete",
        )

    @staticmethod
    def _extension_state(session, page: Page, *, note: str) -> dict | None:
        if session is None or not hasattr(session, "capture_extension_debug"):
            return None
        snapshot = session.capture_extension_debug(page=page, note=note)
        if not snapshot:
            return None
        state = snapshot.get("state")
        return state if isinstance(state, dict) else None

    @staticmethod
    def _extension_phase(state: dict | None) -> str:
        if not isinstance(state, dict):
            return "unknown"
        phase = str(state.get("phase") or "unknown")
        if phase != "unknown":
            return phase
        return str(state.get("lastValidPhase") or "unknown")

    @staticmethod
    def _extension_phase_rank(phase: str) -> int | None:
        return {
            "iframe_entry": 0,
            "selfie_stage": 1,
            "loading_after_continue": 2,
            "block_read_ready": 3,
            "final_submit_ready": 4,
            "final_result_ready": 5,
        }.get(phase)

    @classmethod
    def _extension_phase_is_at_least(cls, phase: str, expected_phase: str) -> bool:
        phase_rank = cls._extension_phase_rank(phase)
        expected_rank = cls._extension_phase_rank(expected_phase)
        return phase_rank is not None and expected_rank is not None and phase_rank >= expected_rank

    @classmethod
    def _extension_phase_action(cls, phase: str) -> str:
        if phase in {"iframe_entry", "selfie_stage", "return_to_selfie"}:
            return "selfie"
        if phase == "loading_after_continue":
            return "loading"
        if phase == "block_read_ready":
            return "block"
        if phase == "final_result_ready":
            return "final"
        if cls._extension_phase_is_at_least(phase, "final_submit_ready"):
            return "block"
        return "unknown"

    @staticmethod
    def _record_engine_resolution(session, state: dict | None, *, phase: str, source: str, note: str) -> None:
        if session is None:
            return
        session.record_engine_phase_usage(phase=phase, source=source, note=note, state=state)
