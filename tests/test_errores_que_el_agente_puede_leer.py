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


def test_la_autorizacion_es_una_por_equipo_no_por_agente(tmp_path) -> None:
    """A proposito.

    Los videos van todos a la MISMA carpeta de Drive de la empresa, asi que
    la cuenta que autoriza tiene que ser la que tiene permiso sobre esa
    carpeta. Si cada agente autorizara la suya, la mayoria no podria
    escribir alli y la subida fallaria para todos menos para uno.
    """

    from services.video_delivery_service import GoogleDriveVideoDeliveryService

    base = tmp_path / "google_drive_token.json"

    class _Ajustes:
        google_drive_oauth_token_file = base

    assert GoogleDriveVideoDeliveryService(_Ajustes())._token_file() == base  # noqa: SLF001


def test_se_puede_olvidar_la_cuenta_para_que_la_vuelva_a_pedir(tmp_path) -> None:
    """La salida cuando el paso de Google se queda a medias.

    La ventana se cerro sin terminar, o el navegador no llego a abrirse.
    Sin esto no habia forma de volver a empezar sin entrar a mano en la
    carpeta de datos.
    """

    from services.video_delivery_service import GoogleDriveVideoDeliveryService

    token = tmp_path / "google_drive_token.json"
    token.write_text('{"token": "lo-que-sea"}', encoding="utf-8")

    class _Ajustes:
        google_drive_oauth_token_file = token

    servicio = GoogleDriveVideoDeliveryService(_Ajustes())

    assert servicio.olvidar_autorizacion() is True
    assert not token.exists(), "la proxima subida tiene que volver a pedirla"
    # Se guarda al lado por si la nueva autorizacion sale mal.
    assert (tmp_path / "google_drive_token.json.anterior").exists()

    # Y repetirlo no es un error: simplemente ya no habia nada.
    assert servicio.olvidar_autorizacion() is False


def test_olvidar_dos_veces_no_deja_respaldos_apilados(tmp_path) -> None:
    from services.video_delivery_service import GoogleDriveVideoDeliveryService

    token = tmp_path / "google_drive_token.json"

    class _Ajustes:
        google_drive_oauth_token_file = token

    servicio = GoogleDriveVideoDeliveryService(_Ajustes())
    for _ in range(3):
        token.write_text("{}", encoding="utf-8")
        assert servicio.olvidar_autorizacion() is True

    assert sorted(f.name for f in tmp_path.iterdir()) == [
        "google_drive_token.json.anterior"
    ]


def test_la_ventana_de_google_no_puede_colgar_la_subida_para_siempre() -> None:
    """`run_local_server` espera el redirect sin limite.

    Si el agente cierra la ventana sin autorizar, el hilo de la subida se
    queda ahi y en pantalla no pasa nada: ni error, ni progreso, ni final.
    """

    fuente = (RAIZ / "services" / "video_delivery_service.py").read_text(encoding="utf-8")

    assert "timeout_seconds=self.AUTORIZACION_TIMEOUT_S" in fuente
    assert "AUTORIZACION_TIMEOUT_S = " in fuente
    # Y al expirar se dice que hacer, no solo que fallo.
    assert "Reiniciar verificacion de Google" in fuente


def test_el_boton_de_reiniciar_no_puede_fallar_con_una_excepcion() -> None:
    # Un boton de rescate que revienta en pantalla no rescata a nadie.
    ventana = (RAIZ / "ui" / "main_app" / "window.py").read_text(encoding="utf-8")
    inicio = ventana.index("def reiniciar_verificacion_de_google")
    cuerpo = ventana[inicio : ventana.index("\n    def ", inicio + 10)]

    assert "try:" in cuerpo and "except Exception" in cuerpo
    assert "raise" not in cuerpo
