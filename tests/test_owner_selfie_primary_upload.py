from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from automation.compinche_site import CompincheSite
from automation.paripe_site import ParipeSite
from automation.ready4drive_site import Ready4DriveSite


def test_compinche_owner_selfie_uploads_selected_file_without_pool(tmp_path: Path) -> None:
    owner_selfie = tmp_path / "titular.jpg"
    owner_selfie.write_text("demo", encoding="utf-8")
    site = CompincheSite()
    uploaded: list[tuple[Path, str]] = []

    site._resolve_selfie_retry_root = lambda _page, root: root  # type: ignore[method-assign]  # noqa: SLF001
    site._complete_pre_selfie_account_step = lambda root, **_kwargs: root  # type: ignore[method-assign]  # noqa: SLF001
    site._complete_owner_verification_selfie_step = lambda root, **_kwargs: root  # type: ignore[method-assign]  # noqa: SLF001
    site._resolve_prepared_photo = lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("No debe reservar foto del pool"))  # type: ignore[method-assign]  # noqa: SLF001
    site._require_photo_input = lambda *_args, **_kwargs: object()  # type: ignore[method-assign]  # noqa: SLF001
    site._upload_photo_file = lambda _root, *, local_path, original_filename, **_kwargs: uploaded.append((local_path, original_filename))  # type: ignore[method-assign]  # noqa: SLF001
    site._require_continue_button = lambda _root: object()  # type: ignore[method-assign]  # noqa: SLF001
    site._continue_from_modal = lambda *_args, **_kwargs: None  # type: ignore[method-assign]  # noqa: SLF001
    site._wait_for_block_context = lambda *_args, **_kwargs: "block-root"  # type: ignore[method-assign]  # noqa: SLF001
    site._observe_flow_state = lambda *_args, **_kwargs: None  # type: ignore[method-assign]  # noqa: SLF001

    block_context, reserved_photo, *_ = site._complete_selfie_until_block(  # noqa: SLF001
        root="selfie-root",  # type: ignore[arg-type]
        page=SimpleNamespace(url="https://compinche.io/app"),
        progress_callback=None,
        action_timeout_ms=1_000,
        block_wait_ms=1_000,
        max_selfie_retries=1,
        owner_selfie_path=owner_selfie,
    )

    assert block_context == "block-root"
    assert reserved_photo is None
    assert uploaded == [(owner_selfie, "titular.jpg")]


def test_ready4drive_owner_selfie_uploads_selected_file_without_pool(tmp_path: Path) -> None:
    owner_selfie = tmp_path / "titular.jpg"
    owner_selfie.write_text("demo", encoding="utf-8")
    site = Ready4DriveSite()
    uploaded: list[tuple[Path, str]] = []

    site._resolve_selfie_retry_root = lambda _page, root: root  # type: ignore[method-assign]  # noqa: SLF001
    site._complete_pre_selfie_account_step = lambda root, **_kwargs: root  # type: ignore[method-assign]  # noqa: SLF001
    site._complete_owner_verification_selfie_step = lambda root, **_kwargs: root  # type: ignore[method-assign]  # noqa: SLF001
    site._resolve_prepared_photo = lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("No debe reservar foto del pool"))  # type: ignore[method-assign]  # noqa: SLF001
    site._require_photo_input = lambda *_args, **_kwargs: object()  # type: ignore[method-assign]  # noqa: SLF001
    site._upload_photo_file = lambda _root, *, local_path, original_filename, **_kwargs: uploaded.append((local_path, original_filename))  # type: ignore[method-assign]  # noqa: SLF001
    site._require_continue_button = lambda _root: object()  # type: ignore[method-assign]  # noqa: SLF001
    site._continue_from_modal = lambda *_args, **_kwargs: None  # type: ignore[method-assign]  # noqa: SLF001
    site._wait_for_block_context = lambda *_args, **_kwargs: "block-root"  # type: ignore[method-assign]  # noqa: SLF001
    site._observe_flow_state = lambda *_args, **_kwargs: None  # type: ignore[method-assign]  # noqa: SLF001

    block_context, reserved_photo, *_ = site._complete_selfie_until_block(  # noqa: SLF001
        root="selfie-root",  # type: ignore[arg-type]
        page=SimpleNamespace(url="https://ready4drive.com/app"),
        progress_callback=None,
        action_timeout_ms=1_000,
        block_wait_ms=1_000,
        max_selfie_retries=1,
        owner_selfie_path=owner_selfie,
    )

    assert block_context == "block-root"
    assert reserved_photo is None
    assert uploaded == [(owner_selfie, "titular.jpg")]


def test_paripe_owner_selfie_uploads_selected_file_without_pool(tmp_path: Path) -> None:
    owner_selfie = tmp_path / "titular.jpg"
    owner_selfie.write_text("demo", encoding="utf-8")
    site = ParipeSite()
    uploaded: list[tuple[Path, str]] = []

    site._set_active_flow_context = lambda context, **_kwargs: context  # type: ignore[method-assign]  # noqa: SLF001
    site._complete_pre_selfie_account_step = lambda dialog, **_kwargs: dialog  # type: ignore[method-assign]  # noqa: SLF001
    site._complete_owner_verification_selfie_step = lambda dialog, **_kwargs: dialog  # type: ignore[method-assign]  # noqa: SLF001
    site._await_background_photo = lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("No debe reservar foto del pool"))  # type: ignore[method-assign]  # noqa: SLF001
    site._upload_photo_file = lambda _dialog, *, local_path, original_filename, **_kwargs: uploaded.append((local_path, original_filename))  # type: ignore[method-assign]  # noqa: SLF001
    site._click_continue = lambda *_args, **_kwargs: None  # type: ignore[method-assign]  # noqa: SLF001
    site._wait_for_details_dialog = lambda *_args, **_kwargs: "details-dialog"  # type: ignore[method-assign]  # noqa: SLF001
    site._observe_flow_state = lambda *_args, **_kwargs: None  # type: ignore[method-assign]  # noqa: SLF001

    details_context, reserved_photo, *_ = site._complete_selfie_until_block(  # noqa: SLF001
        SimpleNamespace(url="https://paripe.io/app"),
        selfie_dialog="selfie-dialog",  # type: ignore[arg-type]
        progress_callback=None,
        action_timeout_ms=1_000,
        block_wait_ms=1_000,
        max_selfie_retries=1,
        owner_selfie_path=owner_selfie,
    )

    assert details_context == "details-dialog"
    assert reserved_photo is None
    assert uploaded == [(owner_selfie, "titular.jpg")]
