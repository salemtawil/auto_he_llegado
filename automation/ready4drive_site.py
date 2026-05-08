from __future__ import annotations

import threading
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
import re
from time import monotonic
from typing import TYPE_CHECKING
import unicodedata

from automation.base_site import BaseSite, ProgressCallback
from automation.browser_manager import BrowserManager
from automation.engines.extension import ExtensionFlowEngine, ExtensionPhaseDecider
from core.models import LocalConfig, ProcessExecutionRequest, ReservedPhoto, SiteExecutionResult
from services.process_photo_service import ProcessPhotoService
from playwright.sync_api import Locator

if TYPE_CHECKING:
    from playwright.sync_api import Frame, Page


_WHITESPACE_RE = re.compile(r"\s+")


@dataclass(frozen=True)
class Ready4DriveSelectors:
    login_phone: tuple[str, ...] = ('input[type="tel"]', 'input[name="phone"]', 'input[name="telefono"]', 'input[placeholder*="tel" i]')
    login_password: tuple[str, ...] = ('input[type="password"]', 'input[name="password"]', 'input[name="contrasena"]', 'input[name="senha"]')
    login_submit: tuple[str, ...] = ('button[type="submit"]', 'input[type="submit"]', 'form button[type="submit"]', 'button:has-text("Iniciar sesion")', 'button:has-text("Entrar")', 'button:has-text("Log in")', 'button:has-text("Login")', 'button:has-text("Sign in")', 'button:has-text("Iniciar sessao")')
    login_failure_texts: tuple[str, ...] = ("contrasena incorrecta", "credenciales incorrectas", "usuario o clave incorrectos", "login fallido", "incorrect password", "wrong password", "invalid credentials", "login failed", "senha incorreta", "credenciais invalidas", "falha no login")
    login_submit_texts: tuple[str, ...] = ("Iniciar sesion", "Entrar", "Log in", "Login", "Sign in", "Iniciar sessao")
    action_card_candidates: tuple[str, ...] = ("button", '[role="button"]', "a", 'div[class*="card"]', 'div[class*="option"]', 'div[class*="item"]', 'div[class*="tile"]')
    modal_roots: tuple[str, ...] = ('[role="dialog"]', '[aria-modal="true"]', ".modal", ".dialog", ".overlay", '[class*="modal"]', '[class*="dialog"]')
    flow_iframe_selectors: tuple[str, ...] = (
        "iframe[src*='paripe.io/imhere-light']",
        "iframe[title='He llegado']",
        "iframe[title='I arrived']",
        "iframe[title=\"I'm here\"]",
        "iframe[title='Cheguei']",
        "iframe[title='Eu cheguei']",
    )
    account_markers: tuple[str, ...] = ("cuenta propia", "cuenta prestada", "own account", "personal account", "borrowed account", "conta propria", "conta própria", "conta emprestada")
    own_account_texts: tuple[str, ...] = ("Cuenta propia", "Own account", "Personal account", "Conta propria", "Conta própria")
    no_block_texts: tuple[str, ...] = ("no hay bloque", "no hay bloque disponible", "sin bloque disponible", "no blocks available", "no block available", "sem bloco disponivel", "nenhum bloco disponivel")
    borrowed_account_texts: tuple[str, ...] = ("Cuenta prestada", "Borrowed account", "Borrowed Account", "Conta emprestada")
    borrowed_account_subtitles: tuple[str, ...] = ("Selecciona para generar una foto", "Select to generate a photo", "Selecione para gerar uma foto")
    photo_inputs: tuple[str, ...] = ('#user_avatar', 'input[id="user_avatar"]', 'input[type="file"]', 'input[accept*="image"]')
    continue_texts: tuple[str, ...] = ("Continuar", "Continue", "Prosseguir", "Continuar agora")
    selfie_instruction_texts: tuple[str, ...] = (
        "para continuar, selecciona una opcion y tomate una foto tipo selfie",
        "foto tipo selfie",
        "tomate una foto tipo selfie",
        "toma una foto tipo selfie",
        "selecciona una opcion",
        "para continuar",
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
    selfie_form_selectors: tuple[str, ...] = (
        "form",
        "[role='dialog']",
        "[class*='selfie']",
        "[class*='photo']",
        "[class*='avatar']",
    )
    processing_done_markers: tuple[str, ...] = ("estacion", "station", "estacao", "precio", "price", "valor", "hora", "time", "horario")
    processing_texts: tuple[str, ...] = (
        "validando",
        "validating",
        "validacao",
        "processing",
        "procesando",
        "processando",
        "loading",
        "cargando",
        "carregando",
        "verifying",
        "verificando",
        "subiendo",
        "uploading",
        "enviando",
        "sending",
    )
    processing_selectors: tuple[str, ...] = (
        "[aria-busy='true']",
        "[role='progressbar']",
        "[class*='loading']",
        "[class*='spinner']",
        "[class*='progress']",
        "[class*='validating']",
    )
    final_success_texts: tuple[str, ...] = (
        "he llegado enviado",
        "he llegado exitoso",
        "estoy aqui exitoso",
        "proceso exitoso",
        "bloque tomado",
        "completado",
        "request submitted",
        "i'm here successful",
        "i've arrived successful",
        "completed",
        "process successful",
        "solicitacao enviada",
        "eu cheguei com sucesso",
        "processo concluido",
    )
    final_failure_texts: tuple[str, ...] = ("error", "fallo", "intenta de nuevo", "try again", "failed", "tente novamente")
    final_submit_texts: tuple[str, ...] = ("He llegado", "Confirmar", "Enviar", "I'm here", "I've arrived", "I arrived", "Confirm", "Submit", "Eu cheguei", "Cheguei")
    station_labels: tuple[str, ...] = ("Estacion", "Station", "Estacao", "Punto", "Point")
    price_labels: tuple[str, ...] = ("Precio", "Price", "Valor", "Monto")
    time_labels: tuple[str, ...] = ("Hora", "Time", "Horario")


@dataclass
class BackgroundPhotoPreparation:
    process_id: str | None
    ready_event: threading.Event = field(default_factory=threading.Event)
    reserved_photo: ReservedPhoto | None = None
    error: Exception | None = None
    consumed: bool = False


@dataclass(frozen=True)
class Ready4DriveActionSpec:
    ui_name: str
    aliases: tuple[str, ...]
    phrases: tuple[str, ...]
    required_token_groups: tuple[tuple[str, ...], ...]
    forbidden_tokens: tuple[str, ...] = ()


@dataclass(frozen=True)
class FlowRoot:
    root: Page | Frame | Locator
    phase: str
    description: str
    is_iframe: bool


class Ready4DriveFlowError(RuntimeError):
    def __init__(self, phase: str, message: str, *, final_status: str = "failed") -> None:
        super().__init__(message)
        self.phase = phase
        self.final_status = final_status
        self.message = message


class Ready4DriveSite(BaseSite):
    site_name = "ready4drive.com"
    _ENTRY_URL = "https://ready4drive.com/login"
    _LOGIN_TIMEOUT_MS = 6_000
    _ACTION_BUTTON_TIMEOUT_MS = 6_000
    _POST_ACTION_TIMEOUT_MS = 8_000
    _NO_BLOCK_GRACE_MS = 5_000
    _BLOCK_WAIT_MS = 120_000
    _SELFIE_REBOUND_WAIT_MS = 12_000
    _SELFIE_REBOUND_STABLE_MS = 1_200
    _BLOCK_WAIT_POLL_MS = 150
    _SHORT_WAIT_MS = 1_500
    _POLL_MS = 150
    _ACTION_SPECS: tuple[Ready4DriveActionSpec, ...] = (
        Ready4DriveActionSpec("He llegado Instantaneas", ("He llegado Instantaneas", "He llegado Instantáneas"), ("he llegado instantaneas", "i arrived snapshots", "i arrived instant snapshots", "cheguei instantaneas"), (("he", "arrived", "cheguei"), ("llegado", "arrived", "cheguei"), ("instantaneas", "snapshots")), ("selfie", "ruta", "route", "rota")),
        Ready4DriveActionSpec("He llegado", ("He llegado", "I arrived", "Cheguei"), ("he llegado", "i arrived", "cheguei"), (("he llegado", "i arrived", "cheguei"),), ("instantaneas", "snapshots", "selfie", "ruta", "route", "rota")),
        Ready4DriveActionSpec("Selfie en ruta", ("Selfie en ruta", "Selfie on route", "Selfie em rota"), ("selfie en ruta", "selfie on route", "selfie on the way", "selfie em rota"), (("selfie",), ("ruta", "route", "way", "rota"))),
    )

    def __init__(self, browser_manager: BrowserManager | None = None, photo_service: ProcessPhotoService | None = None, selectors: Ready4DriveSelectors | None = None) -> None:
        self._browser_manager = browser_manager or BrowserManager()
        self._photo_service = photo_service or ProcessPhotoService()
        self._selectors = selectors or Ready4DriveSelectors()
        self._process_timeline: list[dict[str, object]] = []
        self._phase_timings: list[dict[str, object]] = []
        self._timing_started_at: float | None = None
        self._timing_last_event_at: float | None = None
        self._timing_first_by_event: dict[str, dict[str, object]] = {}
        self._timing_lock = threading.Lock()
        self._last_process_debug_export: dict[str, object] = {}

    def _reset_process_debug_state(self) -> None:
        self._process_timeline = []
        self._phase_timings = []
        self._timing_started_at = None
        self._timing_last_event_at = None
        self._timing_first_by_event = {}
        self._last_process_debug_export = {}

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
            "selfie_validation": self._format_timing_value(self._timing_delta("selfie_validation_started", "block_detected")),
            "block_wait": self._format_timing_value(self._timing_delta("block_wait_started", "block_detected")),
            "final_click": self._format_timing_value(self._timing_delta("final_click_started", "final_click_done")),
            "final_result": self._format_timing_value(self._timing_delta("final_result_started", "final_result_done")),
        }
        return {key: value for key, value in summary.items() if value is not None}

    def _build_timing_summary_text(self) -> str:
        summary = self._build_timing_summary()
        parts: list[str] = []
        label_map = {
            "login": "login",
            "photo_prepare": "foto",
            "selfie_validation": "selfie",
            "block_wait": "bloque",
            "final_click": "final",
            "final_result": "resultado",
            "total": "total",
        }
        for key in ("login", "photo_prepare", "selfie_validation", "block_wait", "final_click", "final_result", "total"):
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
            "last_process_debug_export": dict(self._last_process_debug_export),
        }

    def _start_background_photo_preparation(
        self,
        *,
        process_id: str | None,
        progress_callback: ProgressCallback | None,
    ) -> BackgroundPhotoPreparation:
        preparation = BackgroundPhotoPreparation(process_id=process_id)
        self._mark_phase_timing("photo_prepare_started", process_id=process_id, source="background")
        self.emit_progress(progress_callback, phase="photo_prepare", message="preparando foto en background")

        def worker() -> None:
            try:
                preparation.reserved_photo = self._photo_service.reserve_photo(process_id=process_id)
                self._mark_phase_timing(
                    "photo_prepare_done",
                    process_id=process_id,
                    photo_id=preparation.reserved_photo.photo_id if preparation.reserved_photo else None,
                )
            except Exception as exc:
                preparation.error = exc
            finally:
                preparation.ready_event.set()

        threading.Thread(target=worker, daemon=True).start()
        return preparation

    def _resolve_prepared_photo(
        self,
        preparation: BackgroundPhotoPreparation | None,
        *,
        progress_callback: ProgressCallback | None,
        process_id: str | None,
    ) -> ReservedPhoto:
        if preparation is None:
            self.emit_progress(progress_callback, phase="photo_prepare", message="esperando foto reservada")
            reserved_photo = self._photo_service.reserve_photo(process_id=process_id)
            self._mark_phase_timing("photo_prepare_done", process_id=process_id, photo_id=reserved_photo.photo_id)
            self.emit_progress(progress_callback, phase="photo_prepare", message="foto reservada usada en selfie")
            return reserved_photo

        if preparation.ready_event.is_set():
            self.emit_progress(progress_callback, phase="photo_prepare", message="foto preparada antes del input selfie")
        else:
            self.emit_progress(progress_callback, phase="photo_prepare", message="esperando foto reservada")
            preparation.ready_event.wait()
        if preparation.error is not None:
            raise preparation.error
        if preparation.reserved_photo is None:
            raise RuntimeError("La preparación de foto en background terminó sin una foto reservada.")
        preparation.consumed = True
        self.emit_progress(progress_callback, phase="photo_prepare", message="foto reservada usada en selfie")
        return preparation.reserved_photo

    def _discard_background_photo(self, preparation: BackgroundPhotoPreparation | None) -> None:
        if preparation is None or not preparation.ready_event.is_set() or preparation.consumed:
            return
        reserved_photo = preparation.reserved_photo
        if reserved_photo is None:
            return
        try:
            self._photo_service.release_photo(reserved_photo.photo_id)
        except Exception:
            pass
        try:
            self._photo_service.delete_local_copy(reserved_photo.local_path)
        except Exception:
            pass

    def _get_supported_action_specs(self) -> tuple[Ready4DriveActionSpec, ...]:
        return (
            Ready4DriveActionSpec(
                "He llegado Instantaneas",
                (
                    "He llegado Instantaneas",
                    "He llegado Instantáneas",
                    "He llegado Instantaneo",
                    "He llegado Instantáneo",
                    "I'm here instant offers",
                    "I've arrived instant",
                    "Eu cheguei Instantaneo",
                    "Eu cheguei Instantâneo",
                ),
                (
                    "he llegado instantaneas",
                    "he llegado instantaneo",
                    "i'm here instant offers",
                    "i've arrived instant",
                    "i arrived snapshots",
                    "i arrived instant snapshots",
                    "eu cheguei instantaneo",
                    "cheguei instantaneas",
                ),
                (("he", "i'm", "i've", "eu", "cheguei"), ("llegado", "here", "arrived", "cheguei"), ("instantaneas", "instantaneo", "instant", "snapshots", "offers")),
                ("selfie", "ruta", "route", "rota"),
            ),
            Ready4DriveActionSpec(
                "He llegado",
                ("He llegado", "I'm here", "I've arrived", "I arrived", "Eu cheguei", "Cheguei"),
                ("he llegado", "i'm here", "i've arrived", "i arrived", "eu cheguei", "cheguei"),
                (("he llegado", "i'm here", "i've arrived", "i arrived", "eu cheguei", "cheguei"),),
                ("instantaneas", "instantaneo", "instant", "snapshots", "offers", "selfie", "ruta", "route", "rota"),
            ),
            Ready4DriveActionSpec(
                "Selfie en ruta",
                ("Selfie en ruta", "In route selfie", "Route selfie", "Selfie on route", "Selfie na rota", "Selfie em rota"),
                ("selfie en ruta", "in route selfie", "route selfie", "selfie on route", "selfie on the way", "selfie na rota", "selfie em rota"),
                (("selfie",), ("ruta", "route", "way", "rota")),
            ),
        )

    def execute(self, request: ProcessExecutionRequest, *, local_config: LocalConfig, progress_callback: ProgressCallback | None = None) -> SiteExecutionResult:
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
        progress_callback: ProgressCallback | None,
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
        progress_callback: ProgressCallback | None,
    ) -> SiteExecutionResult:
        return self._execute_pipeline(
            request,
            local_config=local_config,
            progress_callback=progress_callback,
        )

    def _execute_pipeline(self, request: ProcessExecutionRequest, *, local_config: LocalConfig, progress_callback: ProgressCallback | None) -> SiteExecutionResult:
        self._reset_process_debug_state()
        self._mark_phase_timing("process_started", process_id=getattr(request, "process_id", None))
        self._photo_service.validate_atomic_reservation_support()
        extension_engine_requested = self._use_extension_engine(local_config, request)
        process_id = getattr(request, "process_id", None)
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
        page = session.page
        page_timeout_ms = max(local_config.page_timeout_seconds, 1) * 1000
        action_timeout_ms = max(local_config.action_timeout_seconds, 1) * 1000
        action_spec = self._get_action_spec(request.action_name)
        try:
            self.emit_progress(
                progress_callback,
                phase="engine",
                message="creando sesion limpia para ready4drive.com",
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
            self.emit_progress(progress_callback, phase="login", message="Abriendo ready4drive.com/login y esperando solo el formulario minimo...")
            self._mark_phase_timing("login_started", url=self._ENTRY_URL)
            self._open_login(page, timeout_ms=max(page_timeout_ms, self._LOGIN_TIMEOUT_MS))
            cleanup_report = session.clear_auth_state(page=page)
            self._record_timeline_event("session_state_cleared", **cleanup_report)
            self.emit_progress(progress_callback, phase="login", message="estado de sesión limpiado")
            self.emit_progress(progress_callback, phase="login", message="login limpio confirmado")
            session.capture_extension_debug(page=page, note="login_page_opened")
            page.set_default_timeout(max(page_timeout_ms, action_timeout_ms))
            login_result = self._perform_login(page, request=request, progress_callback=progress_callback, timeout_ms=max(page_timeout_ms, self._LOGIN_TIMEOUT_MS))
            session.capture_extension_debug(page=page, note="login_completed")
            if login_result is not None:
                self._mark_phase_timing("process_finished", success=login_result.success, final_status=login_result.final_status, phase=login_result.phase)
                self._emit_timing_summary(progress_callback)
                return login_result
            self._mark_phase_timing("login_done", url=page.url)
            self.emit_progress(
                progress_callback,
                phase="account_selection",
                message="Validacion de cuenta omitida. Continuando directo al flujo.",
            )
            prepared_photo = self._start_background_photo_preparation(
                process_id=process_id,
                progress_callback=progress_callback,
            )
            self.emit_progress(progress_callback, phase="initial_action", message=f"Resolviendo la accion inicial '{action_spec.ui_name}' segun idioma y estructura...")
            frame_count_before_action = len(page.frames)
            self._mark_phase_timing("initial_action_started", action=action_spec.ui_name)
            self._click_action_card(page, action_spec)
            self._mark_phase_timing("initial_action_clicked", action=action_spec.ui_name, url=page.url)
            session.capture_extension_debug(page=page, note="initial_action_clicked")
            self.emit_progress(progress_callback, phase="initial_action", message="Accion inicial presionada.")
            self.emit_progress(progress_callback, phase="iframe_entry", message="Esperando carga del flujo He llegado dentro del iframe...")
            self._mark_phase_timing("iframe_wait_started", source="flow_root")
            flow_root = self._wait_for_flow_root(
                page,
                action_spec,
                timeout_ms=max(action_timeout_ms, self._POST_ACTION_TIMEOUT_MS),
                expected_min_frame_count=frame_count_before_action + 1,
                session=session,
                extension_assisted=extension_engine_requested and session.extension_loaded,
            )
            self._mark_phase_timing("iframe_detected", source="flow_root", url=page.url)
            session.capture_extension_debug(page=page, note="iframe_flow_detected")
            primary_flow_root = self._resolve_primary_flow_root(page, flow_root)
            self.emit_progress(progress_callback, phase="iframe_entry", message=flow_root.description)
            if flow_root.is_iframe:
                self.emit_progress(progress_callback, phase="iframe_entry", message="Iframe He llegado detectado.")
                self.emit_progress(progress_callback, phase="iframe_entry", message="Iframe He llegado seleccionado como contexto principal del flujo.")
            else:
                self.emit_progress(progress_callback, phase="iframe_entry", message="No aparecio un iframe claro; se mantiene el mejor contexto disponible del flujo.")
            self.emit_progress(progress_callback, phase="iframe_entry", message="Verificando disponibilidad real dentro del flujo activo...")
            no_block_message = self._detect_no_block(
                primary_flow_root,
                page=page,
                timeout_ms=self._SHORT_WAIT_MS,
                baseline_frame_count=frame_count_before_action,
            )
            if no_block_message is not None:
                self._mark_phase_timing("process_finished", success=False, final_status="no_block", phase="block_check")
                self._emit_timing_summary(progress_callback)
                return SiteExecutionResult(success=False, message=no_block_message, final_status="no_block", phase="block_check")
            self.emit_progress(progress_callback, phase="iframe_entry", message="Flujo embebido disponible.")
            result = self._execute_iframe_flow(
                session=session,
                page=page,
                flow_root=primary_flow_root,
                progress_callback=progress_callback,
                action_timeout_ms=min(page_timeout_ms, action_timeout_ms),
                block_wait_ms=max(page_timeout_ms, self._BLOCK_WAIT_MS),
                max_selfie_retries=local_config.max_selfie_retries,
                process_id=process_id,
                prepared_photo=prepared_photo,
                extension_assisted=extension_engine_requested and session.extension_loaded,
            )
            self._mark_phase_timing("process_finished", success=result.success, final_status=result.final_status, phase=result.phase)
            self._emit_timing_summary(progress_callback)
            return result
        except Ready4DriveFlowError as exc:
            self._mark_phase_timing("process_finished", success=False, final_status=exc.final_status, phase=exc.phase)
            self._emit_timing_summary(progress_callback)
            return SiteExecutionResult(success=False, message=exc.message, final_status=exc.final_status, phase=exc.phase, selfie_retry_count=selfie_retry_count, deepfakescore_activated=deepfakescore_activated, reserved_photo_id=reserved_photo.photo_id if reserved_photo else None)
        except Exception as exc:
            self._mark_phase_timing("process_finished", success=False, final_status="failed", phase="unexpected")
            self._emit_timing_summary(progress_callback)
            return SiteExecutionResult(success=False, message=f"Fallo en flujo real de ready4drive.com: {exc}", final_status="failed", phase="unexpected", selfie_retry_count=selfie_retry_count, deepfakescore_activated=deepfakescore_activated, reserved_photo_id=reserved_photo.photo_id if reserved_photo else None)
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

    def _execute_iframe_flow(
        self,
        *,
        session=None,
        page: Page,
        flow_root: Page | Frame | Locator,
        progress_callback: ProgressCallback | None,
        action_timeout_ms: int,
        block_wait_ms: int,
        max_selfie_retries: int,
        process_id: str | None = None,
        prepared_photo: BackgroundPhotoPreparation | None = None,
        extension_assisted: bool = False,
    ) -> SiteExecutionResult:
        reserved_photo: ReservedPhoto | None = None
        selfie_retry_count = 0
        deepfakescore_activated = False
        self.emit_progress(progress_callback, phase="selfie_stage", message="Usando el iframe de He llegado como contexto principal.")
        self.emit_progress(progress_callback, phase="selfie_stage", message="Validacion de cuenta omitida. Continuando directo al flujo.")
        if extension_assisted:
            extension_state = self._extension_state(session, page, note="wait_selfie_stage")
            if self._extension_phase(extension_state) == "selfie_stage":
                self._record_engine_resolution(session, extension_state, phase="selfie_stage", source="extension", note="selfie_stage")
                self.emit_progress(progress_callback, phase="selfie_stage", message="selfie_stage detectado por extensión")
            else:
                self._record_engine_resolution(session, None, phase="selfie_stage", source="polling tradicional", note="selfie_stage")
                self.emit_progress(progress_callback, phase="selfie_stage", message="selfie_stage resuelto por polling tradicional")
        else:
            self._record_engine_resolution(session, None, phase="selfie_stage", source="polling tradicional", note="selfie_stage")
            self.emit_progress(progress_callback, phase="selfie_stage", message="selfie_stage resuelto por polling tradicional")
        try:
            block_context, reserved_photo, selfie_retry_count, deepfakescore_activated = self._complete_selfie_until_block(
                flow_root,
                page=page,
                progress_callback=progress_callback,
                action_timeout_ms=action_timeout_ms,
                block_wait_ms=block_wait_ms,
                max_selfie_retries=max_selfie_retries,
                process_id=process_id,
                prepared_photo=prepared_photo,
                session=session,
                extension_assisted=extension_assisted,
            )
            if session is not None:
                session.capture_extension_debug(page=page, note="block_ready_after_selfie")
            self.emit_progress(progress_callback, phase="block_read", message="Bloque detectado. Leyendo informacion del bloque...")
            station_name, block_price, block_time, block_duration = self._read_block_data(block_context, page=page)
            self.emit_progress(
                progress_callback,
                phase="block_read",
                message=(
                    f"Datos del bloque guardados. Estacion: {station_name}. "
                    f"Precio: {block_price}. Horario: {block_time}. Duracion: {block_duration}."
                ),
            )
            self.emit_progress(progress_callback, phase="block_read", message=f"Reintentos de selfie: {selfie_retry_count}.")
            final_context = self._resolve_block_context(page, block_context) or block_context
            final_button_count = self._count_final_submit_buttons(final_context)
            self.emit_progress(progress_callback, phase="final_submit", message=f"Boton final He llegado detectado. Candidatos encontrados: {final_button_count}.")
            self.emit_progress(progress_callback, phase="final_submit", message="Presionando boton final He llegado...")
            final_context = self._submit_final(
                block_context,
                page=page,
                progress_callback=progress_callback,
                session=session,
                extension_assisted=extension_assisted,
            )
            if session is not None:
                session.capture_extension_debug(page=page, note="final_submit_clicked")
            self.emit_progress(progress_callback, phase="final_submit", message="Boton final He llegado presionado y validado.")
            self.emit_progress(progress_callback, phase="final_result", message="Esperando resultado final en iframe...")
            self._mark_phase_timing("final_result_started", url=page.url)
            result = self._detect_final_result(
                final_context,
                page=page,
                timeout_ms=max(action_timeout_ms, self._BLOCK_WAIT_MS),
                station_name=station_name,
                block_price=block_price,
                block_time=block_time,
                block_duration=block_duration,
                selfie_retry_count=selfie_retry_count,
                deepfakescore_activated=deepfakescore_activated,
                reserved_photo=reserved_photo,
                progress_callback=progress_callback,
                session=session,
                extension_assisted=extension_assisted,
            )
            self._mark_phase_timing("final_result_done", success=result.success, final_status=result.final_status, url=page.url)
            if session is not None:
                session.capture_extension_debug(page=page, note="final_result_detected")
            self._last_process_debug_export = {
                "last_url": page.url,
                "final_status": result.final_status,
                "success": result.success,
                "timing_summary": self._build_timing_summary(),
                "timing_summary_text": self._build_timing_summary_text(),
            }
            return result
        except Ready4DriveFlowError as exc:
            return SiteExecutionResult(success=False, message=exc.message, final_status=exc.final_status, phase=exc.phase, selfie_retry_count=selfie_retry_count, deepfakescore_activated=deepfakescore_activated, reserved_photo_id=reserved_photo.photo_id if reserved_photo else None)
        except Exception as exc:
            return SiteExecutionResult(success=False, message=f"Fallo en flujo real de ready4drive.com: {exc}", final_status="failed", phase="unexpected", selfie_retry_count=selfie_retry_count, deepfakescore_activated=deepfakescore_activated, reserved_photo_id=reserved_photo.photo_id if reserved_photo else None)
        finally:
            if reserved_photo is not None:
                self._photo_service.consume_photo(reserved_photo.photo_id)
                self._photo_service.delete_local_copy(reserved_photo.local_path)

    def _perform_login(self, page: Page, *, request: ProcessExecutionRequest, progress_callback: ProgressCallback | None, timeout_ms: int) -> SiteExecutionResult | None:
        self.emit_progress(progress_callback, phase="login", message="Pagina de login cargada.")
        self._fill_first(page, self._selectors.login_phone, request.phone_number)
        self._fill_first(page, self._selectors.login_password, request.password)
        self.emit_progress(progress_callback, phase="login", message="Credenciales completadas.")
        self._press_login_submit(page)
        self.emit_progress(progress_callback, phase="login", message="Boton de ingresar presionado.")
        login_outcome = self._wait_for_login_outcome(page, timeout_ms=timeout_ms)
        if login_outcome == "failure":
            return SiteExecutionResult(success=False, message="Login fallido: ready4drive.com reporto contrasena incorrecta o credenciales invalidas.", final_status="login_failed", phase="login")
        if login_outcome == "no_response":
            return SiteExecutionResult(success=False, message="Login fallido: el boton de ingresar no genero respuesta visible.", final_status="failed", phase="login")
        if login_outcome != "success":
            return SiteExecutionResult(success=False, message="Login fallido: no aparecieron acciones validas ni una respuesta clara tras enviar credenciales.", final_status="login_failed", phase="login")
        self.emit_progress(progress_callback, phase="login", message="Login exitoso.")
        return None

    def _wait_for_login_outcome(self, page: Page, *, timeout_ms: int) -> str:
        deadline = monotonic() + (timeout_ms / 1000)
        no_response_deadline = monotonic() + 1.2
        while monotonic() < deadline:
            if self._has_any_text_now(page, self._selectors.login_failure_texts):
                return "failure"
            if self._has_any_action_card_now(page):
                return "success"
            if monotonic() >= no_response_deadline and self._is_login_form_ready(page) and self._is_login_submit_available(page):
                return "no_response"
            self._wait_interval(page, self._POLL_MS)
        return "timeout"

    def _open_login(self, page: Page, *, timeout_ms: int) -> None:
        page.goto(self._ENTRY_URL, wait_until="domcontentloaded", timeout=timeout_ms)
        self._first_locator(page, self._selectors.login_phone, timeout_ms=min(timeout_ms, 3_000))
        self._first_locator(page, self._selectors.login_password, timeout_ms=min(timeout_ms, 3_000))

    def _press_login_submit(self, page: Page) -> None:
        submit = self._find_login_submit(page)
        if submit is None:
            raise Ready4DriveFlowError("login", "No se encontro el boton real de ingresar en ready4drive.com.")
        try:
            submit.scroll_into_view_if_needed(timeout=1_000)
        except Exception:
            pass
        self._wait_for_enabled(submit, timeout_ms=2_000, phase="login", error_message="El boton de ingresar sigue deshabilitado en ready4drive.com.")
        try:
            submit.click(timeout=1_500)
            return
        except Exception:
            pass
        try:
            submit.click(timeout=1_500, force=True)
            return
        except Exception:
            pass
        try:
            submit.press("Enter")
            return
        except Exception as exc:
            raise Ready4DriveFlowError("login", "No se pudo presionar el boton real de ingresar en ready4drive.com.") from exc

    def _find_login_submit(self, page: Page) -> Locator | None:
        for selector in self._selectors.login_submit:
            locator = page.locator(selector).first
            try:
                locator.wait_for(state="visible", timeout=700)
                return locator
            except Exception:
                continue
        form = self._find_login_form(page)
        if form is None:
            return None
        for selector in self._selectors.login_submit:
            locator = form.locator(selector).first
            try:
                locator.wait_for(state="visible", timeout=500)
                return locator
            except Exception:
                continue
        return self._best_login_submit_candidate(form)

    def _find_login_form(self, page: Page) -> Locator | None:
        phone = self._try_first_locator(page, self._selectors.login_phone, timeout_ms=700)
        password = self._try_first_locator(page, self._selectors.login_password, timeout_ms=700)
        for field in (phone, password):
            if field is None:
                continue
            try:
                form = field.locator("xpath=ancestor::form[1]").first
                form.wait_for(state="attached", timeout=400)
                return form
            except Exception:
                continue
        return None

    def _best_login_submit_candidate(self, root: Locator) -> Locator | None:
        candidates = root.locator("button, input[type='submit'], [role='button']")
        count = candidates.count()
        best_locator: Locator | None = None
        best_score = 0
        for index in range(count):
            locator = candidates.nth(index)
            if not self._is_visible(locator):
                continue
            score = self._score_login_submit_candidate(locator)
            if score > best_score:
                best_score = score
                best_locator = locator
        return best_locator if best_score > 0 else None

    def _score_login_submit_candidate(self, locator: Locator) -> int:
        text = self._candidate_text(locator)
        score = 0
        if "submit" in text:
            score += 100
        for token in self._selectors.login_submit_texts:
            normalized = self._normalize_text(token)
            if normalized and normalized in text:
                score += 80
        try:
            if locator.get_attribute("type") == "submit":
                score += 120
        except Exception:
            pass
        return score

    def _get_action_spec(self, action_name: str) -> Ready4DriveActionSpec:
        normalized_name = self._normalize_text(action_name)
        specs = self._get_supported_action_specs()
        for spec in specs:
            if normalized_name in {self._normalize_text(spec.ui_name), *(self._normalize_text(alias) for alias in spec.aliases)}:
                return spec
        allowed = ", ".join(spec.ui_name for spec in specs)
        raise RuntimeError(f"Accion de ready4drive.com no soportada: '{action_name}'. Opciones validas: {allowed}")

    def _click_action_card(self, page: Page, action_spec: Ready4DriveActionSpec) -> None:
        candidates = self._action_card_candidates(page)
        deadline = monotonic() + (self._ACTION_BUTTON_TIMEOUT_MS / 1000)
        best_locator: Locator | None = None
        best_score = 0
        last_seen_texts: list[str] = []
        while monotonic() < deadline:
            count = candidates.count()
            for index in range(count):
                locator = candidates.nth(index)
                if not self._locator_is_clickable_candidate(locator):
                    continue
                text = self._candidate_text(locator)
                if text:
                    last_seen_texts.append(text)
                score = self._score_action_match(text, action_spec)
                if score > best_score:
                    best_score = score
                    best_locator = locator
            if best_locator is not None and best_score >= 80:
                self._click_locator_resilient(
                    best_locator,
                    phase="action_select",
                    error_message=f"No se pudo presionar la accion '{action_spec.ui_name}' en ready4drive.com.",
                )
                return
            self._wait_interval(page, self._POLL_MS)
        if best_locator is not None and best_score > 0:
            self._click_locator_resilient(
                best_locator,
                phase="action_select",
                error_message=f"No se pudo presionar la accion '{action_spec.ui_name}' en ready4drive.com.",
            )
            return
        seen = ", ".join(dict.fromkeys(last_seen_texts[:10])) or "sin textos visibles"
        raise Ready4DriveFlowError("action_select", f"No se encontro la accion '{action_spec.ui_name}' con variantes por idioma. Textos visibles: {seen}")

    def _wait_for_flow_root(self, page: Page, action_spec: Ready4DriveActionSpec, *, timeout_ms: int, expected_min_frame_count: int = 0, session=None, extension_assisted: bool = False) -> FlowRoot:
        started_at = monotonic()
        deadline = monotonic() + (timeout_ms / 1000)
        while monotonic() < deadline:
            if extension_assisted:
                extension_state = self._extension_state(session, page, note="wait_iframe_entry")
                extension_phase = self._extension_phase(extension_state)
                if extension_state is not None and extension_phase in {"iframe_entry", "selfie_stage"}:
                    frame = self._find_any_live_flow_frame(page)
                    if frame is not None:
                        self._record_engine_resolution(session, extension_state, phase="iframe_entry", source="extension", note="iframe_entry")
                        return FlowRoot(root=frame, phase="iframe_detect", description=f"Pantalla siguiente detectada por la extensión dentro del iframe {self._describe_frame(frame)}.", is_iframe=True)
            frame = self._find_action_frame(page, action_spec, expected_min_frame_count=expected_min_frame_count)
            modal = self._find_action_modal(page, action_spec)
            modal_score = self._score_modal_root(modal, action_spec) if modal is not None else 0
            frame_score = self._score_frame(frame, action_spec) if frame is not None else 0
            if frame is not None and frame_score >= max(modal_score, 6):
                self._record_engine_resolution(session, None, phase="iframe_entry", source="polling tradicional", note="iframe_entry")
                return FlowRoot(root=frame, phase="iframe_detect", description=f"Pantalla siguiente detectada dentro del iframe {self._describe_frame(frame)}.", is_iframe=True)
            if modal is not None and modal_score > 0:
                self._record_engine_resolution(session, None, phase="iframe_entry", source="polling tradicional", note="iframe_entry")
                return FlowRoot(root=modal, phase="modal_check", description="Pantalla siguiente detectada en el DOM principal.", is_iframe=False)
            elapsed_ms = (monotonic() - started_at) * 1000
            if elapsed_ms >= self._NO_BLOCK_GRACE_MS and not self._has_positive_flow_signal(page, baseline_frame_count=max(expected_min_frame_count - 1, 0)):
                no_block_frame = self._find_frame_with_text(page, self._selectors.no_block_texts)
                if no_block_frame is not None:
                    return FlowRoot(root=no_block_frame, phase="iframe_detect", description=f"Mensaje de bloque detectado dentro del iframe {self._describe_frame(no_block_frame)}.", is_iframe=True)
                if self._has_any_text_now(page, self._selectors.no_block_texts):
                    return FlowRoot(root=page, phase="modal_check", description="Pantalla siguiente detectada en el DOM principal mediante mensaje de bloque.", is_iframe=False)
            self._wait_interval(page, self._POLL_MS)
        raise Ready4DriveFlowError("iframe_detect", "No se detecto la siguiente pantalla despues del boton inicial. Se revisaron modal principal e iframes visibles, pero no aparecieron Cuenta prestada, carga de foto ni mensajes de bloque.", final_status="iframe_failed")

    def _resolve_primary_flow_root(self, page: Page, flow_root: FlowRoot) -> Page | Frame | Locator:
        if flow_root.is_iframe and not isinstance(flow_root.root, Locator):
            return flow_root.root
        iframe_root = self._find_any_live_flow_frame(page)
        if iframe_root is not None:
            return iframe_root
        return flow_root.root

    def _find_action_modal(self, page: Page, action_spec: Ready4DriveActionSpec) -> Locator | None:
        for selector in self._selectors.modal_roots:
            roots = page.locator(selector)
            count = roots.count()
            for index in range(count):
                root = roots.nth(index)
                if not self._is_visible(root):
                    continue
                text = self._normalized_locator_text(root)
                if not text:
                    continue
                if self._contains_any(text, self._selectors.account_markers) or self._contains_any(text, self._selectors.no_block_texts):
                    return root
                if self._score_action_match(text, action_spec) > 0:
                    return root
        return None

    def _score_modal_root(self, modal: Locator | None, action_spec: Ready4DriveActionSpec) -> int:
        if modal is None:
            return 0
        text = self._normalized_locator_text(modal)
        if not text:
            return 0
        score = 0
        if self._contains_any(text, self._selectors.account_markers):
            score += 5
        if self._contains_any(text, self._selectors.no_block_texts):
            score += 3
        if self._has_any_selector_now(modal, self._selectors.photo_inputs):
            score += 4
        if self._contains_any(text, self._selectors.continue_texts):
            score += 2
        if self._score_action_match(text, action_spec) > 0:
            score += 1
        return score

    def _find_action_frame(self, page: Page, action_spec: Ready4DriveActionSpec, *, expected_min_frame_count: int = 0) -> Frame | None:
        visible_frame_count = len(page.frames)
        if expected_min_frame_count > 0 and visible_frame_count < expected_min_frame_count:
            return None
        best_frame: Frame | None = None
        best_score = 0
        for frame in page.frames:
            if frame == page.main_frame:
                continue
            score = self._score_frame(frame, action_spec)
            if score > best_score:
                best_score = score
                best_frame = frame
        if best_score >= 6:
            return best_frame
        return None

    def _find_frame_with_text(self, page: Page, texts: tuple[str, ...]) -> Frame | None:
        for frame in page.frames:
            if frame == page.main_frame:
                continue
            if self._has_any_text_now(frame, texts):
                return frame
        return None

    def _score_frame(self, frame: Frame, action_spec: Ready4DriveActionSpec) -> int:
        text = self._normalized_root_text(frame)
        if not text:
            score = 0
        else:
            score = 0
            if self._contains_any(text, self._selectors.account_markers):
                score += 4
            if self._contains_any(text, self._selectors.no_block_texts):
                score += 3
            if self._contains_any(text, self._selectors.continue_texts):
                score += 2
            if self._score_action_match(text, action_spec) > 0:
                score += 1
        frame_url = self._normalize_text((getattr(frame, "url", "") or "").strip())
        if "paripe.io/imhere-light" in frame_url:
            score += 10
        if "stripe.com" in frame_url and "paripe.io/imhere-light" in frame_url:
            score += 8
        if "stripe.network" in frame_url and "paripe.io/imhere-light" in frame_url:
            score += 8
        title = self._normalize_text(self._frame_title(frame))
        if title in {"he llegado", "i arrived", "cheguei"}:
            score += 6
        if self._has_any_selector_now(frame, self._selectors.photo_inputs):
            score += 3
        return score

    def _describe_frame(self, frame: Frame) -> str:
        frame_url = (getattr(frame, "url", "") or "").strip()
        frame_title = self._frame_title(frame)
        if frame_url and frame_title:
            return f"{frame_title} ({frame_url})"
        return frame_url or frame_title or "<iframe sin url visible>"

    def _frame_title(self, frame: Frame) -> str:
        try:
            frame_element = frame.frame_element()
            return (frame_element.get_attribute("title") or "").strip()
        except Exception:
            return ""

    def _detect_no_block(self, root: Page | Frame | Locator, *, page: Page, timeout_ms: int, baseline_frame_count: int = 0) -> str | None:
        deadline = monotonic() + (timeout_ms / 1000)
        no_block_seen = False
        while monotonic() < deadline:
            if self._root_has_positive_flow_signal(root) or self._has_positive_flow_signal(page, baseline_frame_count=baseline_frame_count):
                return None
            if self._has_any_text_now(root, self._selectors.no_block_texts) or self._has_any_text_now(page, self._selectors.no_block_texts):
                no_block_seen = True
            self._wait_interval(page, self._POLL_MS)
        if no_block_seen and not self._root_has_positive_flow_signal(root) and not self._has_positive_flow_signal(page, baseline_frame_count=baseline_frame_count):
            return "No hay bloque disponible en ready4drive.com para la accion seleccionada."
        return None

    def _has_positive_flow_signal(self, page: Page, *, baseline_frame_count: int = 0) -> bool:
        if baseline_frame_count > 0 and len(page.frames) > baseline_frame_count:
            return True
        if self._root_has_positive_flow_signal(page):
            return True
        for frame in page.frames:
            if frame == page.main_frame:
                continue
            if self._frame_looks_like_flow(frame) or self._root_has_positive_flow_signal(frame):
                return True
        return False

    def _root_has_positive_flow_signal(self, root: Page | Frame | Locator) -> bool:
        normalized_text = self._normalized_root_text(root)
        if self._contains_any(normalized_text, self._selectors.account_markers + self._selectors.continue_texts):
            return True
        return self._has_any_selector_now(root, self._selectors.photo_inputs)

    def _frame_looks_like_flow(self, frame: Frame) -> bool:
        frame_url = self._normalize_text((getattr(frame, "url", "") or "").strip())
        if "paripe.io/imhere-light" in frame_url:
            return True
        if ("stripe.com" in frame_url or "stripe.network" in frame_url) and "paripe.io/imhere-light" in frame_url:
            return True
        return False

    def _press_borrowed_account(self, root: Page | Frame | Locator, *, borrowed_title: Locator | None = None) -> None:
        borrowed_title = borrowed_title or self._require_borrowed_account_title(root)
        borrowed_container = self._find_borrowed_account_card(borrowed_title)
        if borrowed_container is None:
            raise Ready4DriveFlowError("account_select", "Se encontro 'Cuenta prestada', pero no se pudo resolver su contenedor clickable padre.")
        borrowed_control = self._find_borrowed_account_control(borrowed_container, borrowed_title)
        if self._try_select_borrowed_account(borrowed_container, borrowed_control):
            if self._wait_for_borrowed_account_selected(root, borrowed_container, borrowed_control=borrowed_control, timeout_ms=2_500):
                return
            raise Ready4DriveFlowError("account_select", "Click enviado pero sin cambio real de selección en 'Cuenta prestada'.")
        raise Ready4DriveFlowError("account_select", "Se encontro la tarjeta de 'Cuenta prestada', pero no se pudo enviar un click valido sobre su contenedor o control real.")

    def _find_borrowed_account_card(self, title_locator: Locator) -> Locator | None:
        card_candidates = (
            "xpath=ancestor::label[1]",
            "xpath=ancestor::*[@role='radio'][1]",
            "xpath=ancestor::*[@role='button'][1]",
            "xpath=ancestor::button[1]",
            "xpath=ancestor::*[contains(@class, 'cursor-pointer')][1]",
            "xpath=ancestor::*[contains(@class, 'rounded')][1]",
            "xpath=ancestor::div[contains(@class, 'border')][1]",
            "xpath=ancestor::div[2]",
            "xpath=ancestor::div[1]",
        )
        for xpath in card_candidates:
            try:
                candidate = title_locator.locator(xpath).first
                candidate.wait_for(state="visible", timeout=300)
                candidate_text = self._normalized_locator_text(candidate)
                if self._contains_any(candidate_text, self._selectors.borrowed_account_texts):
                    if self._contains_any(candidate_text, self._selectors.borrowed_account_subtitles):
                        return candidate
                    return candidate
            except Exception:
                continue
        return self._find_clickable_container_from_title(title_locator)

    def _find_borrowed_account_control(self, card_locator: Locator, title_locator: Locator) -> Locator | None:
        control_selectors = (
            "input[type='radio']",
            "input[type='checkbox']",
            "[role='radio']",
            "[data-checked]",
            "[aria-checked]",
            "[aria-selected]",
            "[data-state]",
        )
        for root in (card_locator, title_locator):
            for selector in control_selectors:
                try:
                    locator = root.locator(selector).first
                    locator.wait_for(state="attached", timeout=200)
                    return locator
                except Exception:
                    continue
        associated_input = self._find_associated_input_from_label(card_locator)
        if associated_input is not None:
            return associated_input
        return None

    def _find_associated_input_from_label(self, card_locator: Locator) -> Locator | None:
        try:
            label = card_locator.locator("xpath=ancestor-or-self::label[1]").first
            label.wait_for(state="attached", timeout=200)
        except Exception:
            return None
        try:
            associated_id = label.get_attribute("for") or ""
        except Exception:
            associated_id = ""
        if associated_id:
            try:
                page = label.page
                locator = page.locator(f"#{associated_id}").first
                locator.wait_for(state="attached", timeout=200)
                return locator
            except Exception:
                pass
        for selector in ("input[type='radio']", "input[type='checkbox']"):
            try:
                locator = label.locator(selector).first
                locator.wait_for(state="attached", timeout=200)
                return locator
            except Exception:
                continue
        return None

    def _try_select_borrowed_account(self, card_locator: Locator, control_locator: Locator | None) -> bool:
        candidates: list[Locator] = [card_locator]
        immediate_parent = self._try_locator(card_locator, "xpath=..")
        if immediate_parent is not None:
            candidates.append(immediate_parent)
        label_candidate = self._try_locator(card_locator, "xpath=ancestor-or-self::label[1]")
        if label_candidate is not None:
            candidates.append(label_candidate)
        if control_locator is not None:
            candidates.append(control_locator)

        for index, candidate in enumerate(candidates):
            use_force = index == len(candidates) - 1
            if self._try_click_candidate(candidate, use_force=use_force):
                return True
        return False

    def _try_locator(self, locator: Locator, selector: str) -> Locator | None:
        try:
            candidate = locator.locator(selector).first
            candidate.wait_for(state="attached", timeout=200)
            return candidate
        except Exception:
            return None

    def _try_click_candidate(self, locator: Locator, *, use_force: bool) -> bool:
        try:
            locator.wait_for(state="visible", timeout=700)
            locator.scroll_into_view_if_needed(timeout=700)
        except Exception:
            pass
        try:
            locator.click(timeout=1_000)
            return True
        except Exception:
            pass
        if not use_force:
            return False
        try:
            locator.click(timeout=1_000, force=True)
            return True
        except Exception:
            return False

    def _upload_photo(self, root: Page | Frame | Locator, *, reserved_photo: ReservedPhoto, timeout_ms: int, file_input: Locator | None = None) -> None:
        file_input = file_input or self._require_photo_input(root, timeout_ms=timeout_ms)
        file_input.set_input_files(Path(reserved_photo.local_path))
        if self._wait_for_uploaded_photo(root, file_input, reserved_photo=reserved_photo, timeout_ms=min(timeout_ms, 3_000)):
            return
        raise Ready4DriveFlowError("photo_upload", "No se pudo confirmar que la foto quedo cargada antes de continuar.")

    def _continue_from_modal(self, root: Page | Frame | Locator, *, continue_button: Locator | None = None) -> None:
        continue_button = continue_button or self._require_continue_button(root)
        self._wait_for_enabled(continue_button, timeout_ms=2_000, phase="modal_continue", error_message="El boton equivalente a 'Continuar' sigue deshabilitado en ready4drive.com.")
        self._click_locator_resilient(continue_button, phase="modal_continue", error_message="No se pudo presionar el boton equivalente a 'Continuar' dentro del flujo activo.")
        if self._wait_for_post_continue_change(root, continue_button, timeout_ms=2_500):
            return
        raise Ready4DriveFlowError("modal_continue", "No se detecto cambio visible despues de presionar 'Continuar'.")

    def _complete_selfie_until_block(
        self,
        root: Page | Frame | Locator,
        *,
        page: Page,
        progress_callback: ProgressCallback | None,
        action_timeout_ms: int,
        block_wait_ms: int,
        max_selfie_retries: int,
        process_id: str | None = None,
        prepared_photo: BackgroundPhotoPreparation | None = None,
        session=None,
        extension_assisted: bool = False,
    ) -> tuple[Page | Frame | Locator, ReservedPhoto | None, int, bool]:
        deepfakescore_activated = False
        current_root = root
        attempt = 1
        while True:
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
                        phase="processing_loading_after_continue" if phase_action == "loading" else "block_read",
                        message=f"ExtensiÃ³n reporta fase actual {extension_phase}. Se omiten fases anteriores.",
                    )
                    if phase_action == "loading":
                        block_context = self._wait_for_block_context(
                            current_root,
                            page=page,
                            timeout_ms=block_wait_ms,
                            progress_callback=progress_callback,
                            session=session,
                            extension_assisted=extension_assisted,
                        )
                        return block_context, None, max(attempt - 1, 0), deepfakescore_activated
                    block_context = self._resolve_block_context(page, current_root) or current_root
                    return block_context, None, max(attempt - 1, 0), deepfakescore_activated
            attempt_label = self._format_retry_attempt_label(attempt, max_selfie_retries)
            current_root = self._resolve_selfie_retry_root(page, current_root)
            self.emit_progress(progress_callback, phase="selfie_stage", message=f"Selfie detectada dentro del iframe. Intento {attempt_label}.")
            if attempt >= 2:
                self.emit_progress(progress_callback, phase="selfie_retry_if_needed", message="Selfie subida mas de una vez. Marca de multiples selfies activada.")
                self.emit_progress(progress_callback, phase="selfie_retry_if_needed", message=f"Reintentando con nueva foto. Intento {attempt_label}.")
            self.emit_progress(progress_callback, phase="selfie_stage", message="Preparando foto para el input selfie...")
            self._mark_phase_timing("selfie_input_detected", attempt=attempt, url=page.url)
            reserved_photo = self._resolve_prepared_photo(
                prepared_photo,
                progress_callback=progress_callback,
                process_id=process_id,
            )
            prepared_photo = None
            try:
                self.emit_progress(progress_callback, phase="selfie_stage", message="Subiendo la foto dentro del iframe o contenedor activo...")
                file_input = self._require_photo_input(current_root, timeout_ms=action_timeout_ms)
                self.emit_progress(progress_callback, phase="selfie_stage", message="Input file encontrado.")
                self.emit_progress(progress_callback, phase="selfie_stage", message=f"Foto usada en intento {attempt}: {reserved_photo.original_filename}.")
                self._mark_phase_timing("photo_upload_started", attempt=attempt, file_name=reserved_photo.original_filename)
                self._upload_photo(current_root, reserved_photo=reserved_photo, timeout_ms=action_timeout_ms, file_input=file_input)
                self.emit_progress(progress_callback, phase="selfie_stage", message="Foto cargada.")
                self._mark_phase_timing("photo_upload_done", attempt=attempt, file_name=reserved_photo.original_filename)
                self.emit_progress(progress_callback, phase="selfie_stage", message="Presionando Continuar para seguir el flujo...")
                continue_button = self._require_continue_button(current_root)
                self.emit_progress(progress_callback, phase="selfie_stage", message="Continuar encontrado.")
                self._continue_from_modal(current_root, continue_button=continue_button)
                self._mark_phase_timing("continue_clicked", attempt=attempt, url=page.url)
                self.emit_progress(progress_callback, phase="selfie_stage", message="Continuar presionado.")
                resolution_source = "polling tradicional"
                if extension_assisted:
                    extension_state = self._extension_state(session, page, note="wait_loading_after_continue")
                    extension_phase = self._extension_phase(extension_state)
                    if self._extension_phase_is_at_least(extension_phase, "loading_after_continue") or extension_phase == "return_to_selfie":
                        resolution_source = "extension"
                        self._record_engine_resolution(session, extension_state, phase=extension_phase, source="extension", note="loading_after_continue")
                        self.emit_progress(
                            progress_callback,
                            phase="processing_loading_after_continue",
                            message="espera selfie_stage -> loading_after_continue resuelta por extensión",
                        )
                if resolution_source == "polling tradicional":
                    self._record_engine_resolution(session, None, phase="loading_after_continue", source="polling tradicional", note="loading_after_continue")
                    self.emit_progress(
                        progress_callback,
                        phase="processing_loading_after_continue",
                        message="espera selfie_stage -> loading_after_continue resuelta por polling tradicional",
                    )
                self.emit_progress(progress_callback, phase="processing_loading_after_continue", message="Esperando validacion de selfie...")
                self.emit_progress(progress_callback, phase="processing_loading_after_continue", message="Esperando aparicion del bloque...")
                self._mark_phase_timing("selfie_validation_started", attempt=attempt, url=page.url)
                self._mark_phase_timing("block_wait_started", attempt=attempt, url=page.url)
                block_context = self._wait_for_block_context(
                    current_root,
                    page=page,
                    timeout_ms=block_wait_ms,
                    progress_callback=progress_callback,
                    session=session,
                    extension_assisted=extension_assisted,
                )
                self._mark_phase_timing("block_detected", attempt=attempt, url=page.url)
                if attempt >= 2:
                    self.emit_progress(progress_callback, phase="block_read", message="Retry exitoso, bloque detectado.")
                    self.emit_progress(progress_callback, phase="block_read", message="Reenganchando al flujo normal desde retry/selfie hacia block_read.")
                else:
                    self.emit_progress(progress_callback, phase="block_read", message="Bloque detectado en primer intento.")
                self.emit_progress(progress_callback, phase="block_read", message="Bloque detectado.")
                return block_context, reserved_photo, max(attempt - 1, 0), deepfakescore_activated
            except Ready4DriveFlowError as exc:
                if exc.final_status == "selfie_retry":
                    self.emit_progress(progress_callback, phase="selfie_retry_if_needed", message="Retorno a selfie detectado.")
                    if not deepfakescore_activated:
                        self.emit_progress(progress_callback, phase="selfie_retry_if_needed", message="deepfakescore activado | reintentos: 1")
                        deepfakescore_activated = True
                    else:
                        self.emit_progress(progress_callback, phase="selfie_retry_if_needed", message=f"deepfakescore activado | reintentos: {attempt}")
                    self.emit_progress(progress_callback, phase="selfie_retry_if_needed", message=exc.message)
                    self.emit_progress(progress_callback, phase="selfie_retry_if_needed", message="Reintentando con nueva foto.")
                    self._finalize_reserved_photo(reserved_photo)
                    reserved_photo = None
                    if self._retry_limit_reached(attempt, max_selfie_retries):
                        self.emit_progress(progress_callback, phase="selfie_retry_if_needed", message="Maximo de intentos de selfie agotado.")
                        raise Ready4DriveFlowError(
                            "selfie_retry_if_needed",
                            "Maximo de reintentos alcanzado tras volver a la pantalla de selfie.",
                            final_status="timeout",
                        )
                    current_root = self._resolve_selfie_retry_root(page, current_root)
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

    def _resolve_selfie_retry_root(self, page: Page, previous_root: Page | Frame | Locator) -> Page | Frame | Locator:
        current_root = self._resolve_current_flow_context(page, previous_root)
        if self._selfie_phase_visible(current_root):
            return current_root
        iframe_root = self._find_any_live_flow_frame(page)
        if iframe_root is not None and self._selfie_phase_visible(iframe_root):
            return iframe_root
        return current_root

    def _selfie_phase_visible(self, root: Page | Frame | Locator) -> bool:
        if self._has_strong_block_signal_raw(root):
            return False
        signals = self._collect_selfie_return_signals(root)
        structural_signals = (
            signals["file_input"],
            signals["user_avatar"],
            signals["continue_button"],
            signals["selfie_form"] or signals["account_options"],
        )
        structural_ready = sum(1 for enabled in structural_signals if enabled) >= 3
        textual_confirmation = signals["selfie_text"] or signals["account_options"]
        return structural_ready and textual_confirmation

    def _finalize_reserved_photo(self, reserved_photo: ReservedPhoto) -> None:
        self._photo_service.consume_photo(reserved_photo.photo_id)
        self._photo_service.delete_local_copy(reserved_photo.local_path)

    def _wait_for_block_context(
        self,
        root: Page | Frame | Locator,
        *,
        page: Page,
        timeout_ms: int,
        progress_callback: ProgressCallback | None,
        session=None,
        extension_assisted: bool = False,
    ) -> Page | Frame | Locator:
        deadline = monotonic() + (timeout_ms / 1000)
        poll_iteration = 0
        extension_block_hint = False
        extension_return_hint = False
        extension_state = None
        fallback_reason = "phase_unknown"
        while monotonic() < deadline:
            poll_iteration += 1
            extension_phase = "unknown"
            if extension_assisted:
                extension_state = self._extension_state(session, page, note="wait_block_read_ready")
                extension_phase = self._extension_phase(extension_state)
                if self._extension_phase_is_at_least(extension_phase, "block_read_ready"):
                    extension_block_hint = True
                    fallback_reason = f"phase_{extension_phase}"
                    self.emit_progress(
                        progress_callback,
                        phase="block_read",
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
                        phase="block_read",
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
            current_context = self._resolve_current_flow_context(page, root)
            block_context = self._resolve_block_context(page, current_context) or current_context
            current_context_text = self._normalized_root_text(block_context)
            context_description = self._describe_live_flow_context(current_context)
            selfie_signals = self._collect_selfie_return_signals(current_context)
            block_signals = self._collect_block_signals(block_context)
            processing_signals = self._collect_processing_signals(current_context)
            selfie_diagnostics = self._selfie_signal_diagnostics(current_context)
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
                self._record_engine_resolution(
                    session,
                    extension_state,
                    phase="return_to_selfie",
                    source="extension",
                    note="selfie_retry:phase_match",
                )
                self.emit_progress(
                    progress_callback,
                    phase="selfie_retry_if_needed",
                    message="return_to_selfie resuelto por extensión",
                )
                structural_sources = [
                    name
                    for name in ("file_input", "user_avatar", "continue_button", "selfie_form", "account_options")
                    if selfie_signals.get(name, False)
                ]
                textual_sources = [
                    name
                    for name in ("selfie_text", "account_options")
                    if selfie_signals.get(name, False)
                ]
                raise Ready4DriveFlowError(
                    "photo_upload",
                    (
                        "Retorno a selfie detectado. "
                        f"user_avatar={'si' if selfie_signals['user_avatar'] else 'no'}, "
                        f"Continuar={'si' if selfie_signals['continue_button'] else 'no'}, "
                        f"texto_selfie={'si' if selfie_signals['selfie_text'] else 'no'}, "
                        "sin senales fuertes de bloque. "
                        f"Activadores deepfakescore estructurales: {', '.join(structural_sources) if structural_sources else 'ninguno'}. "
                        f"textuales: {', '.join(textual_sources) if textual_sources else 'ninguno'}."
                    ),
                    final_status="selfie_retry",
                )
            self.emit_progress(
                progress_callback,
                phase="block_read",
                message=(
                    f"Revisando iframe / contexto actual. Poll {poll_iteration}. "
                    f"Contexto: {context_description}. "
                    f"fuente={'body' if isinstance(current_context, Locator) else 'iframe'}. "
                    f"input[type=file]={selfie_diagnostics['file_inputs']}. "
                    f"user_avatar={'si' if selfie_diagnostics['user_avatar'] else 'no'}. "
                    f"Continuar={selfie_diagnostics['continue_buttons']}. "
                    f"texto_selfie={'si' if selfie_signals['selfie_text'] else 'no'}. "
                    f"senales_bloque={self._format_active_signals(block_signals)}. "
                    f"senales_processing={self._format_active_signals(processing_signals)}."
                ),
            )
            no_block_message = self._detect_no_block(current_context, page=page, timeout_ms=self._POLL_MS)
            if no_block_message is not None:
                raise Ready4DriveFlowError("block_read", no_block_message, final_status="no_block")
            if self._root_looks_like_block(current_context_text, block_context):
                self._record_engine_resolution(
                    session,
                    None,
                    phase="block_read_ready",
                    source="extension_fallback_polling",
                    note=f"block_read:{fallback_reason}",
                )
                residual_selfie = [
                    name
                    for name in ("selfie_text", "account_options", "selfie_form", "file_input", "user_avatar", "continue_button")
                    if selfie_signals.get(name, False)
                ]
                if residual_selfie:
                    self.emit_progress(
                        progress_callback,
                        phase="block_read",
                        message=(
                            "Senales de selfie residuales detectadas, pero bloque real confirmado: "
                            f"{', '.join(residual_selfie)}."
                        ),
                    )
                self.emit_progress(
                    progress_callback,
                    phase="block_read",
                    message=f"Senales fuertes que confirmaron bloque real: {self._format_active_signals(block_signals)}.",
                )
                self.emit_progress(
                    progress_callback,
                    phase="block_read",
                    message="block_read resuelto por fallback tradicional",
                )
                self.emit_progress(progress_callback, phase="block_read", message="Bloque detectado.")
                return block_context
            selfie_retry_reason = self._selfie_retry_reason(current_context, selfie_signals)
            if selfie_retry_reason is not None:
                self._record_engine_resolution(
                    session,
                    None,
                    phase="return_to_selfie",
                    source="extension_fallback_polling",
                    note=f"selfie_retry:{fallback_reason}",
                )
                structural_sources = [
                    name
                    for name in ("file_input", "user_avatar", "continue_button", "selfie_form", "account_options")
                    if selfie_signals.get(name, False)
                ]
                textual_sources = [
                    name
                    for name in ("selfie_text", "account_options")
                    if selfie_signals.get(name, False)
                ]
                self.emit_progress(progress_callback, phase="selfie_retry_if_needed", message="Retorno a selfie detectado.")
                self.emit_progress(
                    progress_callback,
                    phase="selfie_retry_if_needed",
                    message=(
                        f"Motivo exacto del retry: {selfie_retry_reason}. "
                        f"Contexto usado: {context_description}. "
                        f"Senales selfie: {self._format_active_signals(selfie_signals)}. "
                        f"Senales bloque: {self._format_active_signals(block_signals)}."
                    ),
                )
                raise Ready4DriveFlowError(
                    "photo_upload",
                    (
                        "Retorno a selfie detectado. "
                        f"user_avatar={'si' if selfie_signals['user_avatar'] else 'no'}, "
                        f"Continuar={'si' if selfie_signals['continue_button'] else 'no'}, "
                        f"texto_selfie={'si' if selfie_signals['selfie_text'] else 'no'}, "
                        "sin senales fuertes de bloque. "
                        f"Activadores deepfakescore estructurales: {', '.join(structural_sources) if structural_sources else 'ninguno'}. "
                        f"textuales: {', '.join(textual_sources) if textual_sources else 'ninguno'}."
                    ),
                    final_status="selfie_retry",
                )
            if self._processing_phase_visible(current_context):
                discarded = [name for name, enabled in block_signals.items() if enabled]
                self.emit_progress(progress_callback, phase="processing_loading_after_continue", message="Esperando validacion de selfie...")
                self.emit_progress(progress_callback, phase="processing_loading_after_continue", message="Esperando aparicion del bloque...")
                if discarded:
                    self.emit_progress(
                        progress_callback,
                        phase="processing_loading_after_continue",
                        message=f"Senales descartadas por prematuras mientras el iframe seguia validando/cargando: {', '.join(discarded)}.",
                    )
                self._wait_interval(page, self._BLOCK_WAIT_POLL_MS)
                continue
            if block_signals.get("schedule", False) and not self._has_strong_block_signal(block_context):
                self.emit_progress(
                    progress_callback,
                    phase="block_read",
                    message="Senal 'schedule' descartada por insuficiente para confirmar bloque.",
                )
            if block_context is not current_context and self._root_looks_like_block(current_context_text, block_context):
                self.emit_progress(
                    progress_callback,
                    phase="block_read",
                    message="Bloque detectado en contexto nuevo tras el retry. Se prioriza block_read normal.",
                )
            self._wait_interval(page, self._BLOCK_WAIT_POLL_MS)
        raise Ready4DriveFlowError(
            "block_read",
            "No aparecio la informacion del bloque despues de Continuar dentro del mismo iframe de ready4drive.com.",
            final_status="timeout",
        )

    def _selfie_retry_reason(self, root: Page | Frame | Locator, selfie_signals: dict[str, bool]) -> str | None:
        if self._has_strong_block_signal(root):
            return None
        if selfie_signals.get("user_avatar", False) and selfie_signals.get("continue_button", False) and (
            selfie_signals.get("selfie_text", False)
            or selfie_signals.get("file_input", False)
            or selfie_signals.get("selfie_form", False)
            or selfie_signals.get("account_options", False)
        ):
            return "user_avatar + Continuar + texto_selfie reaparecieron sin bloque real"
        return None

    def _resolve_block_context(self, page: Page, preferred_root: Page | Frame | Locator) -> Page | Frame | Locator | None:
        best_candidate: Page | Frame | Locator | None = None
        best_score = -1
        for candidate in self._iter_live_flow_context_candidates(page, preferred_root):
            candidate_text = self._normalized_root_text(candidate)
            if not self._has_strong_block_signal(candidate):
                continue
            if not self._root_looks_like_block(candidate_text, candidate):
                continue
            score = self._score_block_context(candidate)
            if score > best_score:
                best_score = score
                best_candidate = candidate
        return best_candidate

    def _iter_live_flow_context_candidates(self, page: Page, preferred_root: Page | Frame | Locator) -> list[Page | Frame | Locator]:
        candidates: list[Page | Frame | Locator] = []
        iframe_candidate = self._find_any_live_flow_frame(page)
        for candidate in (
            preferred_root,
            iframe_candidate,
        ):
            if candidate is None or not self._context_is_live(candidate):
                continue
            if any(existing is candidate for existing in candidates):
                continue
            candidates.append(candidate)
        if iframe_candidate is None:
            for candidate in (
                self._find_any_live_flow_modal(page),
                page,
            ):
                if candidate is None or not self._context_is_live(candidate):
                    continue
                if any(existing is candidate for existing in candidates):
                    continue
                candidates.append(candidate)
        return candidates

    def _resolve_current_flow_context(self, page: Page, previous_root: Page | Frame | Locator) -> Page | Frame | Locator:
        candidates: list[Page | Frame | Locator] = []
        if self._context_is_live(previous_root):
            candidates.append(previous_root)
        frame = self._find_any_live_flow_frame(page)
        if frame is not None:
            candidates.append(frame)
        elif not self._root_is_iframe_flow(previous_root):
            modal = self._find_any_live_flow_modal(page)
            if modal is not None:
                candidates.append(modal)
        best_candidate: Page | Frame | Locator = previous_root
        best_score = -1
        for candidate in candidates:
            score = self._score_live_flow_context(candidate)
            if score > best_score:
                best_score = score
                best_candidate = candidate
        return best_candidate

    def _score_block_context(self, root: Page | Frame | Locator) -> int:
        signals = self._collect_block_signals(root)
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
        if not isinstance(root, Locator):
            frame_url = self._normalize_text((getattr(root, "url", "") or "").strip())
            if "paripe.io/imhere-light" in frame_url:
                score += 6
            elif "imhere" in frame_url:
                score += 3
        return score

    def _find_any_live_flow_modal(self, page: Page) -> Locator | None:
        best_modal: Locator | None = None
        best_score = 0
        for selector in self._selectors.modal_roots:
            roots = page.locator(selector)
            try:
                count = roots.count()
            except Exception:
                continue
            for index in range(count):
                candidate = roots.nth(index)
                if not self._is_visible(candidate):
                    continue
                score = self._score_live_flow_context(candidate)
                if score > best_score:
                    best_score = score
                    best_modal = candidate
        return best_modal

    def _find_any_live_flow_frame(self, page: Page) -> Frame | None:
        best_frame: Frame | None = None
        best_score = 0
        for frame in page.frames:
            if frame == page.main_frame:
                continue
            score = self._score_live_flow_context(frame)
            if score > best_score:
                best_score = score
                best_frame = frame
        return best_frame

    def _score_live_flow_context(self, root: Page | Frame | Locator) -> int:
        score = 0
        selfie_signals = self._collect_selfie_return_signals(root)
        block_signals = self._collect_block_signals(root)
        score += sum(2 for enabled in block_signals.values() if enabled)
        score += sum(2 for enabled in selfie_signals.values() if enabled)
        normalized_text = self._normalized_root_text(root)
        if self._contains_any(normalized_text, self._selectors.no_block_texts):
            score += 2
        if isinstance(root, Locator):
            score -= 6
        else:
            frame_url = self._normalize_text((getattr(root, "url", "") or "").strip())
            if "paripe.io/imhere-light" in frame_url:
                score += 12
            elif "imhere" in frame_url:
                score += 8
        return score

    def _context_is_live(self, root: Page | Frame | Locator) -> bool:
        if isinstance(root, Locator):
            try:
                return root.is_visible()
            except Exception:
                return False
        try:
            _ = self._normalized_root_text(root)
            return True
        except Exception:
            return False

    def _root_is_iframe_flow(self, root: Page | Frame | Locator) -> bool:
        if isinstance(root, Locator):
            return False
        frame_url = self._normalize_text((getattr(root, "url", "") or "").strip())
        return "paripe.io/imhere-light" in frame_url or "imhere" in frame_url

    def _describe_live_flow_context(self, root: Page | Frame | Locator) -> str:
        if isinstance(root, Locator):
            return "modal/dom principal"
        frame_url = (getattr(root, "url", "") or "").strip()
        frame_title = self._frame_title(root)
        return f"iframe {frame_title or '-'} {frame_url or '-'}".strip()

    def _collect_selfie_return_signals(self, root: Page | Frame | Locator) -> dict[str, bool]:
        normalized_text = self._normalized_root_text(root)
        return {
            "file_input": self._count_selectors(root, ("input[type='file']", "input[accept*='image']")) > 0,
            "user_avatar": self._count_selectors(root, ("#user_avatar", 'input[id="user_avatar"]')) > 0,
            "continue_button": self._count_continue_buttons(root) > 0,
            "selfie_text": self._contains_any(normalized_text, self._selectors.selfie_instruction_texts),
            "account_options": self._contains_any(normalized_text, self._selectors.account_markers),
            "selfie_form": self._has_any_selector_now(root, self._selectors.selfie_form_selectors),
        }

    def _collect_processing_signals(self, root: Page | Frame | Locator) -> dict[str, bool]:
        normalized_text = self._normalized_root_text(root)
        return {
            "processing_text": self._contains_any(normalized_text, self._selectors.processing_texts),
            "processing_ui": self._has_any_selector_now(root, self._selectors.processing_selectors),
        }

    def _processing_phase_visible(self, root: Page | Frame | Locator) -> bool:
        if self._selfie_phase_visible(root):
            return False
        if self._has_strong_block_signal_raw(root):
            return False
        signals = self._collect_processing_signals(root)
        return any(signals.values())

    def _collect_block_signals(self, root: Page | Frame | Locator) -> dict[str, bool]:
        normalized_text = self._normalized_root_text(root)
        return {
            "price_or_payment": any(token in normalized_text for token in ("precio", "price", "valor", "monto", "pago")),
            "station": any(token in normalized_text for token in ("estacion", "station", "estacao", "punto", "point")),
            "schedule": any(token in normalized_text for token in ("hora", "time", "horario", "fecha", "schedule", "slot")),
            "duration": any(token in normalized_text for token in ("duracion", "duration", "horas", "hours")),
            "block_card": self._count_definition_terms(root) > 0,
            "final_button": self._count_final_submit_buttons(root) > 0,
        }

    def _has_strong_block_signal(self, root: Page | Frame | Locator) -> bool:
        return self._has_strong_block_signal_raw(root)

    def _has_strong_block_signal_raw(self, root: Page | Frame | Locator) -> bool:
        signals = self._collect_block_signals(root)
        primary_count = sum(
            1
            for key in ("price_or_payment", "station", "duration")
            if signals.get(key, False)
        )
        supporting_count = sum(
            1
            for key in ("schedule", "block_card", "final_button")
            if signals.get(key, False)
        )
        if primary_count >= 2:
            return True
        if signals.get("block_card", False) and primary_count >= 1 and supporting_count >= 2:
            return True
        return False

    def _processing_phase_visible_guard(self, root: Page | Frame | Locator) -> bool:
        signals = self._collect_processing_signals(root)
        return any(signals.values()) and not self._selfie_phase_visible(root)

    def _selfie_signal_diagnostics(self, root: Page | Frame | Locator) -> dict[str, int | bool]:
        return {
            "file_inputs": self._count_selectors(root, ("input[type='file']", "input[accept*='image']")),
            "user_avatar": self._count_selectors(root, ("#user_avatar", 'input[id="user_avatar"]')) > 0,
            "continue_buttons": self._count_continue_buttons(root),
        }

    @staticmethod
    def _format_active_signals(signals: dict[str, bool]) -> str:
        active = [name for name, enabled in signals.items() if enabled]
        return ", ".join(active) if active else "sin senales activas"

    def _count_selectors(self, root: Page | Frame | Locator, selectors: tuple[str, ...]) -> int:
        total = 0
        for selector in selectors:
            try:
                total += root.locator(selector).count()
            except Exception:
                continue
        return total

    def _count_continue_buttons(self, root: Page | Frame | Locator) -> int:
        total = 0
        for text in self._selectors.continue_texts:
            for selector in (f'button:has-text("{text}")', f'[role="button"]:has-text("{text}")'):
                try:
                    total += root.locator(selector).count()
                except Exception:
                    continue
        return total

    @staticmethod
    def _retry_limit_reached(attempt: int, max_selfie_retries: int) -> bool:
        return max_selfie_retries > 0 and attempt >= max_selfie_retries

    @staticmethod
    def _format_retry_attempt_label(attempt: int, max_selfie_retries: int) -> str:
        if max_selfie_retries > 0:
            return f"{attempt} de {max_selfie_retries}"
        return f"{attempt} (sin limite)"

    def _read_block_data(self, root: Page | Frame | Locator, *, page: Page) -> tuple[str, str, str, str]:
        full_text = self._safe_root_text(root)
        pairs = self._extract_block_pairs(root, full_text=full_text)
        station_name = self._pick_detail_value(pairs, ("estacion", "station", "estacao", "punto", "point"))
        block_price = self._pick_detail_value(pairs, ("precio", "price", "valor", "monto", "pago"))
        block_time = self._read_schedule(root, page=page, pairs=pairs, full_text=full_text)
        duration = self._pick_detail_value(pairs, ("duracion", "duration", "horas", "hours"))
        missing_fields = [
            label
            for label, value in (
                ("estacion", station_name),
                ("precio", block_price),
                ("horario", block_time),
                ("duracion", duration),
            )
            if value == "N/A"
        ]
        if len(missing_fields) >= 3:
            raise Ready4DriveFlowError(
                "block_read",
                "Aparecio el bloque, pero no se pudieron extraer sus datos de forma confiable. "
                f"Campos faltantes: {', '.join(missing_fields)}.",
            )
        return station_name, block_price, block_time, duration

    def _submit_final(
        self,
        root: Page | Frame | Locator,
        *,
        page: Page,
        progress_callback: ProgressCallback | None,
        session=None,
        extension_assisted: bool = False,
    ) -> Page | Frame | Locator:
        last_error = "El boton final 'He llegado' fue detectado, pero no respondio despues de varios intentos."
        resolution_reported = False
        self._mark_phase_timing("final_click_started", source="_submit_final", url=page.url)
        for attempt in range(1, 4):
            current_root = self._resolve_block_context(page, root) or root
            final_button_count = self._count_final_submit_buttons(current_root)
            button = self._find_final_submit_button(current_root)
            if button is None:
                raise Ready4DriveFlowError("final_submit", "Se leyo el bloque, pero no aparecio el boton final REAL 'He llegado' dentro del contenedor final de ready4drive.com.")
            button_visible = self._is_visible(button)
            button_enabled = self._locator_is_enabled(button)
            self.emit_progress(
                progress_callback,
                phase="final_submit",
                message=(
                    f"Diagnostico boton final. Intento {attempt}. "
                    f"Candidatos='He llegado' en contexto final: {final_button_count}. "
                    f"Elegido visible={'si' if button_visible else 'no'}. "
                    f"habilitado={'si' if button_enabled else 'no'}."
                ),
            )
            try:
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
                self._wait_for_enabled(
                    button,
                    timeout_ms=2_000,
                    phase="final_submit",
                    error_message="El boton final 'He llegado' sigue visible pero aun no esta habilitado en ready4drive.com.",
                )
                if not resolution_reported:
                    self._record_engine_resolution(session, None, phase="final_submit_ready", source="polling tradicional", note="final_submit")
                    self.emit_progress(
                        progress_callback,
                        phase="final_submit",
                        message="final_submit_ready resuelto por polling tradicional",
                    )
                    resolution_reported = True
                iframe_root = self._resolve_iframe_final_context(page, current_root)
                baseline_signature = self._result_signature(iframe_root)
                self._click_locator_resilient(
                    button,
                    phase="final_submit",
                    error_message="El boton final 'He llegado' fue detectado, pero no respondio al click.",
                )
                validated_root = self._validate_final_submit_reaction(
                    iframe_root,
                    page=page,
                    baseline_signature=baseline_signature,
                    progress_callback=progress_callback,
                )
                self._mark_phase_timing("final_click_done", source=f"_submit_final_attempt_{attempt}", url=page.url)
                return validated_root
            except Ready4DriveFlowError as exc:
                last_error = exc.message
                self._wait_interval(page, self._POLL_MS)
        raise Ready4DriveFlowError("final_submit", last_error)

    def _validate_final_submit_reaction(
        self,
        root: Page | Frame | Locator,
        *,
        page: Page,
        baseline_signature: str,
        progress_callback: ProgressCallback | None,
    ) -> Page | Frame | Locator:
        deadline = monotonic() + 5.0
        while monotonic() < deadline:
            current_root = self._resolve_iframe_final_context(page, root)
            reaction = self._collect_final_iframe_state(current_root, baseline_signature=baseline_signature)
            self.emit_progress(
                progress_callback,
                phase="final_submit",
                message=(
                    "Validando reaccion del click final. "
                    f"modal_bloque_abierto={'si' if reaction['modal_still_open'] else 'no'}. "
                    f"boton_presente={'si' if reaction['button_present'] else 'no'}. "
                    f"boton_habilitado={'si' if reaction['button_enabled'] else 'no'}. "
                    f"cambio_dom={'si' if reaction['signature_changed'] else 'no'}. "
                    f"senal_iframe={reaction['signal'] or 'ninguna'}."
                ),
            )
            if reaction["signal"] == "success_text":
                return current_root
            if reaction["signal"] in {"button_missing", "button_disabled", "block_replaced"}:
                return current_root
            self._wait_interval(page, self._POLL_MS)
        raise Ready4DriveFlowError(
            "final_submit",
            "El boton final 'He llegado' fue presionado, pero el modal final no cambio de estado de forma valida. El boton sigue visible o habilitado sin reaccion confirmable.",
        )

    def _detect_final_result(
        self,
        root: Page | Frame | Locator,
        *,
        page: Page,
        timeout_ms: int,
        station_name: str,
        block_price: str,
        block_time: str,
        block_duration: str,
        selfie_retry_count: int,
        deepfakescore_activated: bool,
        reserved_photo: ReservedPhoto,
        progress_callback: ProgressCallback | None,
        session=None,
        extension_assisted: bool = False,
    ) -> SiteExecutionResult:
        deadline = monotonic() + (timeout_ms / 1000)
        iframe_root = self._resolve_iframe_final_context(page, root)
        baseline_signature = self._result_signature(iframe_root)
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
                        "Proceso completado correctamente en ready4drive.com. "
                        f"Precio: {block_price}. Estacion: {station_name}. "
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
                    reserved_photo_id=reserved_photo.photo_id,
                )
            current_root = self._resolve_iframe_final_context(page, iframe_root)
            root_text = self._normalized_root_text(current_root)
            reaction = self._collect_final_iframe_state(current_root, baseline_signature=baseline_signature)
            if reaction["signal"] == "success_text":
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
                self.emit_progress(progress_callback, phase="final_result", message="Resultado final detectado en iframe.")
                return SiteExecutionResult(
                    success=True,
                    message=(
                        "Proceso completado correctamente en ready4drive.com. "
                        f"Precio: {block_price}. Estacion: {station_name}. "
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
                    reserved_photo_id=reserved_photo.photo_id,
                )
            if self._contains_any(root_text, self._selectors.final_failure_texts):
                raise Ready4DriveFlowError(
                    "final_result",
                    "Se presiono el boton final, pero ready4drive.com devolvio un error dentro del mismo iframe antes del resultado final.",
                )
            self.emit_progress(
                progress_callback,
                phase="final_result",
                message=(
                    "Diagnostico final_result en iframe. "
                    f"modal_bloque_abierto={'si' if reaction['modal_still_open'] else 'no'}. "
                    f"boton_final_presente={'si' if reaction['button_present'] else 'no'}. "
                    f"boton_final_habilitado={'si' if reaction['button_enabled'] else 'no'}. "
                    f"cambio_dom={'si' if reaction['signature_changed'] else 'no'}. "
                    f"senal_iframe={reaction['signal'] or 'ninguna'}."
                ),
            )
            if reaction["signal"] in {"button_missing", "button_disabled", "block_replaced"}:
                if inferred_success_since is None:
                    inferred_success_since = monotonic()
                    self.emit_progress(progress_callback, phase="final_result", message=f"Cambio final detectado dentro del iframe. Senal usada: {reaction['signal']}. Verificando resultado final...")
                elif monotonic() - inferred_success_since >= 1.5:
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
                    self.emit_progress(progress_callback, phase="final_result", message="Resultado final detectado en iframe.")
                    return SiteExecutionResult(
                        success=True,
                        message=(
                            "Proceso completado correctamente en ready4drive.com. "
                            f"Precio: {block_price}. Estacion: {station_name}. "
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
                        reserved_photo_id=reserved_photo.photo_id,
                    )
            else:
                inferred_success_since = None
            self._wait_interval(page, self._POLL_MS)
        raise Ready4DriveFlowError(
            "final_result",
            "Se presiono el boton final 'He llegado', pero no aparecio una confirmacion positiva dentro del timeout esperado.",
            final_status="timeout",
        )

    def _collect_final_iframe_state(
        self,
        root: Page | Frame | Locator,
        *,
        baseline_signature: str,
    ) -> dict[str, bool | str | None]:
        root_text = self._normalized_root_text(root)
        final_button = self._find_final_submit_button(root)
        button_present = final_button is not None
        button_enabled = final_button is not None and self._locator_is_enabled(final_button)
        modal_still_open = self._has_strong_block_signal(root) and self._root_looks_like_block(root_text, root)
        signature_changed = self._result_signature(root) != baseline_signature
        signal: str | None = None
        if self._contains_any(root_text, self._selectors.final_success_texts):
            signal = "success_text"
        elif signature_changed and not button_present:
            signal = "button_missing"
        elif signature_changed and button_present and not button_enabled:
            signal = "button_disabled"
        elif signature_changed and not modal_still_open:
            signal = "block_replaced"
        return {
            "button_present": button_present,
            "button_enabled": button_enabled,
            "modal_still_open": modal_still_open,
            "signature_changed": signature_changed,
            "signal": signal,
        }

    def _resolve_iframe_final_context(self, page: Page, previous_root: Page | Frame | Locator) -> Page | Frame | Locator:
        if self._root_is_iframe_flow(previous_root) and self._context_is_live(previous_root):
            return previous_root
        iframe_root = self._find_any_live_flow_frame(page)
        if iframe_root is not None:
            return iframe_root
        return previous_root

    def _has_any_action_card_now(self, page: Page) -> bool:
        candidates = self._action_card_candidates(page)
        count = candidates.count()
        for index in range(count):
            locator = candidates.nth(index)
            if not self._is_visible(locator):
                continue
            text = self._candidate_text(locator)
            if any(self._score_action_match(text, spec) > 0 for spec in self._get_supported_action_specs()):
                return True
        return False

    def _is_login_form_ready(self, page: Page) -> bool:
        return self._try_first_locator(page, self._selectors.login_phone, timeout_ms=250) is not None and self._try_first_locator(page, self._selectors.login_password, timeout_ms=250) is not None

    def _is_login_submit_available(self, page: Page) -> bool:
        submit = self._find_login_submit(page)
        if submit is None:
            return False
        try:
            disabled = submit.get_attribute("disabled")
            aria_disabled = submit.get_attribute("aria-disabled")
            return disabled is None and aria_disabled not in {"true", "True"}
        except Exception:
            return False

    def _action_card_candidates(self, page: Page) -> Locator:
        return page.locator(", ".join(self._selectors.action_card_candidates))

    def _first_locator(self, root: Page | Frame | Locator, selectors: tuple[str, ...], *, timeout_ms: int = 2_000) -> Locator:
        last_error: Exception | None = None
        for selector in selectors:
            locator = root.locator(selector).first
            try:
                locator.wait_for(state="visible", timeout=timeout_ms)
                return locator
            except Exception as exc:
                last_error = exc
        raise RuntimeError("Ningun selector coincidio. Ajuste manual requerido para ready4drive.com.") from last_error

    def _try_first_locator(self, root: Page | Frame | Locator, selectors: tuple[str, ...], *, timeout_ms: int = 700) -> Locator | None:
        for selector in selectors:
            locator = root.locator(selector).first
            try:
                locator.wait_for(state="visible", timeout=timeout_ms)
                return locator
            except Exception:
                continue
        return None

    def _find_photo_input(self, root: Page | Frame | Locator, *, timeout_ms: int) -> Locator | None:
        deadline = monotonic() + (timeout_ms / 1000)
        while monotonic() < deadline:
            for selector in self._selectors.photo_inputs:
                locator = root.locator(selector).first
                try:
                    locator.wait_for(state="attached", timeout=250)
                    return locator
                except Exception:
                    continue
            self._wait_interval(root, self._POLL_MS)
        return None

    def _fill_first(self, root: Page | Frame | Locator, selectors: tuple[str, ...], value: str) -> None:
        self._first_locator(root, selectors).fill(value)

    def _click_first(self, root: Page | Frame | Locator, selectors: tuple[str, ...]) -> None:
        self._first_locator(root, selectors).click()

    def _wait_for_enabled(self, locator: Locator, *, timeout_ms: int, phase: str, error_message: str) -> None:
        deadline = monotonic() + (timeout_ms / 1000)
        while monotonic() < deadline:
            try:
                disabled = locator.get_attribute("disabled")
                aria_disabled = locator.get_attribute("aria-disabled")
                if disabled is None and aria_disabled not in {"true", "True"}:
                    return
            except Exception:
                return
            self._wait_interval(locator, self._POLL_MS)
        raise Ready4DriveFlowError(phase, error_message)

    def _click_locator_resilient(self, locator: Locator, *, phase: str, error_message: str) -> None:
        try:
            locator.wait_for(state="visible", timeout=1_000)
            locator.scroll_into_view_if_needed(timeout=1_000)
        except Exception:
            pass
        try:
            locator.click(timeout=1_500)
            return
        except Exception:
            pass
        try:
            locator.click(timeout=1_500, force=True)
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
            raise Ready4DriveFlowError(phase, error_message) from exc

    def _click_by_text_variants(self, root: Page | Frame | Locator, texts: tuple[str, ...]) -> bool:
        for selector in self._selectors_for_texts(texts):
            locator = root.locator(selector).first
            try:
                locator.wait_for(state="visible", timeout=500)
                self._click_locator_resilient(
                    locator,
                    phase="text_click",
                    error_message=f"No se pudo presionar un control equivalente a: {', '.join(texts)}.",
                )
                return True
            except Exception:
                continue
        return self._click_best_text_candidate(root, texts)

    def _selectors_for_texts(self, texts: tuple[str, ...]) -> tuple[str, ...]:
        selectors: list[str] = []
        for text in texts:
            selectors.extend((f'button:has-text("{text}")', f'[role="button"]:has-text("{text}")', f'[role="radio"]:has-text("{text}")', f'label:has-text("{text}")', f'div:has-text("{text}")', f'text="{text}"'))
        return tuple(selectors)

    def _find_best_text_candidate(self, root: Page | Frame | Locator, texts: tuple[str, ...]) -> Locator | None:
        candidates = root.locator("button, [role='button'], [role='radio'], [role='option'], label, div")
        count = candidates.count()
        normalized_targets = tuple(self._normalize_text(text) for text in texts)
        best_locator: Locator | None = None
        best_score = 0
        for index in range(count):
            locator = candidates.nth(index)
            if not self._locator_is_clickable_candidate(locator):
                continue
            text = self._candidate_text(locator)
            score = 0
            for target in normalized_targets:
                if text == target:
                    score = max(score, 100)
                elif target and target in text:
                    score = max(score, 75)
            if score > best_score:
                best_score = score
                best_locator = locator
        return best_locator if best_score > 0 else None

    def _click_best_text_candidate(self, root: Page | Frame | Locator, texts: tuple[str, ...]) -> bool:
        best_locator = self._find_best_text_candidate(root, texts)
        if best_locator is None:
            return False
        best_locator.click()
        return True

    def _find_borrowed_account_title(self, root: Page | Frame | Locator) -> Locator | None:
        candidates = self._borrowed_account_text_candidates(root)
        for locator in candidates:
            try:
                locator.wait_for(state="visible", timeout=500)
                if self._borrowed_account_subtitle_matches(locator):
                    return locator
                return locator
            except Exception:
                continue
        return None

    def _require_borrowed_account_title(self, root: Page | Frame | Locator) -> Locator:
        borrowed_title = self._find_borrowed_account_title(root)
        if borrowed_title is None:
            frame_debug = self._frame_debug_summary(root)
            raise Ready4DriveFlowError(
                "account_select",
                "No se encontro el texto real de 'Cuenta prestada' dentro del frame correcto. "
                f"{frame_debug}",
            )
        return borrowed_title

    def _ensure_borrowed_account_default(self, root: Page | Frame | Locator) -> None:
        borrowed_title = self._require_borrowed_account_title(root)
        borrowed_container = self._find_borrowed_account_card(borrowed_title)
        if borrowed_container is None:
            raise Ready4DriveFlowError("account_select", "Se encontro 'Cuenta prestada', pero no su contenedor principal para validar el estado por defecto.")
        borrowed_control = self._find_borrowed_account_control(root, borrowed_container, borrowed_title)
        if borrowed_control is None:
            raise Ready4DriveFlowError("account_select", "Se encontro 'Cuenta prestada', pero no el control real para validar que quede activa por defecto.")
        own_title = self._find_best_text_candidate(root, self._selectors.own_account_texts)
        own_container = self._find_borrowed_account_card(own_title) if own_title is not None else None
        own_control = self._find_own_account_control(root, own_container, own_title)
        if self._wait_for_borrowed_account_selected(
            root,
            borrowed_container,
            borrowed_control=borrowed_control,
            own_container=own_container,
            own_control=own_control,
            timeout_ms=900,
        ):
            return
        raise Ready4DriveFlowError(
            "account_select",
            "El sitio no llego con 'Cuenta prestada' seleccionada por defecto. "
            f"Borrowed={self._selection_state_summary(borrowed_container, borrowed_control)} | "
            f"Own={self._selection_state_summary(own_container, own_control)}",
        )

    def _borrowed_account_text_candidates(self, root: Page | Frame | Locator) -> list[Locator]:
        candidates: list[Locator] = []
        for text in self._selectors.borrowed_account_texts:
            candidates.extend(
                (
                    root.get_by_text(text, exact=True).first,
                    root.locator(f"text={text}").first,
                    root.locator(f"span:has-text('{text}')").first,
                    root.locator(f"*").filter(has_text=text).first,
                )
            )
        return candidates

    def _borrowed_account_subtitle_matches(self, title_locator: Locator) -> bool:
        try:
            parent_stack = title_locator.locator("xpath=ancestor::span[contains(@class, 'flex')][1]").first
            parent_stack.wait_for(state="attached", timeout=300)
        except Exception:
            return False
        normalized_text = self._normalized_locator_text(parent_stack)
        return self._contains_any(normalized_text, self._selectors.borrowed_account_subtitles)

    def _find_clickable_container_from_title(self, title_locator: Locator) -> Locator | None:
        candidate_xpaths = (
            "xpath=ancestor::*[@role='button'][1]",
            "xpath=ancestor::button[1]",
            "xpath=ancestor::label[1]",
            "xpath=ancestor::*[@tabindex][1]",
            "xpath=ancestor::*[contains(@class, 'cursor-pointer')][1]",
            "xpath=ancestor::*[contains(@class, 'rounded')][1]",
            "xpath=ancestor::div[1]",
        )
        for xpath in candidate_xpaths:
            try:
                candidate = title_locator.locator(xpath).first
                candidate.wait_for(state="visible", timeout=300)
                candidate_text = self._normalized_locator_text(candidate)
                if self._contains_any(candidate_text, self._selectors.borrowed_account_texts):
                    return candidate
            except Exception:
                continue
        return None

    def _require_photo_input(self, root: Page | Frame | Locator, *, timeout_ms: int) -> Locator:
        file_input = self._find_photo_input(root, timeout_ms=min(timeout_ms, 4_000))
        if file_input is None:
            raise Ready4DriveFlowError("photo_upload", "No se encontro el input file real dentro del frame correcto.")
        return file_input

    def _require_continue_button(self, root: Page | Frame | Locator) -> Locator:
        continue_button = self._find_best_text_candidate(root, self._selectors.continue_texts)
        if continue_button is None:
            raise Ready4DriveFlowError("modal_continue", "No se pudo localizar el boton equivalente a 'Continuar' dentro del frame correcto.")
        return continue_button

    def _wait_for_any_text(self, root: Page | Frame | Locator, texts: tuple[str, ...], timeout_ms: int) -> bool:
        deadline = monotonic() + (timeout_ms / 1000)
        while monotonic() < deadline:
            if self._has_any_text_now(root, texts):
                return True
            self._wait_interval(root, self._POLL_MS)
        return False

    def _has_any_text_now(self, root: Page | Frame | Locator, texts: tuple[str, ...]) -> bool:
        return self._contains_any(self._normalized_root_text(root), texts)

    def _has_any_selector_now(self, root: Page | Frame | Locator, selectors: tuple[str, ...]) -> bool:
        for selector in selectors:
            try:
                if root.locator(selector).first.is_visible():
                    return True
            except Exception:
                continue
        return False

    def _score_action_match(self, normalized_text: str, action_spec: Ready4DriveActionSpec) -> int:
        if not normalized_text:
            return 0
        if any(token in normalized_text for token in action_spec.forbidden_tokens):
            return 0
        score = 0
        for phrase in action_spec.phrases:
            normalized_phrase = self._normalize_text(phrase)
            if normalized_text == normalized_phrase:
                score = max(score, 100)
            elif normalized_phrase in normalized_text:
                score = max(score, 90)
        groups_matched = 0
        for group in action_spec.required_token_groups:
            normalized_group = tuple(self._normalize_text(token) for token in group)
            if any(token in normalized_text for token in normalized_group):
                groups_matched += 1
        if groups_matched == len(action_spec.required_token_groups):
            score = max(score, 80)
        return score

    def _candidate_text(self, locator: Locator) -> str:
        parts = [self._normalized_locator_text(locator)]
        for attribute in ("aria-label", "title", "alt", "data-testid"):
            try:
                value = locator.get_attribute(attribute)
            except Exception:
                value = None
            if value:
                parts.append(self._normalize_text(value))
        return " ".join(part for part in parts if part).strip()

    def _wait_for_borrowed_account_selected(self, root: Page | Frame | Locator, locator: Locator, *, borrowed_control: Locator | None = None, timeout_ms: int) -> bool:
        deadline = monotonic() + (timeout_ms / 1000)
        while monotonic() < deadline:
            if borrowed_control is not None and self._locator_looks_selected(borrowed_control):
                return True
            if self._locator_looks_selected(locator):
                return True
            own_option = self._find_best_text_candidate(root, self._selectors.own_account_texts)
            if own_option is not None and self._locator_looks_unselected(own_option):
                if borrowed_control is not None and self._locator_looks_selected(borrowed_control):
                    return True
                if self._locator_looks_selected(locator):
                    return True
            if borrowed_control is not None and self._locator_has_check_marker(locator, borrowed_control):
                return True
            if self._has_any_selector_now(root, self._selectors.photo_inputs):
                return True
            self._wait_interval(root, self._POLL_MS)
        return False

    def _locator_has_check_marker(self, container: Locator, control: Locator) -> bool:
        if self._locator_looks_selected(control):
            return True
        try:
            classes = (container.get_attribute("class") or "").lower()
        except Exception:
            classes = ""
        if any(token in classes for token in ("ring", "border-", "outline", "selected", "active", "checked")):
            return True
        try:
            if container.locator("svg, [data-state='checked'], [aria-hidden='false']").count() > 0 and self._locator_looks_selected(control):
                return True
        except Exception:
            pass
        return False

    def _press_borrowed_account(self, root: Page | Frame | Locator, *, borrowed_title: Locator | None = None) -> None:
        borrowed_title = borrowed_title or self._require_borrowed_account_title(root)
        borrowed_container = self._find_borrowed_account_card(borrowed_title)
        if borrowed_container is None:
            raise Ready4DriveFlowError("account_select", "Se encontro 'Cuenta prestada', pero no se pudo resolver su contenedor clickable padre.")
        borrowed_control = self._find_borrowed_account_control(borrowed_container, borrowed_title)
        if borrowed_control is None:
            raise Ready4DriveFlowError("account_select", "Se encontro la tarjeta de 'Cuenta prestada', pero no el control real asociado de seleccion.")
        own_title = self._find_best_text_candidate(root, self._selectors.own_account_texts)
        own_container = self._find_borrowed_account_card(own_title) if own_title is not None else None
        own_control = self._find_borrowed_account_control(own_container, own_title) if own_container is not None and own_title is not None else None
        if self._wait_for_borrowed_account_selected(
            root,
            borrowed_container,
            borrowed_control=borrowed_control,
            own_container=own_container,
            own_control=own_control,
            timeout_ms=700,
        ):
            return
        selection_error = self._select_borrowed_account_control(
            root,
            borrowed_container=borrowed_container,
            borrowed_control=borrowed_control,
            own_container=own_container,
            own_control=own_control,
        )
        if selection_error is None:
            return
        raise Ready4DriveFlowError("account_select", selection_error)

    def _select_borrowed_account_control(
        self,
        root: Page | Frame | Locator,
        *,
        borrowed_container: Locator,
        borrowed_control: Locator,
        own_container: Locator | None,
        own_control: Locator | None,
    ) -> str | None:
        attempts = (
            ("contenedor clickable", borrowed_container, "click"),
            ("label asociado", self._try_locator(borrowed_container, "xpath=ancestor-or-self::label[1]"), "click"),
            ("control real", borrowed_control, "click"),
            ("control real", borrowed_control, "set_checked"),
            ("control real", borrowed_control, "press"),
            ("control real", borrowed_control, "force"),
        )
        last_error = "Se encontro el control real de 'Cuenta prestada', pero no cambio su estado."
        for target_name, candidate, mode in attempts:
            if candidate is None:
                continue
            failure = self._activate_selection_target(candidate, mode=mode, target_name=target_name)
            if failure is not None:
                last_error = failure
                continue
            if self._wait_for_borrowed_account_selected(
                root,
                borrowed_container,
                borrowed_control=borrowed_control,
                own_container=own_container,
                own_control=own_control,
                timeout_ms=1_200,
            ):
                return None
            last_error = (
                "Se encontro el control real de 'Cuenta prestada', pero no cambio su estado. "
                f"Borrowed={self._selection_state_summary(borrowed_container, borrowed_control)} | "
                f"Own={self._selection_state_summary(own_container, own_control)}"
            )
        return last_error

    def _activate_selection_target(self, locator: Locator, *, mode: str, target_name: str) -> str | None:
        try:
            locator.scroll_into_view_if_needed(timeout=700)
        except Exception:
            pass
        try:
            if mode == "click":
                locator.click(timeout=1_000)
                return None
            if mode == "hover_click":
                locator.hover(timeout=700)
                locator.click(timeout=1_000)
                return None
            if mode == "force":
                locator.click(timeout=1_000, force=True)
                return None
            if mode == "press":
                locator.press("Space")
                return None
            if mode == "set_checked":
                control_type = (locator.get_attribute("type") or "").strip().lower()
                role = (locator.get_attribute("role") or "").strip().lower()
                if control_type not in {"radio", "checkbox"} and role != "radio":
                    return f"Se encontro el control real, pero no admite set/check programatico ({target_name})."
                locator.set_checked(True, timeout=1_000)
                return None
        except Exception as exc:
            message = str(exc).lower()
            if "intercept" in message:
                return f"El click fue interceptado al intentar activar {target_name} de 'Cuenta prestada'."
            return f"No se pudo activar {target_name} de 'Cuenta prestada': {exc}"
        return f"No se pudo activar {target_name} de 'Cuenta prestada'."

    def _wait_for_borrowed_account_selected(
        self,
        root: Page | Frame | Locator,
        locator: Locator,
        *,
        borrowed_control: Locator | None = None,
        own_container: Locator | None = None,
        own_control: Locator | None = None,
        timeout_ms: int,
    ) -> bool:
        deadline = monotonic() + (timeout_ms / 1000)
        while monotonic() < deadline:
            borrowed_selected = False
            if borrowed_control is not None and self._locator_looks_selected(borrowed_control):
                borrowed_selected = True
            elif self._locator_looks_selected(locator):
                borrowed_selected = True
            own_unselected = True
            if own_control is not None:
                own_unselected = self._locator_looks_unselected(own_control)
            elif own_container is not None:
                own_unselected = self._locator_looks_unselected(own_container)
            if borrowed_selected and own_unselected:
                return True
            if borrowed_selected and own_control is None and own_container is None:
                return True
            self._wait_interval(root, self._POLL_MS)
        return False

    def _selection_state_summary(self, container: Locator | None, control: Locator | None) -> str:
        parts: list[str] = []
        if control is not None:
            parts.append(f"control={self._selection_signal_snapshot(control)}")
        if container is not None:
            parts.append(f"container={self._selection_signal_snapshot(container)}")
        return " | ".join(parts) if parts else "sin estado visible"

    def _selection_signal_snapshot(self, locator: Locator) -> str:
        values: list[str] = []
        try:
            values.append(f"type={(locator.get_attribute('type') or '').strip().lower() or '-'}")
        except Exception:
            pass
        for attribute in ("role", "aria-checked", "aria-selected", "data-state", "data-checked", "checked"):
            try:
                values.append(f"{attribute}={(locator.get_attribute(attribute) or '').strip().lower() or '-'}")
            except Exception:
                continue
        try:
            values.append(f"checked={locator.is_checked()}")
        except Exception:
            pass
        try:
            classes = (locator.get_attribute('class') or '').strip().lower()
            values.append(f"class={classes[:120] or '-'}")
        except Exception:
            pass
        return ", ".join(values)

    def _safe_get_attribute(self, locator: Locator, name: str) -> str | None:
        try:
            value = locator.get_attribute(name)
        except Exception:
            return None
        return value

    def _safe_locator_html(self, locator: Locator) -> str:
        try:
            return locator.evaluate("node => node.outerHTML || ''")
        except Exception:
            return ""

    def _wait_for_uploaded_photo(self, root: Page | Frame | Locator, locator: Locator, *, reserved_photo: ReservedPhoto, timeout_ms: int) -> bool:
        deadline = monotonic() + (timeout_ms / 1000)
        filename_marker = self._normalize_text(reserved_photo.original_filename)
        while monotonic() < deadline:
            if self._locator_has_uploaded_file(locator):
                return True
            normalized_text = self._normalized_root_text(root)
            if filename_marker and filename_marker in normalized_text:
                return True
            if self._find_best_text_candidate(root, self._selectors.continue_texts) is not None:
                return True
            self._wait_interval(root, self._POLL_MS)
        return False

    def _wait_for_post_continue_change(self, root: Page | Frame | Locator, locator: Locator, *, timeout_ms: int) -> bool:
        deadline = monotonic() + (timeout_ms / 1000)
        while monotonic() < deadline:
            if not self._is_visible(locator):
                return True
            if not self._has_any_selector_now(root, self._selectors.photo_inputs):
                return True
            if self._contains_any(self._normalized_root_text(root), self._selectors.processing_done_markers):
                return True
            self._wait_interval(root, self._POLL_MS)
        return False

    def _locator_looks_selected(self, locator: Locator) -> bool:
        try:
            if locator.is_checked():
                return True
        except Exception:
            pass
        for attribute in ("aria-checked", "aria-selected", "data-state", "data-checked", "checked"):
            try:
                value = (locator.get_attribute(attribute) or "").strip().lower()
            except Exception:
                value = ""
            if value in {"true", "checked", "selected", "active", "on"}:
                return True
        try:
            classes = (locator.get_attribute("class") or "").lower()
        except Exception:
            classes = ""
        return any(token in classes for token in ("selected", "checked", "active", "current"))

    def _locator_looks_unselected(self, locator: Locator) -> bool:
        try:
            if locator.is_checked():
                return False
        except Exception:
            pass
        for attribute in ("aria-checked", "aria-selected", "data-state", "data-checked", "checked"):
            try:
                value = (locator.get_attribute(attribute) or "").strip().lower()
            except Exception:
                value = ""
            if value in {"false", "unchecked", "off"}:
                return True
        try:
            classes = (locator.get_attribute("class") or "").lower()
        except Exception:
            classes = ""
        return not any(token in classes for token in ("selected", "checked", "active", "current"))

    def _press_borrowed_account(self, root: Page | Frame | Locator, *, borrowed_title: Locator | None = None) -> None:
        borrowed_title = borrowed_title or self._require_borrowed_account_title(root)
        borrowed_container = self._find_borrowed_account_card(borrowed_title)
        if borrowed_container is None:
            raise Ready4DriveFlowError("account_select", "Se encontro el texto de 'Cuenta prestada', pero no el contenedor clicable real.")
        radio_diagnostics = self._enumerate_account_radios(root)
        borrowed_control = self._find_borrowed_account_control(root, borrowed_container, borrowed_title)
        if borrowed_control is None:
            raise Ready4DriveFlowError(
                "account_select",
                "Se encontro el contenedor de 'Cuenta prestada', pero no el control real asociado. "
                f"Container={self._locator_debug_summary(borrowed_container)} | Radios={self._format_radio_diagnostics(radio_diagnostics)}",
            )
        own_title = self._find_best_text_candidate(root, self._selectors.own_account_texts)
        own_container = self._find_borrowed_account_card(own_title) if own_title is not None else None
        own_control = self._find_own_account_control(root, own_container, own_title)
        if self._wait_for_borrowed_account_selected(
            root,
            borrowed_container,
            borrowed_control=borrowed_control,
            own_container=own_container,
            own_control=own_control,
            timeout_ms=700,
        ):
            return
        error_message = self._select_borrowed_account_control(
            root,
            borrowed_container=borrowed_container,
            borrowed_control=borrowed_control,
            own_container=own_container,
            own_control=own_control,
        )
        if error_message is None:
            return
        raise Ready4DriveFlowError(
            "account_select",
            f"{error_message} | Radios={self._format_radio_diagnostics(radio_diagnostics)} | Clicked={self._locator_debug_summary(borrowed_control)}",
        )

    def _find_borrowed_account_card(self, title_locator: Locator | None) -> Locator | None:
        if title_locator is None:
            return None
        stack_locator = self._find_borrowed_account_stack(title_locator)
        candidate_xpaths = (
            "xpath=ancestor::*[@data-checked][1]",
            "xpath=ancestor::*[contains(@class, 'group')][1]",
            "xpath=ancestor::label[1]",
            "xpath=ancestor::*[@role='radio'][1]",
            "xpath=ancestor::*[@role='button'][1]",
            "xpath=ancestor::button[1]",
            "xpath=ancestor::*[@tabindex][1]",
            "xpath=ancestor::*[contains(@class, 'cursor-pointer')][1]",
            "xpath=ancestor::*[contains(@class, 'rounded')][1]",
            "xpath=ancestor::*[contains(@class, 'border')][1]",
            "xpath=ancestor::div[1]",
            "xpath=ancestor::div[2]",
            "xpath=ancestor::div[3]",
        )
        for base in (stack_locator, title_locator):
            for xpath in candidate_xpaths:
                try:
                    candidate = base.locator(xpath).first
                    candidate.wait_for(state="visible", timeout=250)
                    candidate_text = self._normalized_locator_text(candidate)
                    if not self._contains_any(candidate_text, self._selectors.borrowed_account_texts):
                        continue
                    if candidate.locator("span.pointer-events-none").count() > 0:
                        return candidate
                    if self._contains_any(candidate_text, self._selectors.borrowed_account_subtitles):
                        return candidate
                    if candidate.locator("input, [role='radio'], [aria-checked], [aria-selected], [data-checked]").count() > 0:
                        return candidate
                except Exception:
                    continue
        return self._find_clickable_container_from_title(title_locator)

    def _find_borrowed_account_stack(self, title_locator: Locator) -> Locator:
        for xpath in (
            "xpath=ancestor::span[contains(@class, 'flex') and contains(@class, 'flex-col')][1]",
            "xpath=ancestor::span[contains(@class, 'flex')][1]",
            "xpath=..",
        ):
            try:
                candidate = title_locator.locator(xpath).first
                candidate.wait_for(state="attached", timeout=200)
                return candidate
            except Exception:
                continue
        return title_locator

    def _find_borrowed_account_control(self, root: Page | Frame | Locator, card_locator: Locator | None, title_locator: Locator | None) -> Locator | None:
        if card_locator is None or title_locator is None:
            return None
        root_radio = self._find_account_radio(root, expected_kind="borrowed")
        if root_radio is not None:
            return root_radio
        control_selectors = (
            "input[type='radio']",
            "input[type='checkbox']",
            "[role='radio']",
            "[aria-checked]",
            "[aria-selected]",
            "[data-state]",
        )
        for root in (card_locator, self._find_borrowed_account_stack(title_locator), title_locator):
            for selector in control_selectors:
                try:
                    locator = root.locator(selector).first
                    locator.wait_for(state="attached", timeout=200)
                    return locator
                except Exception:
                    continue
        return self._find_associated_input_from_label(card_locator)

    def _find_own_account_control(self, root: Page | Frame | Locator, card_locator: Locator | None, title_locator: Locator | None) -> Locator | None:
        root_radio = self._find_account_radio(root, expected_kind="own")
        if root_radio is not None:
            return root_radio
        if card_locator is None or title_locator is None:
            return None
        for selector in ("[role='radio']", "input[type='radio']", "[aria-checked]"):
            try:
                locator = card_locator.locator(selector).first
                locator.wait_for(state="attached", timeout=200)
                return locator
            except Exception:
                continue
        return self._find_associated_input_from_label(card_locator)

    def _find_account_radio(self, root: Page | Frame | Locator, *, expected_kind: str) -> Locator | None:
        radios = root.locator("[role='radio']")
        count = radios.count()
        best_locator: Locator | None = None
        best_score = 0
        for index in range(count):
            locator = radios.nth(index)
            if not self._is_visible(locator):
                continue
            score = self._score_account_radio(locator, expected_kind=expected_kind)
            if score > best_score:
                best_score = score
                best_locator = locator
        return best_locator if best_score > 0 else None

    def _score_account_radio(self, locator: Locator, *, expected_kind: str) -> int:
        aria_label = self._normalize_text((self._safe_get_attribute(locator, "aria-label") or ""))
        control_text = self._candidate_text(locator)
        html = self._normalize_text(self._safe_locator_html(locator))
        combined = " ".join(part for part in (aria_label, control_text, html) if part)
        score = 0
        if expected_kind == "borrowed":
            if "borrowed-account" in combined:
                score += 200
            if "cuenta prestada" in combined or "borrowed account" in combined or "conta emprestada" in combined:
                score += 120
            if "own-account" in combined or "cuenta propia" in combined or "own account" in combined:
                score -= 220
        else:
            if "own-account" in combined:
                score += 200
            if "cuenta propia" in combined or "own account" in combined or "conta propria" in combined:
                score += 120
            if "borrowed-account" in combined or "cuenta prestada" in combined or "borrowed account" in combined:
                score -= 220
        return score

    def _enumerate_account_radios(self, root: Page | Frame | Locator) -> list[dict[str, str]]:
        items: list[dict[str, str]] = []
        radios = root.locator("[role='radio']")
        try:
            count = radios.count()
        except Exception:
            return items
        for index in range(count):
            locator = radios.nth(index)
            if not self._is_visible(locator):
                continue
            items.append(
                {
                    "index": str(index),
                    "aria_label": self._safe_get_attribute(locator, "aria-label") or "",
                    "aria_checked": self._safe_get_attribute(locator, "aria-checked") or "",
                    "id": self._safe_get_attribute(locator, "id") or "",
                    "text": self._candidate_text(locator)[:120],
                    "html": self._safe_locator_html(locator)[:180],
                }
            )
        return items

    def _format_radio_diagnostics(self, items: list[dict[str, str]]) -> str:
        if not items:
            return "sin radios role=radio visibles"
        parts: list[str] = []
        for item in items[:6]:
            parts.append(
                f"[{item['index']}] aria-label={item['aria_label'] or '-'} aria-checked={item['aria_checked'] or '-'} "
                f"id={item['id'] or '-'} text={item['text'] or '-'} html={item['html'] or '-'}"
            )
        return " || ".join(parts)

    def _select_borrowed_account_control(
        self,
        root: Page | Frame | Locator,
        *,
        borrowed_container: Locator,
        borrowed_control: Locator,
        own_container: Locator | None,
        own_control: Locator | None,
    ) -> str | None:
        attempts = (
            ("control real", borrowed_control, "click"),
            ("control real", borrowed_control, "hover_click"),
            ("contenedor clicable", borrowed_container, "click"),
            ("control real", borrowed_control, "click"),
            ("control real", borrowed_control, "set_checked"),
            ("control real", borrowed_control, "press"),
            ("control real", borrowed_control, "click"),
        )
        last_error = "Se encontro el control real de 'Cuenta prestada', pero aria-checked no cambio a true."
        for target_name, candidate, mode in attempts:
            if candidate is None:
                continue
            before_checked = self._read_aria_checked(borrowed_control)
            failure = self._activate_selection_target(candidate, mode=mode, target_name=target_name)
            if failure is not None:
                last_error = f"{failure} | aria-checked antes={before_checked or '-'}"
                continue
            self._wait_interval(root, 250)
            if self._wait_for_borrowed_account_selected(root, borrowed_container, borrowed_control=borrowed_control, own_container=own_container, own_control=own_control, timeout_ms=900):
                return None
            after_checked = self._read_aria_checked(borrowed_control)
            last_error = (
                "Se encontro el control real, pero no cambio aria-checked a true. "
                f"aria-checked antes={before_checked or '-'} | aria-checked despues={after_checked or '-'} | "
                f"Borrowed={self._selection_state_summary(borrowed_container, borrowed_control)} | "
                f"Own={self._selection_state_summary(own_container, own_control)} | "
                f"Container={self._locator_debug_summary(borrowed_container)}"
            )
        return last_error

    def _wait_for_borrowed_account_selected(
        self,
        root: Page | Frame | Locator,
        locator: Locator,
        *,
        borrowed_control: Locator | None = None,
        own_container: Locator | None = None,
        own_control: Locator | None = None,
        timeout_ms: int,
    ) -> bool:
        deadline = monotonic() + (timeout_ms / 1000)
        while monotonic() < deadline:
            borrowed_selected = borrowed_control is not None and self._read_aria_checked(borrowed_control) == "true"
            own_unselected = True
            if own_control is not None:
                own_unselected = self._read_aria_checked(own_control) in {"", "false", None}
            elif own_container is not None:
                own_unselected = self._locator_looks_unselected(own_container)
            if borrowed_selected and own_unselected:
                return True
            if borrowed_selected and own_control is None and own_container is None:
                return True
            self._wait_interval(root, self._POLL_MS)
        return False

    def _read_aria_checked(self, locator: Locator | None) -> str | None:
        if locator is None:
            return None
        try:
            value = (locator.get_attribute("aria-checked") or "").strip().lower()
        except Exception:
            return None
        return value or None

    def _locator_debug_summary(self, locator: Locator) -> str:
        parts: list[str] = []
        for attribute in ("tagName", "role", "class", "aria-checked", "aria-selected", "data-state", "data-checked"):
            try:
                if attribute == "tagName":
                    value = locator.evaluate("node => node.tagName.toLowerCase()")
                else:
                    value = locator.get_attribute(attribute)
            except Exception:
                value = None
            if value:
                parts.append(f"{attribute}={str(value)[:120]}")
        try:
            html = locator.evaluate("node => node.outerHTML.slice(0, 280)")
            if html:
                parts.append(f"html={html}")
        except Exception:
            pass
        return " | ".join(parts) if parts else "sin resumen html"

    def _frame_debug_summary(self, root: Page | Frame | Locator) -> str:
        if isinstance(root, Locator):
            return f"Contexto locator. {self._locator_debug_summary(root)}"
        match_count = self._count_borrowed_account_matches(root)
        snippets = ", ".join(self._visible_text_snippets(root, limit=6)) or "sin textos visibles"
        if isinstance(root, Page):
            return f"page_url={root.url} | cuenta_prestada_matches={match_count} | textos={snippets}"
        frame_url = (getattr(root, "url", "") or "").strip()
        frame_title = self._frame_title(root)
        return (
            f"frame_url={frame_url or '-'} | frame_title={frame_title or '-'} | "
            f"frame_accessible=True | cuenta_prestada_matches={match_count} | textos={snippets}"
        )

    def _count_borrowed_account_matches(self, root: Page | Frame | Locator) -> int:
        total = 0
        for text in self._selectors.borrowed_account_texts:
            for locator in (
                root.get_by_text(text, exact=True),
                root.locator(f"text={text}"),
                root.locator(f"span:has-text('{text}')"),
                root.locator("*").filter(has_text=text),
            ):
                try:
                    total = max(total, locator.count())
                except Exception:
                    continue
        return total

    def _visible_text_snippets(self, root: Page | Frame | Locator, *, limit: int) -> list[str]:
        if isinstance(root, Locator):
            normalized = self._normalized_locator_text(root)
            return [normalized] if normalized else []
        try:
            lines = root.locator("body").inner_text(timeout=600).splitlines()
        except Exception:
            return []
        snippets: list[str] = []
        for line in lines:
            compact = self._normalize_text(line)
            if compact:
                snippets.append(compact)
            if len(snippets) >= limit:
                break
        return snippets

    def _locator_has_uploaded_file(self, locator: Locator) -> bool:
        try:
            return bool(locator.evaluate("node => Boolean(node.files && node.files.length > 0)"))
        except Exception:
            return False

    def _normalized_root_text(self, root: Page | Frame | Locator) -> str:
        if isinstance(root, Locator):
            return self._normalized_locator_text(root)
        try:
            return self._normalize_text(root.locator("body").inner_text(timeout=400))
        except Exception:
            return ""

    def _safe_root_text(self, root: Page | Frame | Locator) -> str:
        if isinstance(root, Locator):
            try:
                return root.inner_text(timeout=400).strip()
            except Exception:
                return ""
        try:
            return root.locator("body").inner_text(timeout=400).strip()
        except Exception:
            return ""

    def _root_looks_like_block(self, normalized_text: str, root: Page | Frame | Locator) -> bool:
        if not normalized_text:
            return False
        signals = self._collect_block_signals(root)
        has_labels = any(token in normalized_text for token in ("estacion", "station", "estacao", "precio", "price", "valor", "horario", "hora", "duracion"))
        has_definition_pairs = self._count_definition_terms(root) > 0
        primary_count = sum(
            1
            for key in ("price_or_payment", "station", "duration")
            if signals.get(key, False)
        )
        supporting_count = sum(
            1
            for key in ("schedule", "block_card", "final_button")
            if signals.get(key, False)
        )
        if primary_count >= 2:
            return True
        if signals.get("block_card", False) and primary_count >= 1 and supporting_count >= 2:
            return True
        return has_labels and has_definition_pairs

    def _count_definition_terms(self, root: Page | Frame | Locator) -> int:
        try:
            return root.locator("dt").count()
        except Exception:
            return 0

    def _extract_block_pairs(self, root: Page | Frame | Locator, *, full_text: str) -> dict[str, str]:
        pairs = self._extract_definition_pairs(root)
        pairs.update(self._extract_text_pairs(full_text))
        return pairs

    def _extract_definition_pairs(self, root: Page | Frame | Locator) -> dict[str, str]:
        pairs: dict[str, str] = {}
        try:
            terms = root.locator("dt")
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

    def _extract_text_pairs(self, text: str) -> dict[str, str]:
        pairs: dict[str, str] = {}
        lines = [line.strip(" -:\t") for line in text.splitlines() if line.strip()]
        aliases = {
            "estacion": ("estacion", "station", "estacao", "punto", "point"),
            "precio": ("precio", "price", "valor", "monto", "pago"),
            "horario": ("horario", "hora", "time", "fecha", "schedule", "slot"),
            "duracion": ("duracion", "duration", "horas", "hours"),
        }
        for index, line in enumerate(lines):
            normalized_line = self._normalize_text(line)
            next_line = lines[index + 1] if index + 1 < len(lines) else ""
            if ":" in line:
                raw_label, raw_value = line.split(":", 1)
                normalized_line = self._normalize_text(raw_label)
                next_line = raw_value.strip()
            if not next_line:
                continue
            for canonical, variants in aliases.items():
                if canonical in pairs:
                    continue
                if any(self._normalize_text(variant) in normalized_line for variant in variants):
                    pairs[canonical] = next_line
                    break
        return pairs

    def _pick_detail_value(self, pairs: dict[str, str], aliases: tuple[str, ...]) -> str:
        for alias in aliases:
            if alias in pairs and pairs[alias]:
                return pairs[alias]
        for alias in aliases:
            normalized_alias = self._normalize_text(alias)
            for label, value in pairs.items():
                if normalized_alias in label and value:
                    return value
        return "N/A"

    def _read_schedule(
        self,
        root: Page | Frame | Locator,
        *,
        page: Page,
        pairs: dict[str, str],
        full_text: str,
    ) -> str:
        from_pairs = self._pick_detail_value(pairs, ("horario", "fecha", "hora", "time", "schedule", "slot"))
        if from_pairs != "N/A":
            return from_pairs
        for source in (root, page):
            try:
                texts = source.locator("p, span, div")
                count = min(texts.count(), 80)
            except Exception:
                count = 0
            for index in range(count):
                try:
                    text = texts.nth(index).inner_text(timeout=200).strip()
                except Exception:
                    continue
                normalized = self._normalize_text(text)
                if text and (":" in text or bool(re.search(r"\b\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?\b", text))) and not any(token in normalized for token in ("estacion", "station", "precio", "price")):
                    return text
        candidates = self._extract_schedule_candidates(full_text)
        return candidates[0] if candidates else "N/A"

    def _extract_schedule_candidates(self, text: str) -> list[str]:
        candidates: list[str] = []
        for line in [part.strip() for part in text.splitlines() if part.strip()]:
            normalized = self._normalize_text(line)
            has_time_signal = ":" in line or bool(re.search(r"\b(?:am|pm)\b", normalized))
            has_date_signal = bool(re.search(r"\b\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?\b", line))
            if has_time_signal or has_date_signal:
                candidates.append(line)
        return candidates

    def _find_final_submit_button(self, root: Page | Frame | Locator) -> Locator | None:
        candidates = root.locator("button, [role='button'], a")
        try:
            count = candidates.count()
        except Exception:
            return None
        best_button: Locator | None = None
        best_score = 0
        for index in range(count):
            button = candidates.nth(index)
            if not self._locator_is_clickable_candidate(button):
                continue
            text = self._candidate_text(button)
            score = 0
            if any(self._normalize_text(label) in text for label in self._selectors.final_submit_texts):
                score += 100
            if "continuar" in text or "continue" in text:
                score -= 80
            if score > best_score:
                best_score = score
                best_button = button
        return best_button if best_score > 0 else None

    def _count_final_submit_buttons(self, root: Page | Frame | Locator) -> int:
        candidates = root.locator("button, [role='button'], a")
        try:
            count = candidates.count()
        except Exception:
            return 0
        total = 0
        for index in range(count):
            button = candidates.nth(index)
            if not self._locator_is_clickable_candidate(button):
                continue
            text = self._candidate_text(button)
            score = 0
            if any(self._normalize_text(label) in text for label in self._selectors.final_submit_texts):
                score += 100
            if "continuar" in text or "continue" in text:
                score -= 80
            if score > 0:
                total += 1
        return total

    def _result_signature(self, root: Page | Frame | Locator) -> str:
        return self._normalized_root_text(root)[:800]


    def _normalized_locator_text(self, locator: Locator) -> str:
        try:
            raw_text = locator.inner_text(timeout=400)
        except Exception:
            return ""
        return self._normalize_text(raw_text)

    def _is_visible(self, locator: Locator) -> bool:
        try:
            return locator.is_visible()
        except Exception:
            return False

    def _locator_is_clickable_candidate(self, locator: Locator) -> bool:
        if not self._is_visible(locator):
            return False
        try:
            box = locator.bounding_box()
        except Exception:
            return True
        if box is None:
            return False
        return float(box.get("width") or 0) >= 2 and float(box.get("height") or 0) >= 2

    def _locator_is_enabled(self, locator: Locator) -> bool:
        try:
            return not locator.is_disabled()
        except Exception:
            return True

    @classmethod
    def _contains_any(cls, normalized_text: str, texts: tuple[str, ...]) -> bool:
        return any(cls._normalize_text(text) in normalized_text for text in texts)

    @staticmethod
    def _normalize_text(text: str) -> str:
        normalized = unicodedata.normalize("NFKD", text)
        ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
        compact = _WHITESPACE_RE.sub(" ", ascii_text).strip()
        return compact.lower()

    @staticmethod
    def _wait_interval(root: Page | Frame | Locator, milliseconds: int) -> None:
        if isinstance(root, Locator):
            root.page.wait_for_timeout(milliseconds)
        else:
            root.wait_for_timeout(milliseconds)

    def _read_labeled_value(self, roots: tuple[Page | Frame | Locator, ...], labels: tuple[str, ...]) -> str:
        for root in roots:
            for label in labels:
                containers = (root.locator(f'text="{label}"').first, root.locator(f'[aria-label*="{label}" i]').first)
                for container in containers:
                    try:
                        container.wait_for(state="visible", timeout=600)
                        text = container.locator("xpath=..").inner_text().strip()
                        if ":" in text:
                            return text.split(":", maxsplit=1)[1].strip() or "N/A"
                        return text or "N/A"
                    except Exception:
                        continue
        raise Ready4DriveFlowError("block_read", f"No se pudo leer el valor del bloque para etiquetas: {', '.join(labels)}")

    @staticmethod
    def _use_extension_engine(local_config: LocalConfig, request: ProcessExecutionRequest) -> bool:
        request_mode = (request.execution_mode or "").strip().lower()
        config_mode = (local_config.flow_engine or "").strip().lower()
        return local_config.enable_browser_extension and (request_mode == "extension" or config_mode == "extension")

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

