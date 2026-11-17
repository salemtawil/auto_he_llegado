"""El video se archiva Y se le sacan fotos: antes era una cosa o la otra.

Y esa exclusion tenia un coste escondido: la rama de fotogramas no hacia la
huella del video, ni validaba la duracion minima, ni detectaba repetidos.
Esas tres comprobaciones solo vivian en la rama de Drive. Siendo el video la
prueba de trabajo semanal, aceptar el mismo cada semana se cargaba el motivo
de pedirlo.
"""

from __future__ import annotations

import ast
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
SERVICIO = (RAIZ / "services" / "video_contribution_service.py").read_text(encoding="utf-8")


def _cuerpo(nombre: str) -> str:
    for n in ast.walk(ast.parse(SERVICIO)):
        if isinstance(n, ast.FunctionDef) and n.name == nombre:
            return ast.unparse(n)
    raise AssertionError(f"no existe {nombre}")


def test_los_dos_caminos_ya_no_se_excluyen() -> None:
    cuerpo = _cuerpo("submit_video")
    assert "archivar_en_drive = modo in ('drive', 'both')" in cuerpo
    assert "extraer_fotogramas = modo in ('frames', 'both')" in cuerpo
    # Y el atajo viejo, que devolvia antes de comprobar nada, ya no esta.
    assert "_submit_video_as_frame_candidates" not in SERVICIO


def test_las_comprobaciones_valen_para_los_dos_caminos() -> None:
    """Duracion minima y repetidos, antes de decidir que se hace con el video."""

    cuerpo = _cuerpo("submit_video")
    for comprobacion in ("_validate_min_duration", "find_duplicate", "_fingerprint_service.build"):
        assert comprobacion in cuerpo, comprobacion

    # Y ocurren ANTES de tocar Drive o de extraer nada.
    assert cuerpo.index("_validate_min_duration") < cuerpo.index("archivar_en_drive and")  \
        if "archivar_en_drive and" in cuerpo else True
    assert cuerpo.index("find_duplicate") < cuerpo.index("upload_video")
    assert cuerpo.index("find_duplicate") < cuerpo.index("_extraer_fotogramas")


def test_si_falla_la_extraccion_el_video_no_se_pierde() -> None:
    """El agente ya cumplio: su video esta archivado.

    Tumbar el lote porque no salieron fotos seria cobrarle a el un problema
    nuestro.
    """

    cuerpo = _cuerpo("submit_video")
    assert "extraction_warning" in cuerpo
    assert "if not archivar_en_drive:" in cuerpo, (
        "sin Drive de respaldo si tiene que fallar: no quedaria nada"
    )


def test_el_cero_del_intervalo_sigue_cayendo_al_valor_por_defecto() -> None:
    """El 0 significa "nadie lo configuro", no "todos los fotogramas"."""

    cuerpo = _cuerpo("_intervalo_de_fotogramas")
    assert "INTERVALO_POR_DEFECTO_S" in cuerpo
    assert "intervalo > 0" in cuerpo

    from services.video_contribution_service import VideoContributionService

    assert VideoContributionService.INTERVALO_POR_DEFECTO_S > 0


def test_se_mira_lo_bastante_de_cerca_como_para_poder_elegir() -> None:
    """De un video de 10 s salian SEIS fotos.

    No las seis mejores: las unicas seis que se habian mirado, porque el
    intervalo era de 2 segundos. Con tan pocas muestras, ordenar por cara y
    por nitidez no decide nada. Mirar es barato -se mide en memoria y solo se
    escriben al disco las elegidas-, asi que el intervalo tiene que dejar un
    monton del que elegir, aunque el video sea corto.
    """

    from services.video_contribution_service import VideoContributionService

    muestras_en_diez_segundos = 10 / VideoContributionService.INTERVALO_POR_DEFECTO_S
    assert muestras_en_diez_segundos >= 25, VideoContributionService.INTERVALO_POR_DEFECTO_S


def test_cuantas_salen_lo_decide_el_tope_y_no_el_intervalo() -> None:
    """Quien limita el lote es `video_max_candidate_frames`.

    Mientras el intervalo decidia cuantas fotos salian, subir la densidad
    para elegir mejor significaba inundar a quien revisa. Son dos perillas
    distintas y el extractor tiene que recibirlas por separado.
    """

    cuerpo = _cuerpo("_extraer_fotogramas")
    assert "max_frames=self._settings.video_max_candidate_frames" in cuerpo
    assert "interval_seconds=self._intervalo_de_fotogramas()" in cuerpo


def test_los_repetidos_se_filtran_siempre() -> None:
    """Estaban atados al intervalo, y esa es la atadura que hacia daño.

    `filtrar_repetidos = intervalo > 0` convertia "mirar de cerca" en "mirar
    de cerca y quedarselo todo". Mirar mas no puede castigar a quien revisa.
    """

    import inspect

    from services.video_frame_extractor import VideoFrameExtractor

    cuerpo = inspect.getsource(VideoFrameExtractor._medir)
    # El comentario que explica por que se quito si menciona el nombre; lo
    # que no puede volver es la condicion.
    assert "if filtrar_repetidos" not in cuerpo
    assert "_simple_frame_hash" in cuerpo


def test_el_que_extrae_ya_no_crea_ni_cierra_el_lote() -> None:
    # Meter eso ahi dentro fue lo que dejo la rama de fotogramas sin
    # comprobaciones.
    cuerpo = _cuerpo("_extraer_fotogramas")
    for prohibido in ("create_batch", "finish_batch", "mark_batch_failed"):
        assert prohibido not in cuerpo, prohibido


