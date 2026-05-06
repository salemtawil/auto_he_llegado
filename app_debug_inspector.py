from debug_tools.inspector_window import DebugInspectorWindow
from ui.theme import setup_theme


def main() -> None:
    setup_theme()
    app = DebugInspectorWindow()
    app.mainloop()


if __name__ == "__main__":
    main()
