"""Primero la cara, despues la calidad.

Una foto sin cara no sirve NUNCA: el proceso la usa como selfie. Una foto un
poco blanda pero con la cara clara se usa perfectamente. Antes el filtro era
al reves -nitidez y brillo- asi que un fotograma del techo, nitido y bien
iluminado, pasaba, y uno algo movido con la cara perfecta se tiraba.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from services.video_frame_extractor import VideoFrameExtractor

cv2 = pytest.importorskip("cv2", reason="hace falta OpenCV para estas pruebas")
np = pytest.importorskip("numpy")


def _cara(ancho: int, alto: int, *, radio: int, cx: int, cy: int):
    """Una cara sintetica que los clasificadores de Haar reconocen.

    No es un dibujo bonito: son las manchas claras y oscuras en las
    proporciones que el clasificador busca -frente clara, ojos oscuros,
    sombra bajo la nariz-.
    """

    lienzo = np.full((alto, ancho, 3), 40, dtype=np.uint8)
    cv2.ellipse(lienzo, (cx, cy), (radio, int(radio * 1.3)), 0, 0, 360, (200, 200, 200), -1)
    ojo = max(radio // 6, 2)
    cv2.circle(lienzo, (cx - radio // 2, cy - radio // 3), ojo, (20, 20, 20), -1)
    cv2.circle(lienzo, (cx + radio // 2, cy - radio // 3), ojo, (20, 20, 20), -1)
    cv2.ellipse(
        lienzo, (cx, cy + radio // 2), (radio // 2, radio // 5), 0, 0, 180, (60, 60, 60), -1
    )
    return lienzo


def _pared(ancho: int, alto: int, *, semilla: int):
    """Una pared con textura: nitida y bien iluminada, pero sin cara."""

    generador = np.random.default_rng(semilla)
    ruido = generador.integers(120, 200, size=(alto, ancho, 3), dtype=np.uint8)
    return ruido


def _video(path: Path, cuadros, *, fps: int = 10) -> Path:
    alto, ancho = cuadros[0].shape[:2]
    escritor = cv2.VideoWriter(
        str(path), cv2.VideoWriter_fourcc(*"mp4v"), fps, (ancho, alto)
    )
    assert escritor.isOpened(), "no se pudo crear el video de prueba"
    for cuadro in cuadros:
        escritor.write(cuadro)
    escritor.release()
    return path


@pytest.fixture
def extractor() -> VideoFrameExtractor:
    extractor = VideoFrameExtractor()
    if not extractor._cargar_detectores(cv2):  # noqa: SLF001
        pytest.skip("esta instalacion de OpenCV no trae los clasificadores de cara")
    return extractor


def test_se_prefiere_la_cara_sobre_la_pared(tmp_path, extractor) -> None:
    """La prueba que resume todo el cambio.

    Mitad del video es pared nitida y bien iluminada; la otra mitad, cara.
    Antes ganaba la pared.
    """

    cuadros = [_pared(320, 240, semilla=i) for i in range(20)]
    cuadros += [_cara(320, 240, radio=70, cx=160, cy=120) for _ in range(20)]
    video = _video(tmp_path / "mitad.mp4", cuadros)

    fotos = extractor.extract(
        video, tmp_path / "salida", interval_seconds=0.5, max_frames=4, jpeg_quality=85
    )

    assert fotos, "no devolvio ninguna foto"
    assert all(f.has_face for f in fotos), [f.face_score for f in fotos]
    assert all(f.face_score > 0 for f in fotos)


def test_sin_ninguna_cara_no_deja_al_agente_sin_lote(tmp_path, extractor) -> None:
    """Nunca cero fotos por ser exigentes.

    El video es la prueba de trabajo semanal: dejar al agente sin lote por un
    filtro nuestro seria cobrarle a el nuestra exigencia. Se devuelven las
    mejores por calidad, marcadas para que quien revise lo sepa.
    """

    video = _video(tmp_path / "pared.mp4", [_pared(320, 240, semilla=i) for i in range(30)])

    fotos = extractor.extract(
        video, tmp_path / "salida", interval_seconds=0.5, max_frames=3, jpeg_quality=85
    )

    assert fotos, "devolvio cero y dejo al agente sin lote"
    assert all(not f.has_face for f in fotos)
    assert all(f.face_score == 0 for f in fotos)


def test_una_cara_de_fondo_no_cuenta(tmp_path, extractor) -> None:
    # Alguien pasando por detras no es el agente.
    cuadros = [_cara(640, 480, radio=12, cx=560, cy=60) for _ in range(20)]
    video = _video(tmp_path / "fondo.mp4", cuadros)

    fotos = extractor.extract(
        video, tmp_path / "salida", interval_seconds=0.5, max_frames=3, jpeg_quality=85
    )

    assert all(not f.has_face for f in fotos), [f.face_score for f in fotos]


def test_solo_se_escriben_las_elegidas(tmp_path, extractor) -> None:
    """Antes se escribia cada fotograma y se borraba si no pasaba.

    Con la cara como condicion eso serian decenas de escrituras y borrados
    por video para nada.
    """

    cuadros = [_cara(320, 240, radio=70, cx=160, cy=120) for _ in range(40)]
    salida = tmp_path / "salida"
    video = _video(tmp_path / "largo.mp4", cuadros)

    fotos = extractor.extract(
        video, salida, interval_seconds=0.3, max_frames=3, jpeg_quality=85
    )

    assert len(fotos) <= 3
    assert len(list(salida.glob("*.jpg"))) == len(fotos), "quedaron JPG de descartes"


def test_las_fotos_salen_en_orden_del_video(tmp_path, extractor) -> None:
    # Se eligen por calidad, pero se entregan en orden cronologico: asi es
    # como tiene sentido revisarlas.
    cuadros = [_cara(320, 240, radio=60 + (i % 5) * 4, cx=160, cy=120) for i in range(40)]
    video = _video(tmp_path / "orden.mp4", cuadros)

    fotos = extractor.extract(
        video, tmp_path / "salida", interval_seconds=0.3, max_frames=5, jpeg_quality=85
    )

    indices = [f.frame_index for f in fotos]
    assert indices == sorted(indices), indices


def test_sin_clasificadores_sigue_funcionando(tmp_path, monkeypatch) -> None:
    """OpenCV 5 quito las cascadas. Si alguna instalacion se sale del pin,
    se trabaja como antes en vez de fallar."""

    extractor = VideoFrameExtractor()
    monkeypatch.setattr(extractor, "_cargar_detectores", lambda _cv2: [])
    video = _video(tmp_path / "sin.mp4", [_pared(320, 240, semilla=i) for i in range(20)])

    fotos = extractor.extract(
        video, tmp_path / "salida", interval_seconds=0.5, max_frames=2, jpeg_quality=85
    )

    assert fotos
    assert all(not f.has_face for f in fotos)