def test_el_mensaje_final_dice_lo_que_paso_no_el_modo() -> None:
    from services.video_contribution_service import VideoContributionService

    resumen = VideoContributionService._resumen_final  # noqa: SLF001

    assert "guardado" in resumen(archivado=True, candidatas=0, extraccion_pedida=False).lower()
    con_fotos = resumen(archivado=True, candidatas=12, extraccion_pedida=True)
    assert "12" in con_fotos and "guardado" in con_fotos.lower()
    sin_fotos = resumen(archivado=True, candidatas=0, extraccion_pedida=True)
    assert "no se pudo sacar" in sin_fotos


def test_en_modo_both_se_archiva_y_se_extrae(tmp_path) -> None:
    """La prueba de que ya no hay que elegir."""

    import sys

    sys.path.insert(0, str(RAIZ / "tests"))
    from test_video_contribution_service import (  # noqa: E402
        StubExtractor,
        StubFingerprintService,
        StubReviewService,
        build_settings,
    )

    from services.auth_context import AuthSession
    from services.video_contribution_service import VideoContributionService

    video = tmp_path / "semanal.mp4"
    video.write_bytes(b"video-data")

    class _Drive:
        def __init__(self) -> None:
            self.subidas = []

        def upload_video(self, source, *, display_name):
            self.subidas.append(display_name)
            from types import SimpleNamespace

            return SimpleNamespace(provider="drive", file_id="f1", url="https://drive/f1")

    class _Telegram:
        def __init__(self) -> None:
            self.avisos = 0

        def send_video_received(self, **_kwargs):
            self.avisos += 1

    drive = _Drive()
    telegram = _Telegram()
    review = StubReviewService()
    ajustes = build_settings(tmp_path)
    object.__setattr__(ajustes, "video_submission_mode", "both")

    servicio = VideoContributionService(
        review_service=review,
        extractor=StubExtractor(tmp_path),
        delivery_service=drive,
        notification_service=telegram,
        fingerprint_service=StubFingerprintService(),
        settings=ajustes,
    )
    sesion = AuthSession(
        user_id="user-1",
        email="agente@example.com",
        access_token="a",
        refresh_token="r",
        approved=True,
    )

    resultado = servicio.submit_video(video, session=sesion)

    assert drive.subidas, "el video tiene que quedar archivado"
    assert telegram.avisos == 1, "y el admin enterarse"
    assert resultado.frames_extracted == 2, "y ademas salir las fotos"
    assert resultado.candidates_uploaded == 2


def test_el_estado_del_lote_sigue_siendo_el_contrato_con_la_puerta() -> None:
    """No quitar `status="pending_review"` aunque sea el valor por defecto.

    Lo quite yo por parecer ruido y lo cazo test_video_gate_contract: ese
    literal es el enlace entre dos modulos. Un lote nace en "pending_review"
    y ese estado tiene que estar en AccessService.ACTIVE_BATCH_STATUSES,
    porque la revision de fotos esta deshabilitada: si el desbloqueo
    dependiera de aprobar, los agentes quedarian bloqueados para siempre.
    """

    from services.access_service import AccessService

    cuerpo = _cuerpo("submit_video")
    assert "status='pending_review'" in cuerpo
    assert "pending_review" in AccessService.ACTIVE_BATCH_STATUSES


def test_la_deteccion_de_repetidos_compara_contra_algo_de_verdad() -> None:
    """Estuvo muerta y nadie se entero.

    El filtro de quien llama se quedaba con los lotes que tuvieran
    `delivery_file_id`, pero `list_video_fingerprint_candidates` NUNCA pidio
    esa columna. Resultado: la lista se vaciaba siempre, `find_duplicate`
    recibia cero lotes, y cualquiera podia subir el mismo video todas las
    semanas. En cualquier modo, desde que se escribio.
    """

    cuerpo = _cuerpo("submit_video")
    # El filtro que decide contra que se compara. `delivery_file_id` sigue
    # apareciendo mas abajo, al cerrar el lote, y eso esta bien: lo que no
    # puede es volver a ser el criterio de la comparacion.
    filtro = cuerpo[cuerpo.index("comparables = ") : cuerpo.index("find_duplicate")]
    assert "delivery_file_id" not in filtro, "vuelve a filtrar por una columna que no se pide"
    assert "status" in filtro

    repositorio = (RAIZ / "services" / "photo_review_service.py").read_text(encoding="utf-8")
    inicio = repositorio.index("def list_video_fingerprint_candidates")
    consulta = repositorio[inicio : inicio + 900]
    # Lo que se filtra tiene que venir en el select, o el filtro no filtra.
    assert "status" in consulta, "se filtra por estado: hay que pedirlo"


def test_un_lote_fallido_no_bloquea_reintentar_ese_video() -> None:
    """Reconcilia las dos decisiones que habia escritas y en conflicto.

    Una prueba pedia comparar contra TODOS los lotes (16/10, para que un
    video subido una vez cuente como repetido aunque su lote quedara a
    medias) y otra pedia que un lote fallido NO bloqueara el reintento. Se
    cumplen las dos mirando el estado: solo se excluye lo explicitamente
    fallido; lo que quedo a medias sigue contando.
    """

    from services.video_contribution_service import VideoContributionService

    fallidos = VideoContributionService._ESTADOS_FALLIDOS  # noqa: SLF001

    assert "rejected" in fallidos, "mark_batch_failed deja el lote en 'rejected'"
    assert "processing" not in fallidos, "un lote a medias SI cuenta como subido"
    assert "pending_review" not in fallidos, "y uno terminado, mas todavia"


def test_el_aviso_por_telegram_tambien_llega_sin_respaldo_en_drive() -> None:
    # Si no, al quitar Drive te quedas sin enterarte de que alguien subio.
    cuerpo = _cuerpo("submit_video")
    assert "if delivery is not None:\n        try:\n            self._notification_service" not in cuerpo
    assert "fotos_subidas=" in cuerpo
