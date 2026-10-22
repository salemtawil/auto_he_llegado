from config.app_logging import configure_logging
from debug_tools.inspector_window import DebugInspectorWindow
from ui.admin_auth import request_admin_access
from ui.access.login_window import request_app_access
from ui.theme import setup_theme


def main() -> None:
    # Este ejecutable tambien se empaqueta sin consola: sin registro, un fallo
    # al subir fotos o el crash de un hilo no deja rastro en ningun sitio.
    #
    # Va DENTRO de main y no al importar el modulo: montarlo al importar le
    # cambia el logging global a cualquiera que importe este archivo, y eso
    # contaminaba las pruebas de otros archivos (pasaba de verdad con
    # test_app_logging y test_ui_confirmations).
    configure_logging()
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
