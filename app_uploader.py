from ui.admin_auth import request_admin_access
from ui.theme import setup_theme
from ui.uploader.window import UploaderWindow


def main() -> None:
    setup_theme()
    if not request_admin_access():
        return
    app = UploaderWindow()
    app.mainloop()


if __name__ == "__main__":
    main()
