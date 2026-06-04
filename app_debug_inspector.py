from debug_tools.inspector_window import DebugInspectorWindow
from ui.admin_auth import request_admin_access
from ui.theme import setup_theme


def main() -> None:
    setup_theme()
    if not request_admin_access():
        return
    app = DebugInspectorWindow()
    app.mainloop()


if __name__ == "__main__":
    main()
