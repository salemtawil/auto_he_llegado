from ui.theme import setup_theme
from ui.uploader.window import UploaderWindow


def main() -> None:
    setup_theme()
    app = UploaderWindow()
    app.mainloop()


if __name__ == "__main__":
    main()
