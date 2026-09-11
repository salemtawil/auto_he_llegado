from types import SimpleNamespace

import pytest

from automation.compinche_site import CompincheSite
from automation.paripe_site import ParipeSite
from automation.ready4drive_site import Ready4DriveSite


def _unexpected_scan(*_args, **_kwargs):
    pytest.fail("A ready verification step must not wait for the full flow scan")


@pytest.mark.parametrize("site_type", [CompincheSite, Ready4DriveSite])
@pytest.mark.parametrize("label_kind", ["verification_start_texts", "self_owner_continue_texts"])
def test_ready_verification_step_precedes_retry_context_scan(monkeypatch, site_type, label_kind):
    site = site_type()
    root = object()
    button = object()
    labels = getattr(site._selectors, label_kind)
    monkeypatch.setattr(site, "_has_photo_input_now", lambda _root: False)
    monkeypatch.setattr(site, "_find_fast_text_button", lambda _root, texts: button if set(labels) <= set(texts) else None)
    monkeypatch.setattr(site, "_resolve_current_flow_context", _unexpected_scan)

    assert site._resolve_selfie_retry_root(SimpleNamespace(frames=[]), root) is root


@pytest.mark.parametrize("site_type", [CompincheSite, Ready4DriveSite])
def test_verification_frame_precedes_general_frame_scoring(monkeypatch, site_type):
    site = site_type()
    frame = SimpleNamespace(url="https://paripe.io/imhere-light")
    page = SimpleNamespace(frames=[frame], main_frame=object())
    monkeypatch.setattr(site, "_find_fast_text_button", lambda root, _texts: object() if root is frame else None)
    monkeypatch.setattr(site, "_has_photo_input_now", lambda _root: False)
    monkeypatch.setattr(site, "_record_engine_resolution", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(site, "_find_action_frame", _unexpected_scan)

    result = site._wait_for_flow_root(page, site._get_action_spec("He llegado"), timeout_ms=1000)

    assert result.root is frame
    assert result.is_iframe


def test_paripe_verification_step_does_not_wait_for_photo_input(monkeypatch):
    site = ParipeSite()
    page = SimpleNamespace(frames=[])
    dialog = object()
    monkeypatch.setattr(site, "_find_pre_selfie_context_now", lambda _page, _preferred=None: dialog, raising=False)
    monkeypatch.setattr(site, "_dom_signature", _unexpected_scan)
    monkeypatch.setattr(site, "_record_engine_resolution", lambda *_args, **_kwargs: None)

    assert site._wait_for_photo_phase(page, progress_callback=None, timeout_ms=1000) is dialog
