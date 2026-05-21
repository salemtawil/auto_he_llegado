from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import re
import unicodedata
from typing import Any


_WHITESPACE_RE = re.compile(r"\s+")
_TIME_RANGE_RE = re.compile(
    r"\b\d{1,2}:\d{2}\s*(?:am|pm)?\s*-\s*\d{1,2}:\d{2}\s*(?:am|pm)?\b",
    re.IGNORECASE,
)
_DURATION_RE = re.compile(r"\b\d+(?:[.,]\d+)?\s*(?:horas?|hours?|hrs?)\b", re.IGNORECASE)

_SELFIE_TEXTS = (
    "selfie",
    "foto",
    "photo",
    "tomate una foto",
    "toma una foto",
    "take a selfie",
    "tire uma foto",
)
_CONTINUE_TEXTS = ("continuar", "continue", "prosseguir")
_FINAL_BUTTON_TEXTS = (
    "he llegado",
    "i'm here",
    "i ve arrived",
    "i arrived",
    "confirmar",
    "confirm",
    "enviar",
    "submit",
    "eu cheguei",
    "cheguei",
    "final",
)
_PAYMENT_TEXTS = ("pago", "precio", "price", "valor", "monto", "payment")
_STATION_TEXTS = ("estacion", "station", "estacao", "punto", "point")
_SCHEDULE_TEXTS = ("horario", "schedule", "hora", "time", "fecha", "slot")
_DURATION_TEXTS = ("duracion", "duration", "horas", "hours", "hrs")
_PROCESSING_TEXTS = (
    "procesando",
    "processing",
    "processando",
    "validando",
    "validating",
    "revisando",
    "reviewing",
    "loading",
    "cargando",
    "carregando",
    "espere",
    "please wait",
)
_SUCCESS_TEXTS = (
    "completado",
    "correctamente",
    "exitoso",
    "success",
    "successful",
    "concluido",
    "concluida",
)
_ERROR_TEXTS = (
    "error",
    "failed",
    "fallo",
    "fallo ",
    "fallo.",
    "no se pudo",
    "incorrecto",
    "invalido",
    "invalida",
)


def _normalize_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value or "")
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    return _WHITESPACE_RE.sub(" ", ascii_text).strip().lower()


def _preview_text(value: str, *, limit: int = 240) -> str:
    compact = _WHITESPACE_RE.sub(" ", (value or "").strip())
    return compact[:limit]


def _has_any(text: str, tokens: tuple[str, ...]) -> bool:
    return any(_normalize_text(token) in text for token in tokens)


def _safe_text(target: Any) -> str:
    if target is None:
        return ""
    locator = getattr(target, "locator", None)
    if callable(locator):
        try:
            body = locator("body").first
            value = body.inner_text(timeout=300)
            if isinstance(value, str) and value.strip():
                return value.strip()
        except Exception:
            pass
    for attribute in ("text_snapshot", "text", "inner_text", "innerText"):
        candidate = getattr(target, attribute, None)
        if candidate is None:
            continue
        try:
            value = candidate() if callable(candidate) else candidate
        except TypeError:
            try:
                value = candidate(timeout=300)
            except Exception:
                continue
        except Exception:
            continue
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _safe_count(locator: Any) -> int:
    if locator is None:
        return 0
    for method_name in ("count",):
        method = getattr(locator, method_name, None)
        if callable(method):
            try:
                return int(method())
            except Exception:
                return 0
    return 0


def _safe_locator_count(target: Any, selector: str) -> int:
    locator = getattr(target, "locator", None)
    if not callable(locator):
        return 0
    try:
        return _safe_count(locator(selector))
    except Exception:
        return 0


def _safe_buttons_text(target: Any) -> list[str]:
    evaluate_target = target
    if getattr(target, "page", None) is not None and not callable(getattr(target, "evaluate", None)):
        evaluate_target = getattr(target, "page")
    evaluate = getattr(evaluate_target, "evaluate", None)
    if callable(evaluate):
        try:
            values = evaluate(
                """
                () => Array.from(
                    document.querySelectorAll("button, [role='button'], input[type='button'], input[type='submit'], a")
                ).map((node) => (node.innerText || node.value || node.getAttribute('aria-label') || node.textContent || '').trim()).filter(Boolean)
                """
            )
            if isinstance(values, list):
                return [str(value).strip() for value in values if str(value).strip()]
        except Exception:
            pass
    return []


@dataclass(frozen=True)
class FlowSignals:
    has_file_input: bool
    has_continue_button: bool
    has_final_button: bool
    has_payment_text: bool
    has_station_text: bool
    has_schedule_text: bool
    has_duration_text: bool
    has_processing_text: bool
    has_success_text: bool
    has_error_text: bool
    buttons: tuple[str, ...]
    inputs_count: int
    text_length: int


@dataclass(frozen=True)
class FlowStateSnapshot:
    site: str
    process_id: str | None
    state: str
    confidence: float
    reason: str
    source: str
    context_type: str
    text_preview: str
    signals: FlowSignals
    detected_at: str


