# El registro se monta ANTES que nada: si algo falla durante los imports de la
# interfaz, queremos que quede escrito en vez de perderse.
from config.app_logging import configure_logging

configure_logging()

from ui.theme import setup_theme
from ui.access.login_window import request_app_access


def main() -> None:
    setup_theme()
    session = request_app_access()
    if session is None:
        return
    # La ventana principal se importa DESPUES del login: su arbol de imports
    # (~250 ms) se pagaba antes de mostrar la pantalla de entrada, aunque no se
    # instancia hasta aqui.
    from ui.main_app.window import MainAppWindow

    app = MainAppWindow()
    app.mainloop()


if __name__ == "__main__":
    main()
