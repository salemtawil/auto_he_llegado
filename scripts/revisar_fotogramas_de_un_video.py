"""Mira que sacaria la app de un video REAL, sin subir nada a ningun sitio.

Para ajustar el umbral de cara con datos en vez de a ojo. Uso:

    .venv\\Scripts\\python.exe scripts\\revisar_fotogramas_de_un_video.py C:\\ruta\\al\\video.mp4

Escribe los JPG elegidos en una carpeta temporal y dice, de cada uno, cuanto
ocupa la cara, la nitidez y el brillo. No toca Supabase, ni Drive, ni el pool.
"""

from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.video_frame_extractor import VideoFrameExtractor  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("video", type=Path)
    parser.add_argument("--intervalo", type=float, default=2.0, help="segundos entre muestras")
    parser.add_argument("--maximo", type=int, default=40, help="cuantas fotos como mucho")
    parser.add_argument(
        "--umbral-cara",
        type=float,
        default=None,
        help=f"ancho minimo de cara (por defecto {VideoFrameExtractor.MIN_FACE_RATIO})",
    )
    parser.add_argument("--salida", type=Path, default=None)
    args = parser.parse_args()

    if not args.video.is_file():
        print(f"No existe el video: {args.video}")
        return 1

    salida = args.salida or Path(tempfile.mkdtemp(prefix="fotogramas_"))
    extractor = VideoFrameExtractor()
    if not extractor._cargar_detectores(__import__("cv2")):  # noqa: SLF001
        print("AVISO: esta instalacion de OpenCV no trae los clasificadores de cara.")
        print("       Se elegira solo por nitidez y luz, como antes.\n")

    fotos = extractor.extract(
        args.video,
        salida,
        interval_seconds=args.intervalo,
        max_frames=args.maximo,
        jpeg_quality=88,
        min_face_ratio=args.umbral_cara,
    )

    con_cara = sum(1 for f in fotos if f.has_face)
    print(f"Video:  {args.video.name}")
    print(f"Fotos:  {len(fotos)}  ({con_cara} con cara, {len(fotos) - con_cara} sin)")
    print(f"Salida: {salida}\n")
    print(f"{'segundo':>8}  {'cara %':>7}  {'nitidez':>8}  {'brillo':>7}  archivo")
    for foto in fotos:
        print(
            f"{foto.timestamp_seconds:>8.1f}  {foto.face_score * 100:>6.1f}%"
            f"  {foto.blur_score:>8.1f}  {foto.brightness_score:>7.1f}  {foto.path.name}"
        )

    if not con_cara:
        print(
            "\nNinguna llego al umbral de cara. Abre las fotos: si se ve la cara"
            "\nbien, el umbral esta demasiado alto para estos videos."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
