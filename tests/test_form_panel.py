from ui.main_app.form_panel import FormPanel


def test_process_password_sanitizer_removes_all_whitespace() -> None:
    assert FormPanel.sanitize_password(" se cre\tto \n123 ") == "secreto123"


class _FakeEntry:
    def __init__(self, value: str = "", clipboard: str = "") -> None:
        self.value = value
        self.clipboard = clipboard
        self.focused = False
        self.has_selection = False
        self.selection = (0, 0)
        self.insert_index = len(value)

    def clipboard_get(self) -> str:
        return self.clipboard

    def focus_force(self) -> None:
        self.focused = True

    def selection_present(self) -> bool:
        return self.has_selection

    def delete(self, start, end) -> None:
        if start == "sel.first" and end == "sel.last":
            first, last = self.selection
            self.value = self.value[:first] + self.value[last:]
            self.insert_index = first

    def insert(self, index, text: str) -> None:
        if index == "insert":
            index = self.insert_index
        elif index == "end":
            index = len(self.value)
        self.value = self.value[:index] + text + self.value[index:]
        self.insert_index = index + len(text)


def test_context_menu_paste_inserts_clipboard_text() -> None:
    entry = _FakeEntry("abc", "123")

    FormPanel._replace_entry_selection_with_text(entry, entry.clipboard_get())

    assert entry.value == "abc123"
    assert entry.focused is True


def test_context_menu_paste_replaces_selected_text() -> None:
    entry = _FakeEntry("abcXYZ", "123")
    entry.has_selection = True
    entry.selection = (3, 6)
    entry.insert_index = 3

    FormPanel._replace_entry_selection_with_text(entry, entry.clipboard_get())

    assert entry.value == "abc123"
