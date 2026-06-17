from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ExtractedFrame:
    path: Path
    frame_index: int
    timestamp_seconds: float
    blur_score: float
    brightness_score: float


class VideoFrameExtractor:
    def extract(
        self,
        video_path: str | Path,
        output_dir: str | Path,
        *,
        interval_seconds: float,
        max_frames: int,
        jpeg_quality: int,
        min_blur_score: float = 30.0,
        min_brightness: float = 35.0,
        max_brightness: float = 230.0,
    ) -> list[ExtractedFrame]:
        try:
            import cv2
        except Exception as exc:
            raise RuntimeError(
                "OpenCV no esta instalado. Instala opencv-python-headless para procesar videos."
            ) from exc

        source = Path(video_path)
        if not source.is_file():
            raise FileNotFoundError(f"Video no encontrado: {source}")
        destination = Path(output_dir)
        destination.mkdir(parents=True, exist_ok=True)

        capture = cv2.VideoCapture(str(source))
        if not capture.isOpened():
            raise ValueError(f"No se pudo abrir el video: {source.name}")

        fps = float(capture.get(cv2.CAP_PROP_FPS) or 0.0)
        if fps <= 0:
            fps = 30.0
        normalized_interval = float(interval_seconds)
        frame_step = 1 if normalized_interval <= 0 else max(int(round(fps * normalized_interval)), 1)
        frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        extracted: list[ExtractedFrame] = []
        seen_hashes: set[str] = set()

        frame_index = 0
        try:
            while frame_count <= 0 or frame_index < frame_count:
                capture.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
                ok, frame = capture.read()
                if not ok:
                    break
                candidate = self._build_candidate(
                    cv2=cv2,
                    frame=frame,
                    destination=destination,
                    frame_index=frame_index,
                    fps=fps,
                    jpeg_quality=jpeg_quality,
                )
                frame_hash = self._simple_frame_hash(cv2, frame)
                should_filter_duplicates = normalized_interval > 0
                if (
                    candidate.blur_score >= min_blur_score
                    and min_brightness <= candidate.brightness_score <= max_brightness
                    and (not should_filter_duplicates or frame_hash not in seen_hashes)
                ):
                    extracted.append(candidate)
                    seen_hashes.add(frame_hash)
                    if len(extracted) >= max(int(max_frames), 1):
                        break
                elif candidate.path.exists():
                    candidate.path.unlink()
                frame_index += frame_step
        finally:
            capture.release()

        if not extracted:
            raise ValueError("No se generaron fotos utiles desde el video.")
        return extracted

    @staticmethod
    def _build_candidate(
        *,
        cv2,
        frame,
        destination: Path,
        frame_index: int,
        fps: float,
        jpeg_quality: int,
    ) -> ExtractedFrame:
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        blur_score = float(cv2.Laplacian(gray, cv2.CV_64F).var())
        brightness_score = float(gray.mean())
        timestamp_seconds = float(frame_index / fps) if fps > 0 else 0.0
        path = destination / f"frame_{frame_index:08d}.jpg"
        cv2.imwrite(str(path), frame, [int(cv2.IMWRITE_JPEG_QUALITY), int(jpeg_quality)])
        return ExtractedFrame(
            path=path,
            frame_index=frame_index,
            timestamp_seconds=round(timestamp_seconds, 2),
            blur_score=round(blur_score, 2),
            brightness_score=round(brightness_score, 2),
        )

    @staticmethod
    def _simple_frame_hash(cv2, frame) -> str:
        small = cv2.resize(frame, (12, 12))
        gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
        average = float(gray.mean())
        bits = ["1" if value > average else "0" for row in gray for value in row]
        return "".join(bits)
