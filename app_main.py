from ui.main_app.window import MainAppWindow
from ui.theme import setup_theme
from ui.access.login_window import request_app_access


def main() -> None:
    setup_theme()
    session = request_app_access()
    if session is None:
        return
    app = MainAppWindow()
    app.mainloop()


if __name__ == "__main__":
    main()
