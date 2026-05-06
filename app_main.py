from ui.main_app.window import MainAppWindow
from ui.theme import setup_theme


def main() -> None:
    setup_theme()
    app = MainAppWindow()
    app.mainloop()


if __name__ == "__main__":
    main()
