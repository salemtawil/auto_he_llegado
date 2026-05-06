from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
from pathlib import Path
from typing import Any

from playwright.sync_api import Error, Page

from debug_tools.dom_snapshot_service import PageSnapshot


def _timestamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S_%f")


@dataclass(slots=True)
class SessionPaths:
    root: Path
    screenshots: Path
    html_main: Path
    html_iframes: Path
    texts: Path


class ExportService:
    def __init__(self, base_dir: str | Path) -> None:
        self._base_dir = Path(base_dir)
        self._session: SessionPaths | None = None
        self._timeline: list[dict[str, Any]] = []
        self._events: list[dict[str, Any]] = []

    @property
    def session_root(self) -> Path | None:
        return self._session.root if self._session else None

    def start_session(self) -> Path:
        root = self._base_dir / f"session_{_timestamp()}"
        paths = SessionPaths(
            root=root,
            screenshots=root / "screenshots",
            html_main=root / "html_main",
            html_iframes=root / "html_iframes",
            texts=root / "texts",
        )
        for directory in (paths.root, paths.screenshots, paths.html_main, paths.html_iframes, paths.texts):
            directory.mkdir(parents=True, exist_ok=True)
        self._session = paths
        self._timeline = []
        self._events = []
        return root

    def ensure_session(self) -> Path:
        if self._session is None:
            return self.start_session()
        return self._session.root

    def record_snapshot(
        self,
        *,
        event_kind: str,
        message: str,
        snapshot: PageSnapshot,
        page: Page | None,
        metadata: dict[str, Any] | None = None,
    ) -> Path:
        session_root = self.ensure_session()
        assert self._session is not None
        stamp = _timestamp()
        base_name = f"{stamp}_{event_kind}"

        event_payload = {
            "timestamp": snapshot.captured_at,
            "kind": event_kind,
            "message": message,
            "url": snapshot.url,
            "title": snapshot.title,
            "iframe_count": len(snapshot.iframes),
        }
        if metadata:
            event_payload["metadata"] = metadata
        self._events.append(event_payload)

        self._timeline.append(
            {
                "timestamp": snapshot.captured_at,
                "kind": event_kind,
                "message": message,
                "artifacts": {
                    "snapshot_json": f"{base_name}.json",
                    "main_html": f"{base_name}_main.html",
                    "main_text": f"{base_name}_main.txt",
                    "screenshot": f"{base_name}.png",
                },
            }
        )

        (session_root / "events.json").write_text(
            json.dumps(self._events, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        (session_root / "timeline.json").write_text(
            json.dumps(self._timeline, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        (session_root / f"{base_name}.json").write_text(
            json.dumps(snapshot.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        (self._session.html_main / f"{base_name}_main.html").write_text(
            snapshot.main.html,
            encoding="utf-8",
        )
        (self._session.texts / f"{base_name}_main.txt").write_text(
            "\n".join(snapshot.main.visible_lines),
            encoding="utf-8",
        )

        for iframe in snapshot.iframes:
            root = snapshot.iframe_roots.get(str(iframe.index))
            if root is None:
                continue
            prefix = f"{base_name}_iframe_{iframe.index:02d}"
            (self._session.html_iframes / f"{prefix}.html").write_text(root.html, encoding="utf-8")
            (self._session.texts / f"{prefix}.txt").write_text(
                "\n".join(root.visible_lines),
                encoding="utf-8",
            )

        report_lines = [
            "Sesion de inspeccion automatica",
            f"Eventos capturados: {len(self._events)}",
            f"Ultimo evento: {event_kind}",
            f"URL: {snapshot.url}",
            f"Titulo: {snapshot.title}",
        ]
        report_lines.extend(
            f"- [{item['timestamp']}] {item['kind']}: {item['message']}" for item in self._events[-20:]
        )
        (session_root / "report.txt").write_text("\n".join(report_lines), encoding="utf-8")

        if page is not None:
            screenshot_path = self._session.screenshots / f"{base_name}.png"
            try:
                page.screenshot(path=str(screenshot_path), full_page=True)
            except Error:
                pass

        return session_root

    def export_summary(self) -> Path:
        session_root = self.ensure_session()
        report_lines = ["Sesion de inspeccion automatica", f"Eventos: {len(self._events)}"]
        report_lines.extend(
            f"- [{item['timestamp']}] {item['kind']}: {item['message']}" for item in self._events[-50:]
        )
        (session_root / "report.txt").write_text("\n".join(report_lines), encoding="utf-8")
        return session_root
