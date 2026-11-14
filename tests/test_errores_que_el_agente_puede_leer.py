"""Un error que el agente no entiende es un error que no puede resolver.

`safe_error_summary` tapa el texto de las excepciones a proposito: el de
Supabase, Storage o Playwright arrastra rutas, filas, URLs con claves y lo
que la persona acababa de teclear. Eso no puede acabar en una captura de
pantalla.

Pero la misma regla dejaba mudos los mensajes que escribimos nosotros PARA
que los lea una persona. El agente veia "No se pudo enviar el video. Revisa
tu conexion y vuelve a intentar. (RuntimeError)" cuando el video duraba seis
segundos, o estaba repetido, o faltaba configurar la carpeta de Drive. Tres
problemas distintos, tres soluciones distintas, el mismo texto inutil.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from core.errors import ErrorParaElAgente
from ui.shared.errors import safe_error_summary

RAIZ = Path(__file__).resolve().parents[1]


def test_un_error_nuestro_se_lee_entero() -> None:
    mensaje = "El video debe durar minimo 10 s. Duracion detectada: 6 s."

    assert safe_error_summary(ErrorParaElAgente(mensaje)) == mensaje


def test_un_error_de_fuera_sigue_tapado() -> None:
    """Lo de siempre: el texto de terceros puede llevar claves y datos."""

    class ErrorDeSupabase(RuntimeError):
        pass

    fuga = "PGRST301 https://xxxx.supabase.co/rest/v1/photos?apikey=SECRETO"
    resumen = safe_error_summary(ErrorDeSupabase(fuga))

    assert resumen == "ErrorDeSupabase"
    assert "supabase.co" not in resumen
    assert "SECRETO" not in resumen


def test_los_mensajes_del_video_no_llevan_rutas_dentro() -> None:
    """Si se muestran enteros, no pueden arrastrar rutas del equipo.

    Por eso los textos nuevos dicen que hacer en vez de repetir el valor que
    falta: "avisa al administrador", no "No existe C:\\...\\client.json".
    """

    fuente = (RAIZ / "services" / "video_delivery_service.py").read_text(encoding="utf-8")
    inicio = 0
    while True:
        inicio = fuente.find("ErrorParaElAgente(", inicio)
        if inicio == -1:
            break
        bloque = fuente[inicio : fuente.index(")", inicio) + 1]
        inicio += 1
        assert "{" not in bloque, f"interpola un valor en un mensaje visible: {bloque}"


def test_el_video_usa_la_clase_nueva_y_no_runtimeerror_pelado() -> None:
    for nombre in ("video_delivery_service.py", "video_contribution_service.py"):
        fuente = (RAIZ / "services" / nombre).read_text(encoding="utf-8")
        assert "ErrorParaElAgente" in fuente, nombre


def test_cada_agente_autoriza_su_propia_cuenta_de_google() -> None:
    """Era un solo token por instalacion.

    El primero que autorizaba dejaba su cuenta puesta para todo el equipo
    -los videos de los demas subian a SU Drive- y ningun agente posterior
    volvia a ver la pantalla de verificacion.
    """

    from services.video_delivery_service import GoogleDriveVideoDeliveryService

    base = Path("local_data/google_drive_token.json")

    class _Ajustes:
        google_drive_oauth_token_file = base

    servicio = GoogleDriveVideoDeliveryService(_Ajustes(), user_key="abc-123")
    propio = servicio._token_file()  # noqa: SLF001

    assert propio != base
    assert "abc-123" in propio.name
    assert propio.parent == base.parent

    otro = GoogleDriveVideoDeliveryService(_Ajustes(), user_key="zzz-999")._token_file()  # noqa: SLF001
    assert otro != propio, "dos agentes no pueden compartir autorizacion"


def test_un_identificador_raro_no_se_escapa_de_la_carpeta() -> None:
    from services.video_delivery_service import GoogleDriveVideoDeliveryService

    class _Ajustes:
        google_drive_oauth_token_file = Path("local_data/google_drive_token.json")

    sucio = GoogleDriveVideoDeliveryService(_Ajustes(), user_key="../../fuera")._token_file()  # noqa: SLF001

    assert ".." not in str(sucio)
    assert sucio.parent == Path("local_data")


def test_sin_sesion_se_usa_el_archivo_de_siempre() -> None:
    from services.video_delivery_service import GoogleDriveVideoDeliveryService

    base = Path("local_data/google_drive_token.json")

    class _Ajustes:
        google_drive_oauth_token_file = base

    assert GoogleDriveVideoDeliveryService(_Ajustes())._token_file() == base  # noqa: SLF001
