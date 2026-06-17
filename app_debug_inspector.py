from debug_tools.inspector_window import DebugInspectorWindow
from ui.admin_auth import request_admin_access
from ui.access.login_window import request_app_access
from ui.theme import setup_theme


def main() -> None:
    setup_theme()
    session = request_app_access()
    if session is None or not session.is_admin:
        return
    if not request_admin_access():
        return
    app = DebugInspectorWindow()
    app.mainloop()


if __name__ == "__main__":
    main()
