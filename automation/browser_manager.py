from __future__ import annotations

from dataclasses import dataclass
from copy import deepcopy
import json
import os
from pathlib import Path
import shutil
import subprocess
import threading
from time import sleep, time
from contextlib import suppress

from config.paths import DEFAULT_LOCAL_DATA_DIR, PROJECT_ROOT
from config.settings import Settings, get_settings

_EXPECTED_EXTENSION_NAME = "Auto He Llegado Observer"
_CHROME_DEBUG_PORT = 9222


@dataclass
class BrowserSession:
    playwright: object
    browser: object
    context: object
    page: object
    keep_open: bool = False
    extension_enabled: bool = False
    extension_path: str | None = None
    extension_loaded: bool = False
    extension_service_worker_url: str | None = None
    run_id: int = 0
    profile_dir: str | None = None
    cleanup_profile_dir: bool = False
    disconnect_only: bool = False
    _closed: bool = False
    _extension_debug_lock: object | None = None
    _last_extension_debug: dict | None = None
    _engine_phase_history: list[dict] | None = None

    def __post_init__(self) -> None:
        self._extension_debug_lock = threading.Lock()
        self._engine_phase_history = []

    def close(self) -> None:
        self._close_internal(force=False)

    def shutdown(self) -> None:
        self._close_internal(force=True)

    def clear_auth_state(self, page: object | None = None) -> dict[str, object]:
        report: dict[str, object] = {
            "cookies_cleared": False,
            "local_storage_cleared": False,
            "session_storage_cleared": False,
            "indexeddb_cleared": False,
            "cache_storage_cleared": False,
            "service_workers_unregistered": False,
            "origin": None,
        }
        with suppress(Exception):
            self.context.clear_cookies()
            report["cookies_cleared"] = True
        target_page = page or self.page
        target_url = str(getattr(target_page, "url", "") or "")
        if not target_url.startswith(("http://", "https://")):
            return report
        report["origin"] = target_url
        with suppress(Exception):
            storage_report = target_page.evaluate(
                """async () => {
                    const result = {
                        local_storage_cleared: false,
                        session_storage_cleared: false,
                        indexeddb_cleared: false,
                        cache_storage_cleared: false,
                        service_workers_unregistered: false,
                    };
                    try {
                        window.localStorage?.clear();
                        result.local_storage_cleared = true;
                    } catch (_error) {}
                    try {
                        window.sessionStorage?.clear();
                        result.session_storage_cleared = true;
                    } catch (_error) {}
                    try {
                        if ("serviceWorker" in navigator) {
                            const registrations = await navigator.serviceWorker.getRegistrations();
                            await Promise.all(registrations.map((registration) => registration.unregister()));
                            result.service_workers_unregistered = true;
                        }
                    } catch (_error) {}
                    try {
                        if ("caches" in window) {
                            const keys = await caches.keys();
                            await Promise.all(keys.map((key) => caches.delete(key)));
                            result.cache_storage_cleared = true;
                        }
                    } catch (_error) {}
                    try {
                        if (indexedDB && typeof indexedDB.databases === "function") {
                            const databases = await indexedDB.databases();
                            await Promise.all(
                                (databases || [])
                                    .map((item) => item && item.name)
                                    .filter(Boolean)
                                    .map(
                                        (name) =>
                                            new Promise((resolve) => {
                                                try {
                                                    const request = indexedDB.deleteDatabase(name);
                                                    request.onsuccess = () => resolve(true);
                                                    request.onerror = () => resolve(false);
                                                    request.onblocked = () => resolve(false);
                                                } catch (_error) {
                                                    resolve(false);
                                                }
                                            }),
                                    ),
                            );
                            result.indexeddb_cleared = true;
                        }
                    } catch (_error) {}
                    return result;
                }"""
            )
            if isinstance(storage_report, dict):
                report.update(storage_report)
        return report

    def read_observer_state(self, page: object | None = None) -> dict | None:
        target_page = page or self.page
        dom_marker_state = self.read_extension_state_from_dom_markers(page=target_page)
        frames = getattr(target_page, "frames", None)
        frame_scan: list[dict] = []
        if frames:
            for index, frame in enumerate(frames):
                state = self._evaluate_observer_state(frame)
                frame_info = {
                    "index": index,
                    "url": getattr(frame, "url", None),
                    "name": self._frame_name(frame),
                    "is_top_frame": frame is getattr(target_page, "main_frame", None),
                    "has_state": state is not None,
                    "selected": False,
                }
                frame_scan.append(frame_info)
                if not self._is_valid_observer_state(state):
                    continue
                frame_info["selected"] = True
                enriched_state = self._enrich_observer_state(
                    state,
                    frame=frame,
                    is_top_frame=frame_info["is_top_frame"],
                    frame_count=len(frames),
                    frame_scan=frame_scan,
                )
                if self._should_prefer_dom_marker_state(enriched_state, dom_marker_state):
                    return dom_marker_state
                return enriched_state
        with suppress(Exception):
            state = target_page.evaluate("() => window.__autoHeLlegadoState ?? null")
            if not isinstance(state, dict):
                return dom_marker_state or state
            enriched_state = self._enrich_observer_state(
                state,
                frame=getattr(target_page, "main_frame", None),
                is_top_frame=True,
                frame_count=len(frames) if frames else 0,
                frame_scan=frame_scan,
            )
            if self._should_prefer_dom_marker_state(enriched_state, dom_marker_state):
                return dom_marker_state
            return enriched_state
        return dom_marker_state

    def read_extension_debug_marker(self, page: object | None = None) -> dict | None:
        target_page = page or self.page
        with suppress(Exception):
            observer_state = self.read_observer_state(page=target_page)
            return target_page.evaluate(
                """(observerState) => ({
                    state: observerState ?? null,
                    windowState: window.__autoHeLlegadoState ?? null,
                    marker: document.documentElement?.dataset?.autoHeLlegadoContentScript ?? null,
                    overlayPresent: !!document.getElementById('auto-he-llegado-overlay'),
                    overlayFramePresent: !!document.getElementById('auto-he-llegado-frame-overlay')
                })""",
                observer_state,
            )
        return None

    def read_content_markers_from_all_frames(self, page: object | None = None) -> dict:
        target_page = page or self.page
        frames = list(getattr(target_page, "frames", None) or [])
        if not frames:
            main_frame = getattr(target_page, "main_frame", None)
            if main_frame is not None:
                frames = [main_frame]
        main_frame = getattr(target_page, "main_frame", None)
        report = {
            "total_frames": len(frames),
            "frames_with_content_marker": 0,
            "frames_with_main_world_marker": 0,
            "selected_frame": None,
            "frames": [],
        }
        for index, frame in enumerate(frames):
            frame_entry = {
                "index": index,
                "frame_url": getattr(frame, "url", None),
                "frame_name": self._frame_name(frame),
                "is_top_frame": frame is main_frame,
                "content_loaded": False,
                "content_href": None,
                "content_hostname": None,
                "content_frame": None,
                "bridge_status": None,
                "main_world_ready": False,
                "main_world_href": None,
                "main_world_hostname": None,
                "ping_loaded": False,
                "ping_href": None,
                "ping_hostname": None,
                "site": "unknown",
                "lang": "unknown",
                "phase": "unknown",
                "last_valid_phase": "unknown",
                "signals_user_avatar": False,
                "signals_continue": 0,
                "signals_loading": False,
                "signals_block": False,
                "signals_iframe": 0,
                "updated_at": None,
                "error": None,
                "selected": False,
            }
            try:
                marker = frame.evaluate(
                    """() => ({
                        contentLoaded: document.documentElement?.dataset?.autoHeLlegadoContentLoaded ?? null,
                        contentHref: document.documentElement?.dataset?.autoHeLlegadoContentHref ?? null,
                        contentHostname: document.documentElement?.dataset?.autoHeLlegadoContentHostname ?? null,
                        contentFrame: document.documentElement?.dataset?.autoHeLlegadoContentFrame ?? null,
                        bridgeStatus: document.documentElement?.dataset?.autoHeLlegadoBridgeStatus ?? null,
                        mainWorldReady: document.documentElement?.dataset?.autoHeLlegadoMainWorld ?? null,
                        mainWorldHref: document.documentElement?.dataset?.autoHeLlegadoMainWorldHref ?? null,
                        mainWorldHostname: document.documentElement?.dataset?.autoHeLlegadoMainWorldHostname ?? null,
                        pingLoaded: document.documentElement?.dataset?.autoHeLlegadoPingLoaded ?? null,
                        pingHref: document.documentElement?.dataset?.autoHeLlegadoPingHref ?? null,
                        pingHostname: document.documentElement?.dataset?.autoHeLlegadoPingHostname ?? null,
                        site: document.documentElement?.dataset?.autoHeLlegadoSite ?? null,
                        lang: document.documentElement?.dataset?.autoHeLlegadoLang ?? null,
                        phase: document.documentElement?.dataset?.autoHeLlegadoPhase ?? null,
                        lastValidPhase: document.documentElement?.dataset?.autoHeLlegadoLastValidPhase ?? null,
                        signalsUserAvatar: document.documentElement?.dataset?.autoHeLlegadoSignalsUserAvatar ?? null,
                        signalsContinue: document.documentElement?.dataset?.autoHeLlegadoSignalsContinue ?? null,
                        signalsLoading: document.documentElement?.dataset?.autoHeLlegadoSignalsLoading ?? null,
                        signalsBlock: document.documentElement?.dataset?.autoHeLlegadoSignalsBlock ?? null,
                        signalsIframe: document.documentElement?.dataset?.autoHeLlegadoSignalsIframe ?? null,
                        updatedAt: document.documentElement?.dataset?.autoHeLlegadoUpdatedAt ?? null
                    })"""
                )
            except Exception as exc:  # noqa: BLE001
                frame_entry["error"] = str(exc)
            else:
                if isinstance(marker, dict):
                    frame_entry["content_loaded"] = marker.get("contentLoaded") == "true"
                    frame_entry["content_href"] = marker.get("contentHref")
                    frame_entry["content_hostname"] = marker.get("contentHostname")
                    frame_entry["content_frame"] = marker.get("contentFrame")
                    frame_entry["bridge_status"] = marker.get("bridgeStatus")
                    frame_entry["main_world_ready"] = marker.get("mainWorldReady") == "ready"
                    frame_entry["main_world_href"] = marker.get("mainWorldHref")
                    frame_entry["main_world_hostname"] = marker.get("mainWorldHostname")
                    frame_entry["ping_loaded"] = marker.get("pingLoaded") == "true"
                    frame_entry["ping_href"] = marker.get("pingHref")
                    frame_entry["ping_hostname"] = marker.get("pingHostname")
                    frame_entry["site"] = marker.get("site") or "unknown"
                    frame_entry["lang"] = marker.get("lang") or "unknown"
                    frame_entry["phase"] = marker.get("phase") or "unknown"
                    frame_entry["last_valid_phase"] = marker.get("lastValidPhase") or "unknown"
                    frame_entry["signals_user_avatar"] = marker.get("signalsUserAvatar") == "true"
                    frame_entry["signals_continue"] = int(marker.get("signalsContinue") or 0)
                    frame_entry["signals_loading"] = marker.get("signalsLoading") == "true"
                    frame_entry["signals_block"] = marker.get("signalsBlock") == "true"
                    frame_entry["signals_iframe"] = int(marker.get("signalsIframe") or 0)
                    frame_entry["updated_at"] = marker.get("updatedAt")
                    if frame_entry["content_loaded"]:
                        report["frames_with_content_marker"] += 1
                    if frame_entry["main_world_ready"]:
                        report["frames_with_main_world_marker"] += 1
            report["frames"].append(frame_entry)
        selected_index = self._select_best_marker_frame(report["frames"])
        if selected_index is not None:
            report["frames"][selected_index]["selected"] = True
            report["selected_frame"] = deepcopy(report["frames"][selected_index])
        return report

    def read_extension_state_from_dom_markers(self, page: object | None = None) -> dict | None:
        report = self.read_content_markers_from_all_frames(page=page)
        selected = report.get("selected_frame") or {}
        if not selected.get("content_loaded"):
            return None
        frame_role = "top" if selected.get("is_top_frame") else "iframe"
        href = selected.get("main_world_href") or selected.get("ping_href") or selected.get("content_href")
        hostname = selected.get("main_world_hostname") or selected.get("ping_hostname") or selected.get("content_hostname")
        site = selected.get("site") or "unknown"
        if site == "unknown":
            site = self._infer_site_from_hostname(hostname)
        state = {
            "site": site,
            "lang": selected.get("lang") or "unknown",
            "language": selected.get("lang") or "unknown",
            "phase": selected.get("phase") or "unknown",
            "lastValidPhase": selected.get("last_valid_phase") or "unknown",
            "last_valid_phase": selected.get("last_valid_phase") or "unknown",
            "updatedAt": selected.get("updated_at"),
            "updated_at": selected.get("updated_at"),
            "frameRole": frame_role,
            "frameUrl": selected.get("frame_url"),
            "href": href,
            "hostname": hostname,
            "isTopFrame": bool(selected.get("is_top_frame")),
            "bridgeStatus": selected.get("bridge_status") or "missing",
            "pingLoaded": bool(selected.get("ping_loaded")),
            "stateSource": "marker_report",
            "signals": {
                "userAvatarVisible": bool(selected.get("signals_user_avatar")),
                "continueCount": int(selected.get("signals_continue") or 0),
                "loadingStrong": bool(selected.get("signals_loading")),
                "blockReady": bool(selected.get("signals_block")),
                "relevantIframeCount": int(selected.get("signals_iframe") or 0),
            },
            "diagnostics": {
                "href": href,
                "hostname": hostname,
                "frame_url": selected.get("frame_url"),
                "frame_index": selected.get("index"),
                "content_frame": selected.get("content_frame"),
                "selectedFrameUrl": selected.get("frame_url"),
                "selectedFrameName": selected.get("frame_name"),
                "selectedFrameRole": frame_role,
                "bridgeStatus": selected.get("bridge_status") or "missing",
                "pingLoaded": bool(selected.get("ping_loaded")),
                "updatedAt": selected.get("updated_at"),
                "frameCount": report.get("total_frames") or 0,
                "frameScan": deepcopy(report.get("frames") or []),
            },
        }
        if not self._has_useful_dom_marker_state(state):
            return None
        return state

    @staticmethod
    def _infer_site_from_hostname(hostname: object) -> str:
        normalized = str(hostname or "").strip().lower()
        if "paripe.io" in normalized:
            return "paripe"
        if "compinche.io" in normalized:
            return "compinche"
        if "ready4drive.com" in normalized:
            return "ready4drive"
        if "paripe" in normalized:
            return "paripe"
        if "compinche" in normalized:
            return "compinche"
        if "ready4drive" in normalized:
            return "ready4drive"
        return "unknown"

    def read_extension_ping_from_all_frames(self, page: object | None = None) -> dict:
        target_page = page or self.page
        frames = list(getattr(target_page, "frames", None) or [])
        if not frames:
            main_frame = getattr(target_page, "main_frame", None)
            if main_frame is not None:
                frames = [main_frame]
        report = {
            "total_frames": len(frames),
            "frames_with_ping": 0,
            "selected_frame": None,
            "frames": [],
        }
        main_frame = getattr(target_page, "main_frame", None)
        for index, frame in enumerate(frames):
            frame_entry = {
                "index": index,
                "frame_url": getattr(frame, "url", None),
                "frame_name": self._frame_name(frame),
                "is_top_frame": frame is main_frame,
                "ping": None,
                "error": None,
                "selected": False,
            }
            try:
                ping = frame.evaluate("() => window.__autoHeLlegadoPing ?? null")
            except Exception as exc:  # noqa: BLE001
                frame_entry["error"] = str(exc)
            else:
                if isinstance(ping, dict):
                    frame_entry["ping"] = ping
                    report["frames_with_ping"] += 1
                    if report["selected_frame"] is None:
                        frame_entry["selected"] = True
                        report["selected_frame"] = {
                            "frame_url": frame_entry["frame_url"],
                            "frame_name": frame_entry["frame_name"],
                            "is_top_frame": frame_entry["is_top_frame"],
                            "ping": deepcopy(ping),
                        }
            report["frames"].append(frame_entry)
        return report

    def debug_list_all_frames(self, page: object | None = None) -> dict:
        target_page = page or self.page
        frames = list(getattr(target_page, "frames", None) or [])
        main_frame = getattr(target_page, "main_frame", None)
        report = {
            "total_frames": len(frames),
            "frames": [],
        }
        for index, frame in enumerate(frames):
            parent_frame = self._frame_parent(frame)
            entry = {
                "index": index,
                "frame_url": getattr(frame, "url", None),
                "frame_name": self._frame_name(frame),
                "parent_frame_url": getattr(parent_frame, "url", None) if parent_frame is not None else None,
                "is_top_frame": frame is main_frame,
                "is_detached": self._frame_is_detached(frame),
                "ready_state": None,
                "title": None,
                "text_preview": None,
                "error": None,
            }
            try:
                details = frame.evaluate(
                    """() => ({
                        readyState: document.readyState,
                        title: document.title || "",
                        textPreview: document.body?.innerText?.slice(0, 200) || ""
                    })"""
                )
            except Exception as exc:  # noqa: BLE001
                entry["error"] = str(exc)
            else:
                if isinstance(details, dict):
                    entry["ready_state"] = details.get("readyState")
                    entry["title"] = details.get("title")
                    entry["text_preview"] = details.get("textPreview")
            report["frames"].append(entry)
        return report

    def capture_extension_debug(self, page: object | None = None, *, note: str | None = None) -> dict | None:
        snapshot = self.read_extension_debug_marker(page=page)
        if snapshot is None:
            return None
        extension_path = Path(self.extension_path).resolve() if self.extension_path else None
        manifest_path = extension_path / "manifest.json" if extension_path is not None else None
        latest_debug = BrowserManager.get_latest_extension_debug() or {}
        last_debug = self.get_last_extension_debug() or {}
        browser_args = list(latest_debug.get("browser_args") or [])
        marker_report = dict(last_debug.get("marker_report") or latest_debug.get("marker_report") or {})
        ping_report = dict(last_debug.get("ping_report") or latest_debug.get("ping_report") or {})
        frame_debug_report = dict(last_debug.get("frame_debug_report") or latest_debug.get("frame_debug_report") or {})
        frame_debug_error = None
        with suppress(Exception):
            marker_report = self.read_content_markers_from_all_frames(page=page)
        with suppress(Exception):
            ping_report = self.read_extension_ping_from_all_frames(page=page)
        try:
            frame_debug_report = self.debug_list_all_frames(page=page)
        except Exception as exc:  # noqa: BLE001
            frame_debug_error = str(exc)
            if not frame_debug_report:
                frame_debug_report = {"total_frames": 0, "frames": [], "error": frame_debug_error}
            else:
                frame_debug_report = {
                    **frame_debug_report,
                    "error": frame_debug_error,
                }
        marker_selected = marker_report.get("selected_frame") or {}
        marker_active = bool(marker_selected.get("content_loaded")) and BrowserManager._marker_frame_has_useful_state(marker_selected)
        effective_extension_loaded = bool(self.extension_loaded or marker_active)
        effective_extension_mode = "dom_markers" if marker_active else str(latest_debug.get("extension_mode") or "unpacked").strip() or "unpacked"
        service_worker_status = (
            str(latest_debug.get("service_worker_status") or "").strip()
            or ("present" if self.extension_service_worker_url else "missing_non_blocking")
        )
        extension_validation_error = None
        if self.extension_enabled and not effective_extension_loaded:
            extension_validation_error = "No DOM marker found; extension may not be active in this profile"
        with self._extension_debug_lock:
            engine_history = deepcopy(self._engine_phase_history or [])
        payload = {
            "run_id": self.run_id,
            "note": note,
            "extension_enabled": self.extension_enabled,
            "extension_loaded": effective_extension_loaded,
            "extension_mode": effective_extension_mode,
            "extension_service_worker_url": self.extension_service_worker_url,
            "service_worker_status": service_worker_status,
            "extension_validation_error": extension_validation_error,
            "extension_path": self.extension_path,
            "browser_channel": BrowserManager._BROWSER_CHANNEL,
            "browser_executable": self._browser_executable(),
            "extension_dir": str(extension_path) if extension_path is not None else None,
            "extension_dir_is_absolute": bool(extension_path and extension_path.is_absolute()),
            "extension_path_exists": bool(extension_path and extension_path.exists()),
            "manifest_path": str(manifest_path) if manifest_path is not None else None,
            "manifest_exists": bool(manifest_path and manifest_path.exists()),
            "load_extension_arg_present": self._has_extension_launch_arg(browser_args, "--load-extension="),
            "disable_extensions_except_arg_present": self._has_extension_launch_arg(browser_args, "--disable-extensions-except="),
            "content_js_path": str(extension_path / "content.js") if extension_path is not None else None,
            "content_js_exists": bool(extension_path and (extension_path / "content.js").exists()),
            "browser_args": browser_args,
            "marker_report": marker_report,
            "engine_phase_history": engine_history,
            "ping_report": ping_report,
            "frame_debug_report": frame_debug_report,
            "frame_debug_error": frame_debug_error,
            **snapshot,
        }
        self.extension_loaded = effective_extension_loaded
        with self._extension_debug_lock:
            self._last_extension_debug = deepcopy(payload)
        BrowserManager.remember_extension_debug(payload)
        return payload

    def get_last_extension_debug(self) -> dict | None:
        with self._extension_debug_lock:
            return deepcopy(self._last_extension_debug)

    def record_engine_phase_usage(
        self,
        *,
        phase: str,
        source: str,
        note: str | None = None,
        state: dict | None = None,
    ) -> None:
        entry = {
            "phase": phase,
            "source": source,
            "note": note,
            "observedAt": str(int(time() * 1000)),
            "frameRole": (state or {}).get("frameRole"),
            "frameUrl": (state or {}).get("frameUrl"),
        }
        with self._extension_debug_lock:
            self._engine_phase_history = self._engine_phase_history or []
            self._engine_phase_history.append(entry)
            self._engine_phase_history = self._engine_phase_history[-10:]
            if self._last_extension_debug is not None:
                self._last_extension_debug["engine_phase_history"] = deepcopy(self._engine_phase_history)

    def _close_internal(self, *, force: bool) -> None:
        if self._closed:
            return
        self._closed = True
        if self.keep_open and not force:
            return
        if self.disconnect_only:
            with suppress(Exception):
                self.playwright.stop()
            return
        with suppress(Exception):
            self.page.close()
        with suppress(Exception):
            self.context.close()
        with suppress(Exception):
            if self.browser is not None:
                self.browser.close()
        with suppress(Exception):
            self.playwright.stop()
        if self.cleanup_profile_dir and self.profile_dir:
            with suppress(Exception):
                shutil.rmtree(self.profile_dir, ignore_errors=True)

    @staticmethod
    def _evaluate_observer_state(frame: object) -> dict | None:
        with suppress(Exception):
            return frame.evaluate("() => window.__autoHeLlegadoState ?? null")
        return None

    @staticmethod
    def _frame_name(frame: object) -> str | None:
        name = getattr(frame, "name", None)
        if callable(name):
            with suppress(Exception):
                return name()
        return name

    @staticmethod
    def _frame_parent(frame: object) -> object | None:
        parent = getattr(frame, "parent_frame", None)
        if callable(parent):
            with suppress(Exception):
                return parent()
        return parent

    @staticmethod
    def _frame_is_detached(frame: object) -> bool | None:
        checker = getattr(frame, "is_detached", None)
        if callable(checker):
            with suppress(Exception):
                return bool(checker())
        if isinstance(checker, bool):
            return checker
        return None

    @staticmethod
    def _marker_frame_score(frame_entry: dict) -> tuple[int, int, int, int]:
        phase = frame_entry.get("phase") or "unknown"
        site = frame_entry.get("site") or "unknown"
        has_signal = any(
            (
                frame_entry.get("signals_user_avatar"),
                int(frame_entry.get("signals_continue") or 0) > 0,
                frame_entry.get("signals_loading"),
                frame_entry.get("signals_block"),
                int(frame_entry.get("signals_iframe") or 0) > 0,
            )
        )
        return (
            1 if phase != "unknown" else 0,
            1 if site != "unknown" else 0,
            1 if has_signal else 0,
            1 if frame_entry.get("content_loaded") else 0,
        )

    @classmethod
    def _select_best_marker_frame(cls, frames: list[dict]) -> int | None:
        best_index = None
        best_score = None
        for index, frame_entry in enumerate(frames):
            if not frame_entry.get("content_loaded"):
                continue
            score = cls._marker_frame_score(frame_entry)
            if best_score is None or score > best_score:
                best_score = score
                best_index = index
        return best_index

    @classmethod
    def _is_valid_observer_state(cls, state: dict | None) -> bool:
        if not isinstance(state, dict):
            return False
        diagnostics = state.get("diagnostics")
        diagnostics_href = diagnostics.get("href") if isinstance(diagnostics, dict) else None
        href = state.get("href") or diagnostics_href
        if href:
            return True
        phase = state.get("phase")
        site = state.get("site")
        return phase not in (None, "", "unknown") or site not in (None, "", "unknown")

    @classmethod
    def _should_prefer_dom_marker_state(cls, window_state: dict | None, dom_marker_state: dict | None) -> bool:
        if not isinstance(dom_marker_state, dict):
            return False
        if not isinstance(window_state, dict):
            return True
        window_phase = window_state.get("phase") or "unknown"
        window_site = window_state.get("site") or "unknown"
        if window_phase != "unknown" or window_site != "unknown":
            return False
        dom_phase = dom_marker_state.get("phase") or "unknown"
        dom_site = dom_marker_state.get("site") or "unknown"
        dom_signals = dom_marker_state.get("signals") or {}
        dom_has_signal = any(
            (
                dom_signals.get("userAvatarVisible"),
                int(dom_signals.get("continueCount") or 0) > 0,
                dom_signals.get("loadingStrong"),
                dom_signals.get("blockReady"),
                int(dom_signals.get("relevantIframeCount") or 0) > 0,
            )
        )
        return dom_phase != "unknown" or dom_site != "unknown" or dom_has_signal

    @staticmethod
    def _has_useful_dom_marker_state(state: dict | None) -> bool:
        if not isinstance(state, dict):
            return False
        phase = state.get("phase") or "unknown"
        site = state.get("site") or "unknown"
        signals = state.get("signals") or {}
        has_signal = any(
            (
                signals.get("userAvatarVisible"),
                int(signals.get("continueCount") or 0) > 0,
                signals.get("loadingStrong"),
                signals.get("blockReady"),
                int(signals.get("relevantIframeCount") or 0) > 0,
            )
        )
        return phase != "unknown" or site != "unknown" or has_signal

    @classmethod
    def _enrich_observer_state(
        cls,
        state: dict,
        *,
        frame: object | None,
        is_top_frame: bool,
        frame_count: int,
        frame_scan: list[dict],
    ) -> dict:
        enriched = deepcopy(state)
        diagnostics = deepcopy(enriched.get("diagnostics")) if isinstance(enriched.get("diagnostics"), dict) else {}
        frame_url = getattr(frame, "url", None) if frame is not None else None
        frame_name = cls._frame_name(frame) if frame is not None else None
        frame_role = "top" if is_top_frame else "iframe"
        enriched["frame_url"] = frame_url
        enriched["frame_name"] = frame_name
        enriched["frame_role"] = frame_role
        diagnostics.setdefault("frameCount", frame_count)
        diagnostics["selectedFrameUrl"] = frame_url
        diagnostics["selectedFrameName"] = frame_name
        diagnostics["selectedFrameRole"] = frame_role
        diagnostics["frameScan"] = deepcopy(frame_scan)
        enriched["diagnostics"] = diagnostics
        return enriched

    def _browser_executable(self) -> str | None:
        browser_type = getattr(self.browser, "browser_type", None)
        executable_path = getattr(browser_type, "executable_path", None)
        if callable(executable_path):
            with suppress(Exception):
                value = executable_path()
                return str(value) if value else None
        if executable_path:
            return str(executable_path)
        return None

    @staticmethod
    def _is_playwright_bundled_chromium(executable_path: str | None) -> bool:
        normalized = str(executable_path or "").replace("/", "\\").lower()
        return "ms-playwright" in normalized

    @staticmethod
    def _is_real_google_chrome_executable(executable_path: str | None) -> bool:
        normalized = str(executable_path or "").replace("/", "\\").lower()
        if normalized.endswith("\\google\\chrome\\application\\chrome.exe"):
            return True
        return "/google chrome.app/contents/macos/google chrome" in str(executable_path or "").lower()

    @staticmethod
    def _has_extension_launch_arg(args: list[str], prefix: str) -> bool:
        return any(str(arg).startswith(prefix) for arg in args)


