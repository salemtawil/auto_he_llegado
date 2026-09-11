from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path


@dataclass(frozen=True)
class VideoFingerprint:
    sha256: str
    size_bytes: int
    duration_seconds: float
    width: int
    height: int
    fps: float
    hashes: tuple[str, ...]

    def as_payload(self) -> dict:
        return {
            "version": "dhash-v1",
            "hashes": list(self.hashes),
            "sample_count": len(self.hashes),
            "duration_seconds": round(self.duration_seconds, 3),
            "width": self.width,
            "height": self.height,
            "fps": round(self.fps, 3),
        }


@dataclass(frozen=True)
class VideoDuplicateMatch:
    batch_id: str
    score: float
    matched_hashes: int
    compared_hashes: int


class VideoFingerprintService:
    def __init__(self, *, sample_count: int = 24) -> None:
        self._sample_count = max(int(sample_count), 4)

    def build(self, video_path: str | Path) -> VideoFingerprint:
        path = Path(video_path)
        if not path.exists() or not path.is_file():
            raise FileNotFoundError(f"Video no encontrado: {path}")
        return self._build_with_cv2(path)

    def find_duplicate(
        self,
        fingerprint: VideoFingerprint,
        existing_batches: list[dict],
        *,
        similarity_threshold: float,
        hamming_threshold: int,
    ) -> VideoDuplicateMatch | None:
        best_match: VideoDuplicateMatch | None = None
        for row in existing_batches:
            batch_id = str(row.get("id") or "")
            payload = row.get("video_fingerprint") or {}
            if not batch_id or not isinstance(payload, dict):
                continue
            existing_hashes = tuple(str(item) for item in payload.get("hashes") or [] if item)
            if not existing_hashes:
                continue
            score, matched, compared = self._similarity(
                fingerprint.hashes,
                existing_hashes,
                hamming_threshold=max(int(hamming_threshold), 0),
            )
            if best_match is None or score > best_match.score:
                best_match = VideoDuplicateMatch(
                    batch_id=batch_id,
                    score=score,
                    matched_hashes=matched,
                    compared_hashes=compared,
                )
        if best_match is None:
            return None
        if best_match.score < max(min(float(similarity_threshold), 1.0), 0.0):
            return None
        return best_match

    def _build_with_cv2(self, path: Path) -> VideoFingerprint:
        import cv2

        capture = cv2.VideoCapture(str(path))
        if not capture.isOpened():
            raise RuntimeError(f"No se pudo abrir el video: {path.name}")
        try:
            frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
            fps = float(capture.get(cv2.CAP_PROP_FPS) or 0.0)
            width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
            height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
            duration_seconds = float(frame_count / fps) if frame_count > 0 and fps > 0 else 0.0
            hashes = self._sample_hashes(cv2, capture, frame_count=frame_count)
        finally:
            capture.release()
        return VideoFingerprint(
            sha256=self._sha256_file(path),
            size_bytes=path.stat().st_size,
            duration_seconds=duration_seconds,
            width=width,
            height=height,
            fps=fps,
            hashes=tuple(hashes),
        )

    def _sample_hashes(self, cv2, capture, *, frame_count: int) -> list[str]:
        if frame_count <= 0:
            return []
        if frame_count <= self._sample_count:
            positions = list(range(frame_count))
        else:
            positions = [
                round(index * (frame_count - 1) / (self._sample_count - 1))
                for index in range(self._sample_count)
            ]
        hashes: list[str] = []
        for position in positions:
            capture.set(cv2.CAP_PROP_POS_FRAMES, int(position))
            ok, frame = capture.read()
            if not ok or frame is None:
                continue
            hashes.append(self._dhash(cv2, frame))
        return hashes

    @staticmethod
    def _dhash(cv2, frame) -> str:
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        resized = cv2.resize(gray, (9, 8))
        diff = resized[:, 1:] > resized[:, :-1]
        value = 0
        for bit in diff.flatten():
            value = (value << 1) | int(bool(bit))
        return f"{value:016x}"

    @staticmethod
    def _similarity(
        current_hashes: tuple[str, ...],
        existing_hashes: tuple[str, ...],
        *,
        hamming_threshold: int,
    ) -> tuple[float, int, int]:
        if not current_hashes or not existing_hashes:
            return 0.0, 0, 0
        matched = 0
        for current in current_hashes:
            current_value = int(current, 16)
            best_distance = min(
                (current_value ^ int(existing, 16)).bit_count()
                for existing in existing_hashes
            )
            if best_distance <= hamming_threshold:
                matched += 1
        compared = len(current_hashes)
        return matched / compared, matched, compared

    @staticmethod
    def _sha256_file(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
