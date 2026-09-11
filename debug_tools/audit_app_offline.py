"""Offline audit probes. No real accounts, network calls, uploads or deletions."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from threading import current_thread
from time import monotonic, sleep
from types import SimpleNamespace as NS
from unittest.mock import patch

from automation.browser_manager import BrowserManager
from automation.compinche_site import CompincheSite
from automation.paripe_site import ParipeSite
from automation.ready4drive_site import Ready4DriveSite
from core.models import LocalConfig, ProcessExecutionRequest, SiteExecutionResult
from services.access_service import AccessService
from services.auth_context import AuthSession
from services.photo_review_service import PhotoReviewService
from services.process_service import ProcessService
from services.user_access_admin_service import UserAccessAdminService
from services.video_contribution_service import VideoContributionService
from ui.main_app.form_panel import FormPanel
from ui.main_app.photo_review_panel import PhotoReviewPanel
from ui.main_app.window import MainAppWindow
from ui.uploader.panel import UploaderPanel


class Query:
    def __init__(self, name):
        self.name = name
        self.filters = {}
        self.bounds = (0, 999)
        self.max_rows = 100

    def select(self, *_args, **_kwargs):
        return self

    def order(self, *_args, **_kwargs):
        return self

    def eq(self, key, value):
        self.filters[key] = value
        return self

    def in_(self, key, value):
        self.filters[key] = list(value)
        return self

    def gte(self, *_args):
        return self

    def limit(self, value):
        self.max_rows = value
        return self

    def range(self, start, end):
        self.bounds = start, end
        return self


class Provider:
    def __init__(self, *, users=1, candidates=0, delay=0):
        self.client = self
        self.users = users
        self.candidates = candidates
        self.delay = delay
        self.calls = []

    def table(self, name):
        return Query(name)

    def rpc(self, name, *_args):
        return Query(name)

    def execute(self, query):
        self.calls.append((query.name, current_thread().name))
        sleep(self.delay)
        if query.name == "get_video_requirement_policy":
            return [{"enabled": True, "days": 7}]
        if query.name == "profiles":
            return [{"id": f"user-{index}", "approved": True, "role": "member"} for index in range(min(self.users, query.max_rows))]
        if query.name == "batches":
            if isinstance(query.filters.get("user_id"), list):
                return [{"id": f"batch-{user_id}", "user_id": user_id, "status": "accepted"} for user_id in query.filters["user_id"]]
            return [{"id": "batch", "status": "accepted"}]
        if query.name == "candidates":
            start, end = query.bounds
            return [{"id": f"candidate-{index}"} for index in range(start, min(end + 1, self.candidates))]
        raise AssertionError(f"Unexpected offline query: {query.name}")


def session(role="member"):
    return AuthSession(user_id="offline-user", email="offline@example.invalid", access_token="", refresh_token="", role=role, approved=True)


def access_service(provider):
    service = AccessService.__new__(AccessService)
    service._client_provider = provider
    service._settings = NS(supabase_profiles_table="profiles", supabase_photo_batches_table="batches")
    return service


def probe_access():
    results = {}
    for role in ("member", "admin"):
        provider = Provider(delay=0.05)
        snapshot = access_service(provider).get_access_snapshot(session(role)) if role == "member" else None
        provider.calls.clear()
        window = NS(
            _auth_session=session(role),
            _access_service=access_service(provider),
            _access_snapshot=snapshot,
            _process_access_block_reason="",
            refresh_process_access_state=lambda: None,
        )
        started = monotonic()
        allowed = MainAppWindow._process_access_allows_start(window)
        results[role] = {"allowed": allowed, "elapsed_ms": round((monotonic() - started) * 1000), "queries": len(provider.calls), "query_threads": sorted({thread for _, thread in provider.calls})}
    return results


def probe_timers():
    pending = []
    window = NS(_is_closing=False, _slots={}, _extension_status_refresh_scheduled=False, _refresh_admin_diagnostics_if_open=lambda: None)
    window.refresh_extension_status = lambda: MainAppWindow.refresh_extension_status(window)
    window._run_scheduled_extension_status_refresh = lambda: MainAppWindow._run_scheduled_extension_status_refresh(window)
    window._schedule_extension_status_refresh = lambda delay_ms=1000: MainAppWindow._schedule_extension_status_refresh(window, delay_ms)
    window._safe_after = lambda _delay, callback: pending.append(callback)
    with patch.object(BrowserManager, "get_latest_session", return_value=None), patch.object(BrowserManager, "get_latest_extension_debug", return_value={}):
        window.refresh_extension_status()
        initial = len(pending)
        for _ in range(10):
            window.refresh_extension_status()  # start_process
            window.refresh_extension_status()  # _finish_process
        after_runs = len(pending)
        for _ in range(3):
            tick, pending[:] = list(pending), []
            for callback in tick:
                callback()
        return {"initial_chains": initial, "after_10_start_finish_pairs": after_runs, "after_3_ticks": len(pending)}


def probe_admin_users():
    results = {}
    for count in (1, 25, 100):
        provider = Provider(users=count)
        service = UserAccessAdminService.__new__(UserAccessAdminService)
        service._client_provider = provider
        service._access_service = access_service(provider)
        service._table = "profiles"
        service._batches_table = "batches"
        users = service.list_users()
        results[str(count)] = {"returned": len(users), "queries": len(provider.calls)}
    return results


class Log:
    def __init__(self, delay):
        self.delay = delay
        self.calls = []

    def start_process(self, **_kwargs):
        self.calls.append("start")
        sleep(self.delay)
        return NS(id=1)

    def update_process(self, _id, **kwargs):
        self.calls.append(kwargs["phase"])
        sleep(self.delay)
        return NS(id=1)

    def finish_process(self, _id, **_kwargs):
        self.calls.append("finish")
        sleep(self.delay)
        return NS(id=1)


class Runner:
    def execute_traditional(self, request, *, local_config, progress_callback):
        for _ in range(10):
            progress_callback("selfie_stage", "Offline progress")
        return SiteExecutionResult(success=True, message="Offline result", final_status="success", phase="final_result")

    execute_extension = execute_traditional

    def export_process_debug_state(self):
        return {}


def probe_logging():
    results = {}
    for delay in (0, 0.03):
        log = Log(delay)
        service = ProcessService(log_service=log, log_service_factory=lambda: log, local_config_service=NS(load=lambda: LocalConfig(agent_name="Offline", flow_engine="traditional")), last_result_service=NS(save_result=lambda _result: None), compinche_site=Runner(), paripe_site=Runner(), ready4drive_site=Runner())
        started = monotonic()
        result = service.execute(ProcessExecutionRequest(process_id="offline-audit", page_name="Compinche", action_name="He llegado", phone_number="8095551234", password="offline", agent_name="Offline", execution_mode="traditional"))
        results[str(delay)] = {"success": result.success, "elapsed_ms": round((monotonic() - started) * 1000), "writes": len(log.calls), "same_phase_updates": log.calls.count("selfie_stage")}
    return results


def probe_review():
    provider = Provider(candidates=5000)
    service = PhotoReviewService.__new__(PhotoReviewService)
    service._client_provider = provider
    service._candidates_table = "candidates"
    service._candidate_from_row = lambda row: row
    service._list_recent_batches = lambda: []
    service._count_candidates = lambda _status: 0
    received = []
    panel = NS(
        _review_service=service,
        _display_limit=PhotoReviewPanel.DISPLAY_BATCH_SIZE,
        DISPLAY_BATCH_SIZE=PhotoReviewPanel.DISPLAY_BATCH_SIZE,
        after=lambda _delay, callback: callback(),
        _apply_snapshot=received.append,
        _show_error=lambda error: (_ for _ in ()).throw(error),
    )
    PhotoReviewPanel._refresh_worker(panel, "pending")
    return {"downloaded_rows": len(received[0].candidates), "candidate_queries": len(provider.calls), "initial_visible_cards": PhotoReviewPanel.DISPLAY_BATCH_SIZE}


def probe_upload_error():
    callbacks, errors = [], []
    def fail_upload(*_args, **_kwargs):
        raise RuntimeError("Offline upload failure")
    panel = NS(_uploader_service=NS(upload_files=fail_upload), _selected_files=[], delete_local_checkbox=NS(get=lambda: False), _schedule_progress_update=lambda _: None, after=lambda _delay, callback: callbacks.append(callback), _handle_unexpected_error=errors.append)
    UploaderPanel._run_upload(panel)
    try:
        callbacks[0]()
    except Exception as error:
        return {"callback_error": type(error).__name__, "error_handler_calls": len(errors)}
    return {"callback_error": None, "error_handler_calls": len(errors)}


def probe_updater():
    calls = []
    def download():
        calls.append(current_thread().name)
        sleep(0.1)
        return NS(path=Path("offline-not-created.zip"))
    window = NS(
        _is_closing=False,
        _validate_updater_ready=lambda: None,
        _download_update_package_from_github=download,
        _launch_integrated_updater=lambda _path: False,
        _broadcast_status_message=lambda *_args, **_kwargs: None,
        _safe_after=lambda _delay, callback, **_kwargs: callback(),
    )
    window._request_external_update_worker = lambda: MainAppWindow._request_external_update_worker(window)
    window._finish_external_update_request = lambda downloaded_update: MainAppWindow._finish_external_update_request(window, downloaded_update)
    started = monotonic()
    MainAppWindow.request_external_update(window)
    blocked_ms = round((monotonic() - started) * 1000)
    sleep(0.15)
    return {"download_threads": calls, "blocked_ms": blocked_ms}


def probe_video_failure():
    failed, batches = [], []
    service = VideoContributionService.__new__(VideoContributionService)
    service._settings = NS(video_submission_mode="drive", video_duplicate_similarity_threshold=0.9, video_duplicate_hamming_threshold=8, video_min_duration_seconds=1)
    fingerprint = NS(duration_seconds=12, sha256="offline", size_bytes=100, width=10, height=10, as_payload=lambda: {})
    service._fingerprint_service = NS(build=lambda _: fingerprint, find_duplicate=lambda *_args, **_kwargs: None)
    def create_batch(**_kwargs):
        batch = NS(id="offline-batch", status="processing")
        batches.append(batch)
        return batch
    def mark_failed(_batch_id, message):
        batches[0].status = "failed"
        failed.append(message)
    service._review_service = NS(list_video_fingerprint_candidates=lambda: [], create_batch=create_batch, mark_batch_failed=mark_failed)
    def fail_delivery(*_args, **_kwargs):
        raise RuntimeError("Offline Drive failure")
    service._delivery_service = NS(upload_video=fail_delivery)
    try:
        service.submit_video("offline-not-created.mp4", session=session())
    except RuntimeError:
        pass
    return {"batch_state": batches[0].status, "mark_failed_calls": len(failed), "state_allows_access": batches[0].status in AccessService.ACTIVE_BATCH_STATUSES}


def probe_actions():
    result = {}
    for site_type in (CompincheSite, ParipeSite, Ready4DriveSite):
        site = site_type()
        result[site.site_name] = {action: site._get_action_spec(action).ui_name for action in FormPanel.ACTION_OPTIONS}
    return result


def probe_admin_access():
    results = {}
    for role, password in (("member", "offline"), ("admin", "wrong"), ("admin", "offline")):
        opened = []
        window = NS(_settings=NS(admin_access_password="offline"), _admin_password_dialog=None, _broadcast_status_message=lambda *_args, **_kwargs: None, _apply_pending_admin_tab=lambda: None, insert_test_log_from_admin=lambda: None, _build_admin_diagnostics_payload=lambda: {}, refresh_extension_status=lambda: None, _handle_admin_export_debug=lambda _: None)
        def open_dialog(*_args, **_kwargs):
            opened.append(True)
            return NS(focus=lambda: None)
        with patch("ui.main_app.window.get_current_session", return_value=session(role)), patch("ui.main_app.window.AdminUploaderDialog", side_effect=open_dialog):
            MainAppWindow._validate_admin_access(window, password)
        results[f"{role}/{'correct_password' if password == 'offline' else 'wrong_password'}"] = {"opened": bool(opened)}
    return results


def probe_paripe_context():
    site = ParipeSite()
    def evaluate_body(script):
        if "tagName" in script:
            return True
        if "window.location.href" in script:
            return "https://paripe.io/imhere-light"
        return None

    body = NS(evaluate=evaluate_body)
    dialog = object()
    root = NS(url="https://paripe.io/imhere-light")
    root.locator = lambda selector: NS(count=lambda: 1, nth=lambda _index: dialog) if selector == site._selectors.selfie_dialog else NS(first=body)
    page = NS(frames=[root], main_frame=None)
    # The next button appears after the dialog scan, before the body scan.
    site._find_fast_text_button = lambda context, _labels: object() if context is body else None
    selected = site._find_pre_selfie_context_now(page)
    site._set_active_flow_context(selected, page=page, source="offline-audit")
    return {"selected_body": selected is body, "active_context_saved": site._active_flow_context is not None}


def probe_widgets():
    import customtkinter as ctk
    from services.photo_review_service import PhotoCandidateRecord
    from services.user_access_admin_service import UserAccessRecord
    from ui.main_app.user_access_panel import UserAccessPanel

    root = ctk.CTk()
    root.withdraw()
    results = {}
    try:
        with patch.object(UserAccessPanel, "refresh"):
            users_panel = UserAccessPanel(root, access_admin_service=NS())
        users = [UserAccessRecord(id=str(index), email="offline@example.invalid", login_id=f"offline-{index}", display_name="Offline", role="member", approved=True, disabled=False) for index in range(100)]
        started = monotonic()
        users_panel._apply_users(users)
        root.update_idletasks()
        results["100_user_rows_ms"] = round((monotonic() - started) * 1000)
        users_panel.destroy()
        with patch.object(PhotoReviewPanel, "refresh"):
            review_panel = PhotoReviewPanel(root, review_service=NS())
        review_panel._thumbnail_loader_worker = lambda *_args: None
        candidates = [PhotoCandidateRecord(id=str(index), batch_id="offline", user_id="offline", storage_path="offline.jpg", original_name="offline.jpg", frame_index=index, timestamp_seconds=0, blur_score=1, brightness_score=1, status="pending") for index in range(PhotoReviewPanel.DISPLAY_BATCH_SIZE)]
        started = monotonic()
        review_panel._render_candidates(candidates)
        root.update_idletasks()
        results["180_photo_cards_ms"] = round((monotonic() - started) * 1000)
        review_panel.destroy()
    finally:
        root.destroy()
    return results


def main():
    probes = {"access": probe_access, "timers": probe_timers, "admin_users": probe_admin_users, "logging": probe_logging, "photo_review": probe_review, "upload_error": probe_upload_error, "updater": probe_updater, "video_failure": probe_video_failure, "actions": probe_actions, "admin_access": probe_admin_access, "paripe_context": probe_paripe_context}
    if "--widgets" in sys.argv:
        probes["widgets"] = probe_widgets
    for name, probe in probes.items():
        print(json.dumps({name: probe()}, ensure_ascii=True), flush=True)


if __name__ == "__main__":
    main()