class BrowserManager:
    _BROWSER_CHANNEL = "chrome"
    _DEFAULT_WINDOW_WIDTH = 1440
    _DEFAULT_WINDOW_HEIGHT = 960
    _sessions: list[BrowserSession] = []
    _sessions_lock = threading.Lock()
    _latest_extension_debug: dict | None = None
    _current_run_id: int = 0

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()

    def open_clean_session(
        self,
        *,
        keep_open: bool = False,
        enable_extension: bool = False,
        extension_overlay: bool = True,
    ) -> BrowserSession:
        run_id = self.current_run_id()
        self._configure_playwright_runtime()
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise RuntimeError(
                "Playwright no esta instalado. Ejecuta 'pip install -r requirements.txt' "
                "y asegúrate de tener Google Chrome instalado."
            ) from exc

        playwright = sync_playwright().start()
        extension_mode = "disabled"
        extension_path = self._get_extension_dir() if enable_extension else None
        manifest_path = extension_path / "manifest.json" if extension_path is not None else None
        manifest_payload = self._load_manifest_payload(manifest_path)
        content_script_files = self._manifest_content_script_files(manifest_payload)
        resolved_extension_dir = extension_path.resolve() if extension_path is not None else None
        browser_launch_args: list[str] = []
        browser_channel = self._BROWSER_CHANNEL
        chrome_profile_dir: Path | None = None
        chrome_executable_path: Path | None = None
        profile_dir: Path | None = None
        installed_extensions: list[dict] = []
        expected_extension_visible = False
        connection_mode = "launch"
        chrome_debug_port: int | None = None
        service_worker_status = "not_applicable"
        extension_validation_error: str | None = None
        background_page_urls: list[str] = []

        if enable_extension and self._use_installed_chrome_profile_extension():
            extension_mode = "installed_profile"
            chrome_profile_dir = self._get_required_chrome_profile_dir()
            chrome_executable_path = self._get_configured_chrome_executable_path()
            browser_channel = "chrome"
            browser_launch_args = self._build_installed_profile_launch_args()
        elif enable_extension:
            extension_mode = "unpacked"
            if extension_path is None:
                self.remember_extension_debug(
                    {
                        "note": "extension_path_missing",
                        "extension_enabled": True,
                        "extension_mode": extension_mode,
                        "extension_loaded": False,
                        "extension_service_worker_url": None,
                        "extension_path": str(PROJECT_ROOT / "browser_extension"),
                        "extension_path_exists": False,
                        "manifest_path": str(PROJECT_ROOT / "browser_extension" / "manifest.json"),
                        "manifest_exists": False,
                        "state": None,
                        "marker": None,
                        "overlayPresent": False,
                        "overlayFramePresent": False,
                    }
                )
                playwright.stop()
                raise RuntimeError(
                    "La extension de navegador esta habilitada, pero no existe la carpeta "
                    f"'{PROJECT_ROOT / 'browser_extension'}'."
                )
            browser_launch_args = self._build_browser_launch_args(
                self._build_extension_launch_args(
                    extension_path,
                    extension_overlay=extension_overlay,
                )
            )
        else:
            chrome_executable_path = self._get_optional_real_chrome_executable_path()
            browser_launch_args = self._build_browser_launch_args()

        if enable_extension and extension_mode == "unpacked" and manifest_path is not None and not manifest_path.exists():
            self.remember_extension_debug(
                {
                    "note": "extension_manifest_missing",
                    "extension_enabled": True,
                    "extension_mode": extension_mode,
                    "extension_loaded": False,
                    "extension_service_worker_url": None,
                    "extension_path": str(resolved_extension_dir),
                    "extension_dir": str(resolved_extension_dir),
                    "extension_dir_is_absolute": True,
                    "extension_path_exists": True,
                    "manifest_path": str(manifest_path),
                    "manifest_exists": False,
                    "load_extension_arg_present": self._has_extension_launch_arg(browser_launch_args, "--load-extension="),
                    "disable_extensions_except_arg_present": self._has_extension_launch_arg(browser_launch_args, "--disable-extensions-except="),
                    "state": None,
                    "marker": None,
                    "overlayPresent": False,
                    "overlayFramePresent": False,
                }
            )
            playwright.stop()
            raise RuntimeError(
                "La extension de navegador esta habilitada, pero falta "
                f"'{manifest_path}'."
            )

        if enable_extension and extension_mode == "unpacked" and extension_path is not None:
            profile_dir = self._get_extension_profile_dir(run_id=run_id)
            self._emit_launch_diagnostics(
                with_extension=True,
                extension_dir=resolved_extension_dir,
                args=browser_launch_args,
            )
            try:
                context = playwright.chromium.launch_persistent_context(
                    str(profile_dir),
                    channel=browser_channel,
                    headless=False,
                    ignore_https_errors=True,
                    no_viewport=True,
                    args=browser_launch_args,
                )
                
            except Exception as exc:
                playwright.stop()
                raise RuntimeError(
                    "No se pudo abrir Google Chrome con el perfil persistente configurado para la extension. "
                    "Verifica que Google Chrome este instalado y que el perfil no este en uso."
                ) from exc
                
            context.add_init_script(
                script=(
                    "window.localStorage.setItem("
                    "'autoHeLlegado.overlayEnabled', "
                    f"'{ 'true' if extension_overlay else 'false' }'"
                    ");"
                )
            )
            service_worker_url = self._detect_extension_service_worker(context)
            service_worker_urls = self._collect_service_worker_urls(context)
            service_worker_status = "present" if service_worker_url else "missing_blocking"
            browser = context.browser
            page = context.pages[0] if context.pages else context.new_page()
        elif enable_extension and extension_mode == "installed_profile":
            self._emit_profile_launch_diagnostics(chrome_profile_dir)
            self._emit_launch_diagnostics(
                with_extension=True,
                extension_dir=resolved_extension_dir,
                args=browser_launch_args,
            )
            try:
                browser, context, page = self._connect_or_launch_installed_profile_browser(
                    playwright=playwright,
                    chrome_profile_dir=chrome_profile_dir,
                    chrome_executable_path=chrome_executable_path,
                    browser_launch_args=browser_launch_args,
                )
            except Exception as exc:
                playwright.stop()
                raise RuntimeError(
                    "No se pudo abrir Google Chrome con el perfil persistente configurado para la extension. "
                    "Verifica que Google Chrome este instalado y que el perfil no este en uso."
                ) from exc
            connection_mode = "cdp"
            chrome_debug_port = _CHROME_DEBUG_PORT
            service_worker_urls = self._collect_service_worker_urls(context)
            background_page_urls = self._collect_background_page_urls(context)
            self._emit_profile_runtime_diagnostics(
                service_worker_urls=service_worker_urls,
                background_page_urls=background_page_urls,
            )
            service_worker_url = self._find_extension_service_worker_url(service_worker_urls)
            service_worker_status = "present" if service_worker_url else "missing_non_blocking"
        else:
            self._emit_launch_diagnostics(
                with_extension=False,
                extension_dir=None,
                args=browser_launch_args,
            )
            try:
                launch_kwargs = {
                    "headless": False,
                    "args": browser_launch_args,
                }
                if chrome_executable_path is not None:
                    launch_kwargs["executable_path"] = str(chrome_executable_path)
                else:
                    launch_kwargs["channel"] = browser_channel
                browser = playwright.chromium.launch(**launch_kwargs)
            except Exception as exc:
                playwright.stop()
                raise RuntimeError(
                    "No se pudo abrir Google Chrome. Verifica que Google Chrome esté instalado "
                    "y disponible para Playwright."
                ) from exc
            context = browser.new_context(
                ignore_https_errors=True,
                no_viewport=True,
            )
            page = context.new_page()
            service_worker_url = None
            service_worker_urls = []
            installed_extensions = []
            expected_extension_visible = False
            background_page_urls = []

        session = BrowserSession(
            playwright=playwright,
            browser=browser,
            context=context,
            page=page,
            keep_open=keep_open,
            extension_enabled=enable_extension,
            extension_path=str(resolved_extension_dir) if resolved_extension_dir is not None else None,
            extension_loaded=bool(service_worker_url or expected_extension_visible),
            extension_service_worker_url=service_worker_url,
            run_id=run_id,
            profile_dir=(
                str(profile_dir)
                if profile_dir is not None
                else str(chrome_profile_dir)
                if chrome_profile_dir is not None
                else None
            ),
            cleanup_profile_dir=profile_dir is not None,
            disconnect_only=extension_mode == "installed_profile" and connection_mode == "cdp",
        )
        if extension_mode == "installed_profile" and connection_mode == "cdp":
            browser_executable_actual = str(chrome_executable_path)
        else:
            browser_executable_actual = session._browser_executable()
            if browser_executable_actual is None and chrome_executable_path is not None:
                browser_executable_actual = str(chrome_executable_path)

        using_real_chrome = self._is_real_google_chrome_executable(browser_executable_actual)
        uses_playwright_chromium = self._is_playwright_bundled_chromium(browser_executable_actual)
        if not enable_extension:
            print(f"Launching browser mode=traditional configured_executable={str(chrome_executable_path) if chrome_executable_path is not None else '--'}")
            print(f"Traditional browser actual={browser_executable_actual or '--'}")

        if extension_mode == "installed_profile" and not using_real_chrome:
            with suppress(Exception):
                session.shutdown()
            raise RuntimeError(
                "Extension mode must use real Google Chrome executable_path"
            )
        self.remember_extension_debug(
            {
                "run_id": run_id,
                "note": "browser_session_opened" if enable_extension else "extension_disabled_by_config",
                "cache_mode": "clean_only",
                "cache_only_available": False,
                "extension_enabled": session.extension_enabled,
                "extension_mode": extension_mode,
                "extension_loaded": session.extension_loaded,
                "extension_service_worker_url": session.extension_service_worker_url,
                "service_worker_urls": service_worker_urls,
                "service_worker_status": service_worker_status,
                "background_page_urls": background_page_urls,
                "extension_validation_error": extension_validation_error,
                "installed_extensions": installed_extensions if enable_extension and extension_mode == "installed_profile" else [],
                "expected_extension_visible": expected_extension_visible if enable_extension and extension_mode == "installed_profile" else False,
                "extension_expected": bool(enable_extension and extension_mode == "installed_profile"),
                "extension_path": session.extension_path,
                "browser_executable_configured": str(chrome_executable_path) if chrome_executable_path is not None else None,
                "browser_executable": browser_executable_actual,
                "browser_executable_actual": browser_executable_actual,
                "using_real_chrome": using_real_chrome,
                "uses_playwright_chromium": uses_playwright_chromium,
                "connection_mode": connection_mode,
                "chrome_debug_port": chrome_debug_port,
                "extension_dir": str(resolved_extension_dir) if resolved_extension_dir is not None else None,
                "extension_dir_is_absolute": bool(resolved_extension_dir and resolved_extension_dir.is_absolute()),
                "profile_dir": session.profile_dir,
                "chrome_profile_dir": str(chrome_profile_dir) if chrome_profile_dir is not None else None,
                "browser_channel": browser_channel,
                "window_size": {
                    "width": self._DEFAULT_WINDOW_WIDTH,
                    "height": self._DEFAULT_WINDOW_HEIGHT,
                },
                "viewport_mode": "native_window",
                "browser_args": browser_launch_args,
                "load_extension_arg_present": self._has_extension_launch_arg(browser_launch_args, "--load-extension="),
                "disable_extensions_except_arg_present": self._has_extension_launch_arg(browser_launch_args, "--disable-extensions-except="),
                "extension_path_exists": bool(
                    chrome_profile_dir.exists()
                    if chrome_profile_dir is not None
                    else extension_path and extension_path.exists()
                ),
                "manifest_path": str(manifest_path) if manifest_path is not None else None,
                "manifest_exists": bool(manifest_path and manifest_path.exists()),
                "content_js_path": str(extension_path / "content.js") if extension_path is not None else None,
                "content_js_exists": bool(extension_path and (extension_path / "content.js").exists()),
                "manifest_content_scripts_js": content_script_files,
                "engine_phase_history": [],
                "marker_report": None,
                "ping_report": None,
                "state": None,
                "marker": None,
                "overlayPresent": False,
                "overlayFramePresent": False,
            }
        )
        self._register_session(session)
        return session

    def open_extension_session(
        self,
        *,
        keep_open: bool = False,
        extension_overlay: bool = True,
    ) -> BrowserSession:
        return self.open_clean_session(
            keep_open=keep_open,
            enable_extension=True,
            extension_overlay=extension_overlay,
        )

    def prepare_chrome_extension_profile(self) -> BrowserSession:
        self._configure_playwright_runtime()
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise RuntimeError(
                "Playwright no esta instalado. Ejecuta 'pip install -r requirements.txt' "
                "y asegúrate de tener Google Chrome instalado."
            ) from exc

        chrome_profile_dir = self._get_required_chrome_profile_dir()
        browser_channel = "chrome"
        browser_launch_args = self._build_installed_profile_launch_args()
        self._emit_launch_diagnostics(
            with_extension=True,
            extension_dir=chrome_profile_dir,
            args=browser_launch_args,
        )
        playwright = sync_playwright().start()
        try:
            context = playwright.chromium.launch_persistent_context(
                str(chrome_profile_dir),
                channel=browser_channel,
                headless=False,
                ignore_https_errors=True,
                no_viewport=True,
                args=browser_launch_args,
            )
        except Exception as exc:
            playwright.stop()
            raise RuntimeError(
                "No se pudo abrir Google Chrome con el perfil persistente configurado para preparar la extension. "
                "Verifica que Google Chrome este instalado y que el perfil no este en uso."
            ) from exc

        browser = context.browser
        page = context.pages[0] if context.pages else context.new_page()
        page.goto("chrome://extensions", wait_until="load", timeout=30_000)
        service_worker_urls = self._collect_service_worker_urls(context)
        service_worker_url = self._find_extension_service_worker_url(service_worker_urls)
        installed_extensions = self._read_extensions_page_entries(page)
        session = BrowserSession(
            playwright=playwright,
            browser=browser,
            context=context,
            page=page,
            keep_open=True,
            extension_enabled=True,
            extension_path=str(chrome_profile_dir),
            extension_loaded=bool(service_worker_url),
            extension_service_worker_url=service_worker_url,
            run_id=self.current_run_id(),
            profile_dir=str(chrome_profile_dir),
            cleanup_profile_dir=False,
        )
        self.remember_extension_debug(
            {
                "run_id": self.current_run_id(),
                "note": "chrome_profile_preparation_opened",
                "extension_enabled": True,
                "extension_mode": "installed_profile",
                "extension_loaded": session.extension_loaded,
                "extension_service_worker_url": session.extension_service_worker_url,
                "service_worker_urls": service_worker_urls,
                "installed_extensions": installed_extensions,
                "expected_extension_visible": self._has_expected_extension_entry(installed_extensions),
                "extension_path": session.extension_path,
                "extension_dir": None,
                "extension_dir_is_absolute": False,
                "profile_dir": session.profile_dir,
                "chrome_profile_dir": str(chrome_profile_dir),
                "browser_channel": browser_channel,
                "browser_args": browser_launch_args,
                "load_extension_arg_present": False,
                "disable_extensions_except_arg_present": False,
                "extension_path_exists": chrome_profile_dir.exists(),
                "manifest_path": None,
                "manifest_exists": False,
                "content_js_path": None,
                "content_js_exists": False,
                "engine_phase_history": [],
                "marker_report": None,
                "ping_report": None,
                "state": None,
                "marker": None,
                "overlayPresent": False,
                "overlayFramePresent": False,
            }
        )
        self._register_session(session)
        return session

    def open_chrome_extension_smoke_test(self) -> dict:
        self._configure_playwright_runtime()
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise RuntimeError(
                "Playwright no esta instalado. Ejecuta 'pip install -r requirements.txt' "
                "y asegÃºrate de tener Google Chrome instalado."
            ) from exc

        extension_dir = self._get_required_extension_dir()
        manifest_path = extension_dir / "manifest.json"
        service_worker_path = extension_dir / "service_worker.js"
        content_script_path = extension_dir / "content.js"
        launch_args = self._build_extension_smoke_test_args(extension_dir)
        payload = {
            "extension_dir": str(extension_dir),
            "extension_dir_is_absolute": extension_dir.is_absolute(),
            "manifest_path": str(manifest_path),
            "manifest_exists": manifest_path.exists(),
            "service_worker_path": str(service_worker_path),
            "service_worker_exists": service_worker_path.exists(),
            "content_js_path": str(content_script_path),
            "content_js_exists": content_script_path.exists(),
            "chrome": {},
            "chromium": {},
        }
        for channel in ("chrome", "chromium"):
            payload[channel] = self._run_extension_smoke_launch(
                channel=channel,
                extension_dir=extension_dir,
                launch_args=launch_args,
            )
        payload["chrome_service_worker"] = payload["chrome"].get("service_workers")
        payload["chromium_service_worker"] = payload["chromium"].get("service_workers")
        return payload

    @classmethod
    def shutdown_all(cls) -> None:
        with cls._sessions_lock:
            sessions = list(cls._sessions)
            cls._sessions = []
        for session in sessions:
            with suppress(Exception):
                session.shutdown()

    @classmethod
    def get_latest_session(cls) -> BrowserSession | None:
        # TODO(parallelism): this helper is intentionally "latest run" only. Replace with lookup by process_id/run_id
        # before enabling multiple active processes at the same time.
        with cls._sessions_lock:
            current_run_id = cls._current_run_id
            for session in reversed(cls._sessions):
                if session.run_id == current_run_id:
                    return session
            return None

    @classmethod
    def begin_new_run(cls, *, flow_engine: str | None = None) -> int:
        with cls._sessions_lock:
            cls._current_run_id += 1
            run_id = cls._current_run_id
            extension_dir = PROJECT_ROOT / "browser_extension"
            manifest_path = extension_dir / "manifest.json"
            extension_enabled = flow_engine == "extension"
            cls._latest_extension_debug = {
                "run_id": run_id,
                "note": "process_start_pending",
                "flow_engine": flow_engine,
                "extension_enabled": extension_enabled,
                "extension_loaded": False,
                "extension_service_worker_url": None,
                "extension_path": str(extension_dir.resolve()) if extension_enabled else None,
                "extension_dir": str(extension_dir.resolve()) if extension_enabled else None,
                "extension_dir_is_absolute": extension_enabled,
                "extension_path_exists": extension_enabled and extension_dir.exists(),
                "manifest_path": str(manifest_path.resolve()) if extension_enabled else None,
                "manifest_exists": extension_enabled and manifest_path.exists(),
                "engine_phase_history": [],
                "state": None,
                "marker": None,
                "overlayPresent": False,
                "overlayFramePresent": False,
            }
            return run_id

    @classmethod
    def current_run_id(cls) -> int:
        with cls._sessions_lock:
            return cls._current_run_id

    @classmethod
    def remember_extension_debug(cls, payload: dict | None) -> None:
        if payload is None:
            return
        with cls._sessions_lock:
            payload_run_id = int(payload.get("run_id") or cls._current_run_id)
            if payload_run_id != cls._current_run_id:
                return
            payload_copy = deepcopy(payload)
            payload_copy["run_id"] = payload_run_id
            cls._latest_extension_debug = payload_copy

    @classmethod
    def get_latest_extension_debug(cls) -> dict | None:
        # TODO(parallelism): this returns shared latest debug state, not per execution. Do not use for real parallelism.
        with cls._sessions_lock:
            return deepcopy(cls._latest_extension_debug)

    def _configure_playwright_runtime(self) -> None:
        if os.getenv("PLAYWRIGHT_BROWSERS_PATH"):
            return
        bundled_browsers = PROJECT_ROOT / "ms-playwright"
        if bundled_browsers.exists():
            os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(bundled_browsers)

    def _use_installed_chrome_profile_extension(self) -> bool:
        return bool(self._settings.use_chrome_profile_extension)

    def _get_required_chrome_profile_dir(self) -> Path:
        profile_dir = self._settings.chrome_profile_dir
        if profile_dir is None:
            raise RuntimeError(
                "AUTO_HE_LLEGADO_USE_CHROME_PROFILE_EXTENSION=true, but AUTO_HE_LLEGADO_CHROME_PROFILE_DIR is not configured."
            )
        resolved = profile_dir.expanduser().resolve()
        if not resolved.exists():
            raise RuntimeError(
                "AUTO_HE_LLEGADO_CHROME_PROFILE_DIR does not exist: "
                f"{resolved}"
            )
        return resolved

    def _get_configured_chrome_executable_path(self) -> Path:
        executable_path = getattr(self._settings, "chrome_executable_path", None)
        if executable_path is None:
            raise RuntimeError(
                "AUTO_HE_LLEGADO_CHROME_EXECUTABLE_PATH is required for installed_profile extension mode."
            )
        resolved = executable_path.expanduser().resolve()
        if not resolved.exists():
            raise RuntimeError(
                "AUTO_HE_LLEGADO_CHROME_EXECUTABLE_PATH does not exist: "
                f"{resolved}"
            )
        if not self._is_real_google_chrome_executable(str(resolved)):
            raise RuntimeError(
                "Extension mode must use real Google Chrome, not Playwright bundled Chromium: "
                f"{resolved}"
            )
        return resolved

    def _get_optional_real_chrome_executable_path(self) -> Path | None:
        executable_path = getattr(self._settings, "chrome_executable_path", None)
        if executable_path in (None, ""):
            return None
        return self._get_configured_chrome_executable_path()

    @staticmethod
    def _is_playwright_bundled_chromium(executable_path: str | None) -> bool:
        normalized = str(executable_path or "").replace("/", "\\").lower()
        return "ms-playwright" in normalized or "chromium" in normalized

    @classmethod
    def _is_real_google_chrome_executable(cls, executable_path: str | None) -> bool:
        if not executable_path:
            return False
        candidate = Path(executable_path).expanduser()
        if not candidate.exists():
            return False
        normalized = str(candidate).replace("/", "\\").lower()
        if cls._is_playwright_bundled_chromium(normalized):
            return False
        executable_name = candidate.name.lower()
        if executable_name == "chrome.exe":
            return True
        if executable_name == "google chrome":
            return "google chrome.app" in str(candidate).lower()
        return False

    @classmethod
    def _build_installed_profile_cdp_command(
        cls,
        *,
        chrome_executable_path: Path,
        chrome_profile_dir: Path,
        browser_launch_args: list[str],
        chrome_debug_port: int = _CHROME_DEBUG_PORT,
    ) -> list[str]:
        return [
            str(chrome_executable_path),
            f"--remote-debugging-port={chrome_debug_port}",
            f"--user-data-dir={chrome_profile_dir}",
            "--no-first-run",
            *browser_launch_args,
            "https://paripe.io/app",
        ]

    @staticmethod
    def _cdp_endpoint_url(*, chrome_debug_port: int = _CHROME_DEBUG_PORT) -> str:
        return f"http://127.0.0.1:{chrome_debug_port}"

    @classmethod
    def _connect_or_launch_installed_profile_browser(
        cls,
        *,
        playwright: object,
        chrome_profile_dir: Path,
        chrome_executable_path: Path,
        browser_launch_args: list[str],
    ) -> tuple[object, object, object]:
        
        endpoint_url = cls._cdp_endpoint_url()

        browser = cls._try_connect_over_cdp(
            playwright=playwright,
            endpoint_url=endpoint_url,
        )

        if browser is None:
            raise RuntimeError(
                "No hay Chrome real abierto con CDP. "
                "Abre Chrome primero con --remote-debugging-port=9222 y vuelve a iniciar el proceso."
            )

        context = cls._wait_for_browser_context(browser)
        page = cls._wait_for_browser_page(context)
        
        return browser, context, page

    @classmethod
    def _try_connect_over_cdp(cls, *, playwright: object, endpoint_url: str) -> object | None:
        with suppress(Exception):
            return playwright.chromium.connect_over_cdp(endpoint_url)
        return None

    @classmethod
    def _wait_for_cdp_browser(cls, *, playwright: object, endpoint_url: str, timeout_seconds: float = 15.0) -> object:
        deadline = time() + timeout_seconds
        last_error: Exception | None = None
        while time() < deadline:
            try:
                return playwright.chromium.connect_over_cdp(endpoint_url)
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                sleep(0.25)
        raise RuntimeError(
            f"No se pudo conectar a Google Chrome via CDP en {endpoint_url}."
        ) from last_error

    @staticmethod
    def _wait_for_browser_context(browser: object, timeout_seconds: float = 10.0) -> object:
        deadline = time() + timeout_seconds
        while time() < deadline:
            contexts = list(getattr(browser, "contexts", []) or [])
            if contexts:
                return contexts[0]
            sleep(0.25)
        raise RuntimeError("Google Chrome se conecto por CDP, pero no expuso ningun browser context.")

    @staticmethod
    def _wait_for_browser_page(context: object, timeout_seconds: float = 10.0) -> object:
        with suppress(Exception):
            page = context.new_page()
            page.bring_to_front()
            try:
                page.goto("https://paripe.io/login", wait_until="commit", timeout=10_000)
            except Exception:
                pass
            page.wait_for_timeout(2_000)
            return page

        deadline = time() + timeout_seconds
        while time() < deadline:
            pages = list(getattr(context, "pages", []) or [])
            for page in reversed(pages):
                url = str(getattr(page, "url", "") or "")
                if "paripe.io" in url or "compinche.io" in url or "ready4drive.com" in url:
                    with suppress(Exception):
                        page.bring_to_front()
                    return page
            sleep(0.25)

        raise RuntimeError("Google Chrome se conecto por CDP, pero no expuso ninguna pagina util.")

    @classmethod
    def _run_extension_smoke_launch(
        cls,
        *,
        channel: str,
        extension_dir: Path,
        launch_args: list[str],
    ) -> dict:
        from playwright.sync_api import sync_playwright

        profile_dir = cls._get_extension_profile_dir(run_id=0)
        cls._emit_smoke_launch_diagnostics(
            channel=channel,
            extension_dir=extension_dir,
            launch_args=launch_args,
        )
        playwright = sync_playwright().start()
        context = None
        try:
            context = playwright.chromium.launch_persistent_context(
                str(profile_dir),
                channel=channel,
                headless=False,
                ignore_https_errors=True,
                no_viewport=True,
                args=launch_args,
            )
            page = context.pages[0] if context.pages else context.new_page()
            page.goto("chrome://extensions", wait_until="load", timeout=30_000)
            with suppress(Exception):
                page.wait_for_timeout(3_000)
            service_workers = [str(getattr(worker, "url", None) or "") for worker in list(context.service_workers)]
            page_urls = [str(getattr(item, "url", None) or "") for item in list(context.pages)]
            chrome_extension_targets = sorted(
                {
                    url
                    for url in service_workers + page_urls
                    if str(url).startswith("chrome-extension://")
                }
            )
            result = {
                "channel": channel,
                "profile_dir": str(profile_dir),
                "args": list(launch_args),
                "service_workers": service_workers,
                "pages": page_urls,
                "chrome_extension_targets": chrome_extension_targets,
                "extension_load_status": "loaded" if service_workers or chrome_extension_targets else "not_loaded",
            }
            cls._emit_smoke_launch_result(result)
            return result
        finally:
            with suppress(Exception):
                if context is not None:
                    context.close()
            with suppress(Exception):
                playwright.stop()

    @staticmethod
    def _get_extension_profile_dir(*, run_id: int) -> Path:
        profile_dir = DEFAULT_LOCAL_DATA_DIR / "browser_profiles" / f"chrome_extension_profile_run_{run_id}_{int(time() * 1000)}"
        profile_dir.mkdir(parents=True, exist_ok=True)
        return profile_dir

    @staticmethod
    def _get_extension_dir() -> Path | None:
        extension_dir = PROJECT_ROOT / "browser_extension"
        return extension_dir if extension_dir.exists() else None

    @classmethod
    def _get_required_extension_dir(cls) -> Path:
        extension_dir = cls._get_extension_dir()
        if extension_dir is None:
            raise RuntimeError(
                "No existe la carpeta de extension esperada en "
                f"'{PROJECT_ROOT / 'browser_extension'}'."
            )
        manifest_path = extension_dir / "manifest.json"
        if not manifest_path.exists():
            raise RuntimeError(f"Falta '{manifest_path}'.")
        return extension_dir.resolve()

    @staticmethod
    def _build_extension_launch_args(extension_dir: Path, *, extension_overlay: bool) -> list[str]:
        extension_path = str(extension_dir.resolve())
        args = [
            f"--disable-extensions-except={extension_path}",
            f"--load-extension={extension_path}",
        ]
        if not extension_overlay:
            args.append("--auto-he-llegado-overlay=off")
        return args

    @classmethod
    def _build_installed_profile_launch_args(cls) -> list[str]:
        return cls._build_browser_launch_args()

    @staticmethod
    def _build_installed_profile_launch_kwargs(
        *,
        chrome_profile_dir: Path,
        chrome_executable_path: Path,
        browser_launch_args: list[str],
    ) -> dict:
        return {
            "user_data_dir": str(chrome_profile_dir),
            "headless": False,
            "ignore_https_errors": True,
            "no_viewport": True,
            "args": browser_launch_args,
            "executable_path": str(chrome_executable_path),
        }

    @staticmethod
    def _build_extension_smoke_test_args(extension_dir: Path) -> list[str]:
        extension_path = str(extension_dir.resolve())
        return [
            f"--disable-extensions-except={extension_path}",
            f"--load-extension={extension_path}",
        ]

    @staticmethod
    def _has_extension_launch_arg(args: list[str], prefix: str) -> bool:
        return any(str(arg).startswith(prefix) for arg in args)

    @classmethod
    def _build_browser_launch_args(cls, extra_args: list[str] | None = None) -> list[str]:
        args = [
            f"--window-size={cls._DEFAULT_WINDOW_WIDTH},{cls._DEFAULT_WINDOW_HEIGHT}",
            "--window-position=40,40",
        ]
        if extra_args:
            args.extend(extra_args)
        return args

    @staticmethod
    def _emit_launch_diagnostics(
        *,
        with_extension: bool,
        extension_dir: Path | None,
        args: list[str],
    ) -> None:
        if with_extension:
            print("Launching Chrome WITH extension")
            print(f"extension_dir={extension_dir}")
        else:
            print("Launching Chrome WITHOUT extension")
        print(f"args={args}")

    @staticmethod
    def _emit_profile_launch_diagnostics(user_data_dir: Path) -> None:
        resolved = user_data_dir.resolve()
        print(f"LAUNCH PROFILE: {user_data_dir}")
        print(f"user_data_dir={user_data_dir}")
        print(f"user_data_dir_exists={user_data_dir.exists()}")
        print(f"user_data_dir_resolved={resolved}")

    @staticmethod
    def _emit_profile_runtime_diagnostics(
        *,
        service_worker_urls: list[str],
        background_page_urls: list[str],
    ) -> None:
        print(f"context.service_workers={service_worker_urls}")
        print(f"context.background_pages={background_page_urls}")
        if not service_worker_urls:
            print("PROFILE LOADED WITHOUT EXTENSION")

    @staticmethod
    def _emit_smoke_launch_diagnostics(
        *,
        channel: str,
        extension_dir: Path,
        launch_args: list[str],
    ) -> None:
        manifest_path = extension_dir / "manifest.json"
        service_worker_path = extension_dir / "service_worker.js"
        content_script_path = extension_dir / "content.js"
        print(f"[smoke:{channel}] extension_dir={extension_dir}")
        print(f"[smoke:{channel}] manifest_exists={manifest_path.exists()}")
        print(f"[smoke:{channel}] service_worker_exists={service_worker_path.exists()}")
        print(f"[smoke:{channel}] content_js_exists={content_script_path.exists()}")
        print(f"[smoke:{channel}] args={launch_args}")

    @staticmethod
    def _emit_smoke_launch_result(result: dict) -> None:
        channel = str(result.get("channel") or "unknown")
        print(f"[smoke:{channel}] service_workers={result.get('service_workers')}")
        print(f"[smoke:{channel}] pages={result.get('pages')}")
        print(f"[smoke:{channel}] chrome_extension_targets={result.get('chrome_extension_targets')}")
        print(f"[smoke:{channel}] extension_load_status={result.get('extension_load_status')}")

    @staticmethod
    def _detect_extension_service_worker(context: object) -> str | None:
        with suppress(Exception):
            service_workers = list(context.service_workers)
            if service_workers:
                return getattr(service_workers[0], "url", None)
        with suppress(Exception):
            service_worker = context.wait_for_event("serviceworker", timeout=5_000)
            return getattr(service_worker, "url", None)
        return None

    @staticmethod
    def _collect_service_worker_urls(context: object) -> list[str]:
        with suppress(Exception):
            return [
                str(getattr(worker, "url", None) or "")
                for worker in list(context.service_workers)
                if str(getattr(worker, "url", None) or "").strip()
            ]
        return []

    @staticmethod
    def _find_extension_service_worker_url(service_worker_urls: list[str]) -> str | None:
        for url in service_worker_urls:
            normalized = str(url or "").strip()
            if normalized.startswith("chrome-extension://") and normalized.endswith("/service_worker.js"):
                return normalized
        return None

    @classmethod
    def _marker_frame_has_useful_state(cls, frame_entry: dict) -> bool:
        phase = str(frame_entry.get("phase") or "unknown").strip() or "unknown"
        site = str(frame_entry.get("site") or "unknown").strip() or "unknown"
        has_signal = any(
            (
                frame_entry.get("signals_user_avatar"),
                int(frame_entry.get("signals_continue") or 0) > 0,
                frame_entry.get("signals_loading"),
                frame_entry.get("signals_block"),
                int(frame_entry.get("signals_iframe") or 0) > 0,
            )
        )
        return phase != "unknown" or site != "unknown" or has_signal

    @staticmethod
    def _collect_background_page_urls(context: object) -> list[str]:
        with suppress(Exception):
            return [
                str(getattr(page, "url", None) or "")
                for page in list(getattr(context, "background_pages", []) or [])
                if str(getattr(page, "url", None) or "").strip()
            ]
        return []

    @staticmethod
    def _read_extensions_page_entries(page: object) -> list[dict]:
        with suppress(Exception):
            payload = page.evaluate(
                """() => {
                    const visit = (root, results) => {
                        if (!root) return;
                        const nodes = root.querySelectorAll ? Array.from(root.querySelectorAll('*')) : [];
                        for (const node of nodes) {
                            if (node.tagName && node.tagName.toLowerCase() === 'extensions-item') {
                                const nameNode = node.shadowRoot?.querySelector('#name');
                                const versionNode = node.shadowRoot?.querySelector('#version');
                                results.push({
                                    id: node.getAttribute('id') || node.getAttribute('item-id') || null,
                                    name: nameNode?.textContent?.trim() || '',
                                    version: versionNode?.textContent?.trim() || '',
                                });
                            }
                            if (node.shadowRoot) {
                                visit(node.shadowRoot, results);
                            }
                        }
                    };
                    const results = [];
                    visit(document, results);
                    return results;
                }"""
            )
            if isinstance(payload, list):
                return [item for item in payload if isinstance(item, dict)]
        return []

    @staticmethod
    def _has_expected_extension_entry(entries: list[dict]) -> bool:
        expected = _EXPECTED_EXTENSION_NAME.strip().lower()
        for entry in entries:
            name = str(entry.get("name") or "").strip().lower()
            if name == expected:
                return True
        return False

    @staticmethod
    def _load_manifest_payload(manifest_path: Path | None) -> dict | None:
        if manifest_path is None or not manifest_path.exists():
            return None
        with suppress(Exception):
            return json.loads(manifest_path.read_text(encoding="utf-8"))
        return None

    @staticmethod
    def _manifest_content_script_files(manifest_payload: dict | None) -> list[str]:
        if not isinstance(manifest_payload, dict):
            return []
        content_scripts = manifest_payload.get("content_scripts")
        if not isinstance(content_scripts, list):
            return []
        files: list[str] = []
        for entry in content_scripts:
            js_entries = entry.get("js") if isinstance(entry, dict) else None
            if not isinstance(js_entries, list):
                continue
            files.extend(str(item) for item in js_entries)
        return files

    @classmethod
    def _register_session(cls, session: BrowserSession) -> None:
        original_close = session.close
        original_shutdown = session.shutdown

        def close_and_unregister() -> None:
            try:
                original_close()
            finally:
                with cls._sessions_lock:
                    cls._sessions = [item for item in cls._sessions if item is not session]

        def shutdown_and_unregister() -> None:
            try:
                original_shutdown()
            finally:
                with cls._sessions_lock:
                    cls._sessions = [item for item in cls._sessions if item is not session]

        session.close = close_and_unregister
        session.shutdown = shutdown_and_unregister
        with cls._sessions_lock:
            cls._sessions.append(session)
