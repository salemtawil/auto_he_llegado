from ui.main_app.form_panel import FormPanel


def test_process_password_sanitizer_removes_all_whitespace() -> None:
    assert FormPanel.sanitize_password(" se cre\tto \n123 ") == "secreto123"
