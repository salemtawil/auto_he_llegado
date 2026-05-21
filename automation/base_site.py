from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import asdict
from time import monotonic
from typing import Any

from automation.flow_context import ActiveFlowContext, safe_root_text
from automation.flow_state_detector import FlowStateDetector, snapshot_to_dict

from core.models import LocalConfig, ProcessExecutionRequest, SiteExecutionResult

ProgressCallback = Callable[[str, str], None]


class BaseSite(ABC):
    site_name: str = ""
    _TIME_RANGE_RE = r"\b\d{1,2}:\d{2}\s*(?:am|pm)\s*-\s*\d{1,2}:\d{2}\s*(?:am|pm)\b"
    _DURATION_RE = r"\b\d+(?:[.,]\d+)?\s*(?:horas?|hours?|hrs?)\b"
    _FLOW_STATE_THROTTLE_S = 0.5

    def clone_for_run(self):
        return self

    def attach_run_context(self, run_context) -> None:
        self._process_run_context = run_context

    def _record_run_stat(self, event: str, **details: Any) -> None:
        run_context = getattr(self, "_process_run_context", None)
        if run_context is None:
            return
        run_context.run_stats.record(event, details or None)

    @staticmethod
    def _safe_page_url(page: Any) -> str:
        return str(getattr(page, "url", "") or "")

    def _build_common_run_stats_payload(self) -> dict[str, Any]:
        run_context = getattr(self, "_process_run_context", None)
        if run_context is None:
            return {}
        return {
            "process_id": run_context.process_id,
            "page_name": run_context.page_name,
            "slot_id": getattr(run_context, "slot_id", None),
            "action_name": run_context.action_name,
            "execution_mode": run_context.execution_mode,
            "run_stats_timeline": run_context.run_stats.export_timeline(),
            "run_stats_summary": run_context.run_stats.build_common_timing_summary(),
            "run_stats_summary_text": run_context.run_stats.build_common_timing_summary_text(),
        }

    def _get_flow_state_detector(self) -> FlowStateDetector:
        detector = getattr(self, "_flow_state_detector", None)
        if detector is None:
            detector = FlowStateDetector()
            setattr(self, "_flow_state_detector", detector)
        return detector

    def _reset_flow_state_detector_debug(self) -> None:
        setattr(
            self,
            "_flow_state_detector_debug",
            {
                "last_state": None,
                "last_confidence": None,
                "last_reason": "",
                "last_source": "",
                "snapshots_count": 0,
                "state_transitions": [],
                "first_seen_by_state": {},
                "snapshots": [],
            },
        )
        setattr(self, "_flow_state_detector_last_recorded_at", None)

    def _build_flow_state_detector_export(self) -> dict[str, Any]:
        debug_state = getattr(self, "_flow_state_detector_debug", None) or {}
        return {
            "last_state": debug_state.get("last_state"),
            "last_confidence": debug_state.get("last_confidence"),
            "last_reason": debug_state.get("last_reason"),
            "last_source": debug_state.get("last_source"),
            "snapshots_count": debug_state.get("snapshots_count", 0),
            "state_transitions": list(debug_state.get("state_transitions") or []),
            "first_seen_by_state": dict(debug_state.get("first_seen_by_state") or {}),
            "snapshots": [dict(item) for item in debug_state.get("snapshots") or []],
        }

    def _observe_flow_state(self, context, page, source: str):
        detector = self._get_flow_state_detector()
        run_context = getattr(self, "_process_run_context", None)
        process_id = getattr(run_context, "process_id", None)
        snapshot = detector.snapshot(
            site=self.site_name,
            process_id=process_id,
            context=context,
            page=page,
            source=source,
        )
        debug_state = getattr(self, "_flow_state_detector_debug", None)
        if debug_state is None:
            self._reset_flow_state_detector_debug()
            debug_state = getattr(self, "_flow_state_detector_debug")
        last_state = debug_state.get("last_state")
        now = monotonic()
        last_recorded_at = getattr(self, "_flow_state_detector_last_recorded_at", None)
        force_record = snapshot.state in {FlowStateDetector.FINAL_BUTTON_VISIBLE, FlowStateDetector.ERROR}
        state_changed = snapshot.state != last_state
        throttled = (
            last_recorded_at is not None
            and (now - float(last_recorded_at)) < self._FLOW_STATE_THROTTLE_S
            and not state_changed
            and not force_record
        )
        if throttled:
            return snapshot

        snapshot_payload = snapshot_to_dict(snapshot)
        debug_state["last_state"] = snapshot.state
        debug_state["last_confidence"] = snapshot.confidence
        debug_state["last_reason"] = snapshot.reason
        debug_state["last_source"] = snapshot.source
        debug_state["snapshots_count"] = int(debug_state.get("snapshots_count", 0)) + 1
        first_seen_by_state = dict(debug_state.get("first_seen_by_state") or {})
        first_seen_by_state.setdefault(snapshot.state, snapshot.detected_at)
        debug_state["first_seen_by_state"] = first_seen_by_state
        if state_changed and last_state is not None:
            transitions = list(debug_state.get("state_transitions") or [])
            transitions.append(
                {
                    "from": last_state,
                    "to": snapshot.state,
                    "detected_at": snapshot.detected_at,
                    "source": snapshot.source,
                }
            )
            debug_state["state_transitions"] = transitions
        snapshots = list(debug_state.get("snapshots") or [])
        snapshots.append(snapshot_payload)
        debug_state["snapshots"] = snapshots[-50:]
        setattr(self, "_flow_state_detector_last_recorded_at", now)

        record_timeline_event = getattr(self, "_record_timeline_event", None)
        if callable(record_timeline_event):
            record_timeline_event(
                "flow_detector_state",
                state=snapshot.state,
                confidence=snapshot.confidence,
                reason=snapshot.reason,
                source=snapshot.source,
                signals=asdict(snapshot.signals),
                text_preview=snapshot.text_preview,
                context_type=snapshot.context_type,
            )
        self._record_run_stat(
            "flow_detector_state",
            state=snapshot.state,
            confidence=snapshot.confidence,
            reason=snapshot.reason,
            source=snapshot.source,
            signals=asdict(snapshot.signals),
            text_preview=snapshot.text_preview,
            context_type=snapshot.context_type,
        )
        return snapshot

    def _is_cancel_requested(self) -> bool:
        run_context = getattr(self, "_process_run_context", None)
        return bool(run_context is not None and run_context.cancel_event.is_set())

    def _raise_if_cancelled(self) -> None:
        if self._is_cancel_requested():
            raise RuntimeError("Proceso cancelado por cancel_event.")

    def _build_active_flow_context(
        self,
        *,
        page,
        root,
        source: str,
        stage: str,
        text_snapshot: str | None = None,
    ) -> ActiveFlowContext:
        return ActiveFlowContext(
            page=page,
            root=root,
            source=source,
            stage=stage,
            text_snapshot=text_snapshot if text_snapshot is not None else safe_root_text(root),
        )

    def _extract_time_range(self, text: str) -> str:
        import re

        match = re.search(self._TIME_RANGE_RE, text or "", re.IGNORECASE)
        return match.group(0).strip() if match is not None else "N/A"

    def _extract_duration_text(self, text: str) -> str:
        import re

        match = re.search(self._DURATION_RE, text or "", re.IGNORECASE)
        return match.group(0).strip() if match is not None else "N/A"

    def _looks_like_duration_text(self, text: str) -> bool:
        import re

        return re.search(self._DURATION_RE, text or "", re.IGNORECASE) is not None

    def _parse_block_snapshot_details(
        self,
        pairs: dict[str, str],
        full_text: str,
        *,
        payment_aliases: tuple[str, ...],
        station_aliases: tuple[str, ...],
        schedule_aliases: tuple[str, ...],
        duration_aliases: tuple[str, ...],
        hours_aliases: tuple[str, ...] = ("horas", "hours", "hrs"),
    ) -> tuple[str, str, str, str]:
        payment = self._pick_detail_value(pairs, payment_aliases)
        station = self._pick_detail_value(pairs, station_aliases)
        schedule = self._extract_time_range(full_text) or "N/A"
        if schedule == "N/A":
            schedule = self._pick_detail_value(pairs, schedule_aliases)
        if schedule != "N/A":
            schedule = schedule.replace("(He llegado)", "").strip()
        duration = "N/A"
        for alias_group in (hours_aliases, duration_aliases):
            candidate = self._pick_detail_value(pairs, alias_group)
            if candidate != "N/A" and self._looks_like_duration_text(candidate):
                duration = candidate
                break
        if duration == "N/A":
            duration = self._extract_duration_text(full_text)
        return payment, station, schedule, duration

    def _try_fast_click_final_from_flow_context(
        self,
        page,
        context,
        progress_callback: ProgressCallback | None,
        *,
        source: str,
    ) -> bool:
        if context is None:
            return False
        if not hasattr(context, "locator"):
            return False
        page_url = self._safe_page_url(page)
        looks_like_body = getattr(self, "_looks_like_body_context", None)
        if callable(looks_like_body) and looks_like_body(context):
            self.emit_progress(progress_callback, phase="block_read", message="dashboard/body descartado como contexto principal")
            return False
        find_button = getattr(self, "_find_final_submit_button", None)
        if not callable(find_button):
            return False
        try:
            button = find_button(context, page=page)
        except TypeError:
            button = find_button(context)
        if button is None:
            return False
        context_has_block_details = getattr(self, "_context_has_block_details", None)
        if callable(context_has_block_details) and not context_has_block_details(context):
            return False
        capture_snapshot = getattr(self, "_capture_block_snapshot_text", None)
        snapshot_text = capture_snapshot(context, page) if callable(capture_snapshot) else safe_root_text(context)
        setattr(self, "_latest_block_snapshot_text", snapshot_text)
        set_active_flow_context = getattr(self, "_set_active_flow_context", None)
        if callable(set_active_flow_context):
            set_active_flow_context(context, page=page, source=source)
        remember_candidate = getattr(self, "_remember_final_button_candidate", None)
        if callable(remember_candidate):
            remember_candidate(context=context, button=button, page=page, source=source)
        self._mark_phase_timing("block_visual_detected", source=source, url=page_url)
        self._record_run_stat("block_visual_detected", source=source, url=page_url)
        self.emit_progress(progress_callback, phase="final_submit", message="bloque detectado por boton final: click inmediato")
        self._mark_phase_timing("final_click_started", source=source, url=page_url)
        self._record_run_stat("final_click_started", source=source, url=page_url)
        try:
            button.click(timeout=400)
        except Exception:
            try:
                button.click(timeout=400, force=True)
            except Exception:
                try:
                    button.evaluate("node => node.click()")
                except Exception:
                    return False
        setattr(self, "_final_submit_already_clicked", True)
        from time import monotonic

        setattr(self, "_final_submit_fast_clicked_at", monotonic())
        self._mark_phase_timing("final_click_done", source=source, url=page_url)
        self._record_run_stat("final_click_done", source=source, url=page_url)
        self.emit_progress(progress_callback, phase="final_submit", message="boton final presionado directamente desde contexto activo")
        return True

    @abstractmethod
    def execute(
        self,
        request: ProcessExecutionRequest,
        *,
        local_config: LocalConfig,
        progress_callback: ProgressCallback | None = None,
    ) -> SiteExecutionResult:
        raise NotImplementedError

    @staticmethod
    def emit_progress(
        progress_callback: ProgressCallback | None,
        *,
        phase: str,
        message: str,
    ) -> None:
        if progress_callback is not None:
            progress_callback(phase, message)
