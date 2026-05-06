from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import queue
import threading
from typing import Any

from playwright.sync_api import Browser, BrowserContext, Error, Page, Playwright, sync_playwright

from debug_tools.dom_snapshot_service import DomSnapshotService, PageSnapshot
from debug_tools.export_service import ExportService


SITE_URLS = {
    "compinche": "https://compinche.io/login",
    "paripe": "https://paripe.io/login",
}
POLL_INTERVAL_SECONDS = 2.0

_INIT_SCRIPT = """
(() => {
  if (window.__debugInspectorInstalled) return;
  window.__debugInspectorInstalled = true;
  window.__debugInspectorEvents = [];
  const push = (kind, payload) => {
    window.__debugInspectorEvents.push({
      kind,
      payload,
      at: new Date().toISOString(),
    });
    if (window.__debugInspectorEvents.length > 200) {
      window.__debugInspectorEvents.splice(0, window.__debugInspectorEvents.length - 200);
    }
  };
  const summarize = (node) => {
    if (!node) return { tag: "", text: "" };
    return {
      tag: node.tagName ? node.tagName.toLowerCase() : "",
      text: (node.innerText || node.textContent || "").replace(/\\s+/g, " ").trim().slice(0, 200),
    };
  };
  document.addEventListener("click", (event) => push("user_click", summarize(event.target)), true);
  document.addEventListener("change", (event) => push("user_change", summarize(event.target)), true);
})();
"""


@dataclass(slots=True)
class WorkerCommand:
    name: str
    payload: dict[str, Any]


