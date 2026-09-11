from types import SimpleNamespace

from ui.uploader.panel import UploaderPanel


def test_upload_thread_error_reaches_handler_after_tk_callback() -> None:
    callbacks = []
    handled_errors = []

    def fail_upload(*_args, **_kwargs):
        raise RuntimeError("fallo offline")

    panel = SimpleNamespace(
        _uploader_service=SimpleNamespace(upload_files=fail_upload),
        _selected_files=["foto.jpg"],
        delete_local_checkbox=SimpleNamespace(get=lambda: False),
        _schedule_progress_update=lambda _progress: None,
        after=lambda _delay, callback: callbacks.append(callback),
        _handle_unexpected_error=handled_errors.append,
    )

    UploaderPanel._run_upload(panel)
    callbacks[0]()

    assert len(handled_errors) == 1
    assert str(handled_errors[0]) == "fallo offline"
