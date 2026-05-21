from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from time import monotonic
from typing import Any


class RunStatsRecorder:
    def __init__(self) -> None:
        self._started_at = monotonic()
        self._timeline: list[dict[str, Any]] = []

    def record(self, event: str, details: dict[str, Any] | None = None) -> None:
        payload = dict(details or {})
        now = monotonic()
        self._timeline.append(
            {
                "event": event,
                "recorded_at": datetime.now(timezone.utc).isoformat(),
                "elapsed_ms": int((now - self._started_at) * 1000),
                "details": payload,
            }
        )

    def export_timeline(self) -> list[dict[str, Any]]:
        return [dict(item, details=dict(item.get("details") or {})) for item in self._timeline]

    def build_summary(self) -> dict[str, Any]:
        return {
            "event_count": len(self._timeline),
            "total_elapsed_ms": self._timeline[-1]["elapsed_ms"] if self._timeline else 0,
            "last_event": self._timeline[-1]["event"] if self._timeline else None,
        }

    def first_event_elapsed_ms(self, event: str) -> int | None:
        for item in self._timeline:
            if item.get("event") == event:
                return int(item.get("elapsed_ms") or 0)
        return None

    def duration_ms(self, start_event: str, end_event: str) -> int | None:
        start = self.first_event_elapsed_ms(start_event)
        end = self.first_event_elapsed_ms(end_event)
        if start is None or end is None or end < start:
            return None
        return end - start

    @staticmethod
    def _coalesce_duration(*durations: int | None) -> int | None:
        for duration in durations:
            if duration is not None:
                return duration
        return None

    @staticmethod
    def _format_duration(duration_ms: int | None) -> str:
        if duration_ms is None:
            return "N/A"
        return f"{duration_ms / 1000:.1f}s"

    def build_common_timing_summary(self) -> dict[str, str]:
        total_duration = self._coalesce_duration(
            self.duration_ms("process_started", "final_result_done"),
            self.duration_ms("process_started", "process_finished"),
        )
        return {
            "login": self._format_duration(self.duration_ms("login_started", "login_done")),
            "foto_prep": self._format_duration(self.duration_ms("photo_prepare_started", "photo_prepare_done")),
            "inputupload": self._format_duration(self.duration_ms("selfie_input_detected", "photo_upload_started")),
            "photo_upload": self._format_duration(self.duration_ms("photo_upload_started", "photo_upload_done")),
            "validacion_sitio": self._format_duration(
                self._coalesce_duration(
                    self.duration_ms("continue_clicked", "block_visual_detected"),
                    self.duration_ms("continue_clicked", "block_detected"),
                )
            ),
            "bloqueclick": self._format_duration(
                self._coalesce_duration(
                    self.duration_ms("block_visual_detected", "final_click_done"),
                    self.duration_ms("block_detected", "final_click_done"),
                )
            ),
            "resultado_final": self._format_duration(
                self._coalesce_duration(
                    self.duration_ms("final_click_done", "final_result_done"),
                    self.duration_ms("final_result_started", "final_result_done"),
                )
            ),
            "total": self._format_duration(total_duration),
        }

    def build_common_timing_summary_text(self) -> str:
        summary = self.build_common_timing_summary()
        parts = [
            f"login {summary['login']}",
            f"foto prep {summary['foto_prep']}",
            f"inputupload {summary['inputupload']}",
            f"photo upload {summary['photo_upload']}",
            f"validacion sitio {summary['validacion_sitio']}",
            f"bloqueclick {summary['bloqueclick']}",
            f"resultado final {summary['resultado_final']}",
            f"total {summary['total']}",
        ]
        return "Resumen tiempos: " + " | ".join(parts)


@dataclass
class ProcessRunContext:
    process_id: str
    page_name: str
    action_name: str
    phone_number: str
    execution_mode: str
    log_service: Any
    slot_id: str | None = None
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    cancel_event: threading.Event = field(default_factory=threading.Event)
    photo_service: Any | None = None
    run_stats: RunStatsRecorder = field(default_factory=RunStatsRecorder)
    debug: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    log_record_id: int | None = None
    log_updates_enabled: bool = True
    last_log_update_at: float | None = None

    def add_warning(self, message: str) -> None:
        self.warnings.append(message)