class InspectorService:
    def __init__(self, base_dir: str) -> None:
        self._base_dir = base_dir
        self._command_queue: queue.Queue[WorkerCommand] = queue.Queue()
        self._event_queue: queue.Queue[dict[str, Any]] = queue.Queue()
        self._stop_requested = False
        self._worker = threading.Thread(target=self._run_worker, name="debug-inspector-worker", daemon=True)
        self._worker.start()

    @property
    def event_queue(self) -> queue.Queue[dict[str, Any]]:
        return self._event_queue

    def open_browser(self, site_key: str) -> None:
        self._command_queue.put(WorkerCommand("open_browser", {"site_key": site_key}))

    def start_observation(self, search_text: str = "") -> None:
        self._command_queue.put(WorkerCommand("start_observation", {"search_text": search_text}))

    def stop_observation(self) -> None:
        self._command_queue.put(WorkerCommand("stop_observation", {}))

    def export_report(self) -> None:
        self._command_queue.put(WorkerCommand("export_report", {}))

    def shutdown(self) -> None:
        self._command_queue.put(WorkerCommand("shutdown", {}))
        self._worker.join(timeout=5)

    def _run_worker(self) -> None:
        playwright: Playwright | None = None
        browser: Browser | None = None
        context: BrowserContext | None = None
        page: Page | None = None
        snapshot_service = DomSnapshotService()
        exporter = ExportService(self._base_dir)
        observing = False
        last_snapshot: PageSnapshot | None = None
        last_signature: str | None = None
        next_poll_at = datetime.min
        pending_reasons: list[str] = []

        def note(reason: str) -> None:
            pending_reasons.append(reason)

        try:
            while not self._stop_requested:
                try:
                    command = self._command_queue.get(timeout=0.25)
                    if command.name == "open_browser":
                        site_key = str(command.payload.get("site_key", "compinche") or "compinche").strip().lower()
                        target_url = SITE_URLS.get(site_key, SITE_URLS["compinche"])
                        if browser is None:
                            playwright = sync_playwright().start()
                            browser = playwright.chromium.launch(headless=False)
                            context = browser.new_context()
                            context.add_init_script(_INIT_SCRIPT)
                            page = context.new_page()
                            page.on("framenavigated", lambda frame: note(f"frame_navigated:{frame.url}"))
                            page.on("domcontentloaded", lambda: note("domcontentloaded"))
                            page.on("load", lambda: note("load"))
                            exporter.start_session()
                        assert page is not None
                        page.goto(target_url, wait_until="domcontentloaded")
                        self._push_status(f"Navegador abierto en {site_key}.", active=observing)
                        self._push_log(f"Navegador visible abierto en {target_url}")
                        next_poll_at = datetime.now()
                    elif command.name == "start_observation":
                        if page is None:
                            self._push_error("Abre el navegador antes de iniciar la observación.")
                            continue
                        search_text = str(command.payload.get("search_text", "") or "").strip()
                        snapshot_service = DomSnapshotService([search_text] if search_text else None)
                        observing = True
                        pending_reasons.append("observation_started")
                        self._push_status("Observación activa.", active=True)
                        self._push_log("Observación automática iniciada.")
                        next_poll_at = datetime.now()
                    elif command.name == "stop_observation":
                        observing = False
                        self._push_status("Observación detenida.", active=False)
                        self._push_log("Observación automática detenida.")
                    elif command.name == "export_report":
                        root = exporter.export_summary()
                        self._push_log(f"Reporte exportado en: {root}")
                    elif command.name == "shutdown":
                        self._stop_requested = True
                except queue.Empty:
                    pass

                if not observing or page is None:
                    continue
                if datetime.now() < next_poll_at:
                    continue

                next_poll_at = datetime.now() + timedelta(seconds=POLL_INTERVAL_SECONDS)
                reasons = list(pending_reasons)
                pending_reasons.clear()
                user_events = self._drain_page_events(page)
                reasons.extend(item["kind"] for item in user_events)

                try:
                    snapshot = snapshot_service.capture(page)
                    signature = snapshot_service.build_signature(snapshot)
                except Exception as exc:
                    self._push_error(f"Error capturando snapshot: {exc}")
                    continue

                detected = snapshot_service.detect_events(last_snapshot, snapshot, last_signature, signature)
                if reasons and not detected:
                    detected.append(
                        {
                            "kind": "activity_detected",
                            "message": f"Actividad detectada: {', '.join(reasons[:5])}",
                            "reasons": reasons[:20],
                        }
                    )

                for user_event in user_events:
                    detected.append(
                        {
                            "kind": user_event["kind"],
                            "message": f"Evento manual: {user_event['kind']}",
                            "metadata": user_event,
                        }
                    )

                if detected:
                    for item in detected:
                        root = exporter.record_snapshot(
                            event_kind=item["kind"],
                            message=item["message"],
                            snapshot=snapshot,
                            page=page,
                            metadata=item.get("metadata") or {"reasons": item.get("reasons")},
                        )
                        self._push_log(f"Snapshot exportado: {item['kind']}")
                        self._push_snapshot_event(item["message"], snapshot, root, item["kind"])
                else:
                    self._push_snapshot_heartbeat(snapshot)

                last_snapshot = snapshot
                last_signature = signature
        finally:
            if context is not None:
                context.close()
            if browser is not None:
                browser.close()
            if playwright is not None:
                playwright.stop()

    def _drain_page_events(self, page: Page) -> list[dict[str, Any]]:
        try:
            payload = page.evaluate(
                """
                () => {
                  const items = Array.isArray(window.__debugInspectorEvents)
                    ? window.__debugInspectorEvents.splice(0, window.__debugInspectorEvents.length)
                    : [];
                  return items;
                }
                """
            )
        except Error:
            return []
        if not isinstance(payload, list):
            return []
        return [item for item in payload[:25] if isinstance(item, dict)]

    def _push_status(self, message: str, *, active: bool) -> None:
        self._event_queue.put({"type": "status", "message": message, "active": active})

    def _push_log(self, message: str) -> None:
        self._event_queue.put({"type": "log", "message": message, "at": datetime.now().isoformat()})

    def _push_error(self, message: str) -> None:
        self._event_queue.put({"type": "error", "message": message, "at": datetime.now().isoformat()})

    def _push_snapshot_event(self, message: str, snapshot: PageSnapshot, root: Any, kind: str) -> None:
        for item in snapshot.iframes:
            if item.accessible:
                self._push_log(f"Iframe detectado [{item.index}]: title={item.title or '-'} src={item.src or '-'}")
            else:
                self._push_error(
                    f"Error al inspeccionar iframe {item.index}: {item.inspect_error or 'frame no accesible'}"
                )
        self._event_queue.put(
            {
                "type": "snapshot",
                "kind": kind,
                "message": message,
                "url": snapshot.url,
                "title": snapshot.title,
                "iframes": [
                    {
                        "index": item.index,
                        "title": item.title,
                        "src": item.src,
                        "url": item.url,
                        "accessible": item.accessible,
                        "inspect_error": item.inspect_error,
                    }
                    for item in snapshot.iframes
                ],
                "session_root": str(root),
                "at": snapshot.captured_at,
            }
        )

    def _push_snapshot_heartbeat(self, snapshot: PageSnapshot) -> None:
        self._event_queue.put(
            {
                "type": "heartbeat",
                "url": snapshot.url,
                "title": snapshot.title,
                "iframes": [
                    {
                        "index": item.index,
                        "title": item.title,
                        "src": item.src,
                        "url": item.url,
                        "accessible": item.accessible,
                        "inspect_error": item.inspect_error,
                    }
                    for item in snapshot.iframes
                ],
                "at": snapshot.captured_at,
            }
        )