class FlowStateDetector:
    UNKNOWN = "UNKNOWN"
    SELFIE_INPUT = "SELFIE_INPUT"
    PHOTO_READY_TO_CONTINUE = "PHOTO_READY_TO_CONTINUE"
    SELFIE_PROCESSING = "SELFIE_PROCESSING"
    BLOCK_VISIBLE = "BLOCK_VISIBLE"
    FINAL_BUTTON_VISIBLE = "FINAL_BUTTON_VISIBLE"
    FINAL_RESULT = "FINAL_RESULT"
    ERROR = "ERROR"

    def collect_signals(self, context: Any, page: Any = None) -> FlowSignals:
        target = context if context is not None else page
        text = _safe_text(context)
        if not text:
            text = _safe_text(target)
        normalized_text = _normalize_text(text)
        buttons = tuple(_safe_buttons_text(context) or _safe_buttons_text(target))
        normalized_buttons = tuple(_normalize_text(button) for button in buttons)

        has_file_input = _safe_locator_count(target, "input[type='file'], input[accept*='image'], #user_avatar") > 0
        inputs_count = _safe_locator_count(target, "input")
        has_continue_button = any(_has_any(button, _CONTINUE_TEXTS) for button in normalized_buttons) or _safe_locator_count(
            target,
            "button, [role='button'], input[type='submit'], input[type='button'], a",
        ) > 0 and _has_any(normalized_text, _CONTINUE_TEXTS)
        has_final_button = any(_has_any(button, _FINAL_BUTTON_TEXTS) for button in normalized_buttons)

        has_payment_text = _has_any(normalized_text, _PAYMENT_TEXTS)
        has_station_text = _has_any(normalized_text, _STATION_TEXTS)
        has_schedule_text = _has_any(normalized_text, _SCHEDULE_TEXTS) or _TIME_RANGE_RE.search(normalized_text) is not None
        has_duration_text = _has_any(normalized_text, _DURATION_TEXTS) or _DURATION_RE.search(normalized_text) is not None
        has_processing_text = _has_any(normalized_text, _PROCESSING_TEXTS)
        has_success_text = _has_any(normalized_text, _SUCCESS_TEXTS)
        has_error_text = _has_any(normalized_text, _ERROR_TEXTS)

        return FlowSignals(
            has_file_input=has_file_input,
            has_continue_button=has_continue_button,
            has_final_button=has_final_button,
            has_payment_text=has_payment_text,
            has_station_text=has_station_text,
            has_schedule_text=has_schedule_text,
            has_duration_text=has_duration_text,
            has_processing_text=has_processing_text,
            has_success_text=has_success_text,
            has_error_text=has_error_text,
            buttons=buttons,
            inputs_count=inputs_count,
            text_length=len(text or ""),
        )

    def classify(self, signals: FlowSignals) -> tuple[str, float, str]:
        if signals.has_error_text:
            return self.ERROR, 0.99, "texto de error detectado"
        if signals.has_success_text:
            return self.FINAL_RESULT, 0.98, "texto de resultado exitoso detectado"
        if signals.has_processing_text:
            return self.SELFIE_PROCESSING, 0.9, "texto de procesamiento/validacion detectado"

        has_block = (
            signals.has_payment_text
            and signals.has_station_text
            and (signals.has_schedule_text or signals.has_duration_text)
        )
        if signals.has_final_button and has_block:
            return self.FINAL_BUTTON_VISIBLE, 0.96, "boton final visible con senales reales de bloque"
        if has_block:
            return self.BLOCK_VISIBLE, 0.9, "bloque visible con pago + estacion + horario/duracion"
        if signals.has_file_input and signals.has_continue_button:
            return self.PHOTO_READY_TO_CONTINUE, 0.92, "input file + boton continuar"

        selfie_text = signals.has_file_input or signals.inputs_count > 0 or signals.text_length > 0
        if signals.has_file_input:
            return self.SELFIE_INPUT, 0.82, "input file detectado"
        if selfie_text:
            # Avoid classifying any arbitrary body as selfie input unless it also mentions selfie/photo.
            normalized_buttons = tuple(_normalize_text(button) for button in signals.buttons)
            joined_buttons = " ".join(normalized_buttons)
            if _has_any(joined_buttons, _SELFIE_TEXTS):
                return self.SELFIE_INPUT, 0.7, "texto/botones de selfie detectados"
        return self.UNKNOWN, 0.2, "sin senales suficientes"

    def snapshot(
        self,
        site: str,
        process_id: str | None,
        context: Any,
        page: Any = None,
        source: str = "",
    ) -> FlowStateSnapshot:
        signals = self.collect_signals(context, page=page)
        state, confidence, reason = self.classify(signals)
        text_source = context if context is not None else page
        text_preview = _preview_text(_safe_text(text_source))
        context_type = type(context).__name__ if context is not None else "NoneType"
        return FlowStateSnapshot(
            site=site,
            process_id=process_id,
            state=state,
            confidence=confidence,
            reason=reason,
            source=source,
            context_type=context_type,
            text_preview=text_preview,
            signals=signals,
            detected_at=datetime.now(timezone.utc).isoformat(),
        )


def snapshot_to_dict(snapshot: FlowStateSnapshot) -> dict[str, Any]:
    payload = asdict(snapshot)
    payload["signals"] = asdict(snapshot.signals)
    return payload
