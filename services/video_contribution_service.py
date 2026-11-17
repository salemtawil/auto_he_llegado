from __future__ import annotations

from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import shutil
from time import sleep
from typing import Callable

from config.settings import Settings, get_settings
from core.errors import ErrorParaElAgente
from services.access_service import AccessService
from services.auth_context import AuthSession, require_current_session
from services.photo_review_service import PhotoBatchRecord, PhotoReviewService
from services.telegram_notification_service import TelegramNotificationService
from services.video_delivery_service import GoogleDriveVideoDeliveryService
from services.video_fingerprint_service import VideoFingerprintService
from services.video_frame_extractor import ExtractedFrame, VideoFrameExtractor


@dataclass(frozen=True)
class VideoContributionProgress:
    phase: str
    message: str
    current: int = 0
    total: int = 0


@dataclass(frozen=True)
class VideoContributionResult:
    batch: PhotoBatchRecord
    frames_extracted: int
    candidates_uploaded: int


class VideoContributionService:
    _DB_BATCH_SIZE = 25
    _MAX_CONCURRENT_UPLOADS = 3
    _RETRY_DELAYS_SECONDS = (0.8, 1.6, 3.0)

    def __init__(
        self,
        review_service: PhotoReviewService | None = None,
        extractor: VideoFrameExtractor | None = None,
        delivery_service: GoogleDriveVideoDeliveryService | None = None,
        notification_service: TelegramNotificationService | None = None,
        fingerprint_service: VideoFingerprintService | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._review_service = review_service or PhotoReviewService(settings=self._settings)
        self._extractor = extractor or VideoFrameExtractor()
        self._delivery_service = delivery_service or GoogleDriveVideoDeliveryService(self._settings)
        self._notification_service = notification_service or TelegramNotificationService(self._settings)
        self._fingerprint_service = fingerprint_service or VideoFingerprintService()
        self._work_dir = self._settings.local_data_dir / "video_frames"
        self._work_dir.mkdir(parents=True, exist_ok=True)

    # Lotes que no cuentan como "este video ya se subio": su subida nunca
    # llego a buen puerto, asi que el agente tiene que poder reintentarla.
    _ESTADOS_FALLIDOS = frozenset({"rejected", "failed", "deleted"})

    def submit_video(
        self,
        video_path: str | Path,
        *,
        session: AuthSession | None = None,
        progress_callback: Callable[[VideoContributionProgress], None] | None = None,
    ) -> VideoContributionResult:
        session = session or require_current_session()
        source = Path(video_path)
        week_start = AccessService.current_week_start()
        # Los dos caminos -archivar el video en Drive y sacarle fotogramas- se
        # excluian, y eso dejaba la rama de fotogramas SIN la huella, sin la
        # duracion minima y sin la deteccion de repetidos, que solo vivian en
        # la de Drive. Con el video como prueba de trabajo semanal, aceptar el
        # mismo cada semana se cargaba el motivo de pedirlo.
        #
        # Ahora las comprobaciones son comunes y cada camino se hace o no se
        # hace por separado.
        modo = (self._settings.video_submission_mode or "drive").strip().lower()
        archivar_en_drive = modo in ("drive", "both")
        extraer_fotogramas = modo in ("frames", "both")

        self._emit(progress_callback, "fingerprinting", "Validando si el video ya fue cargado...")
        fingerprint = self._fingerprint_service.build(source)
        self._validate_min_duration(fingerprint.duration_seconds)
        existing_batches = self._review_service.list_video_fingerprint_candidates()
        # Contra que se compara. Aqui habia un filtro que se quedaba solo con
        # los lotes "entregados" -los que tenian delivery_file_id- y eso
        # dejaba la deteccion de repetidos MUERTA: la consulta ni siquiera
        # pedia esa columna, asi que el filtro vaciaba la lista SIEMPRE y
        # `find_duplicate` recibia cero lotes con los que comparar. En
        # cualquier modo, desde que se escribio. Y sin respaldo en Drive no
        # habria delivery_file_id nunca, asi que el fallo se volvia
        # permanente.
        #
        # Lo que queda reconcilia las dos decisiones escritas en las pruebas:
        # un lote que FALLO no bloquea reintentar ese video -su subida nunca
        # conto-, y cualquier otro si, aunque se quedara a medias.
        comparables = [
            row
            for row in existing_batches
            if str(row.get("status") or "").strip().lower() not in self._ESTADOS_FALLIDOS
        ]
        duplicate = self._fingerprint_service.find_duplicate(
            fingerprint,
            comparables,
            similarity_threshold=self._settings.video_duplicate_similarity_threshold,
            hamming_threshold=self._settings.video_duplicate_hamming_threshold,
        )
        batch = self._review_service.create_batch(
            user_id=session.user_id,
            week_start=week_start,
            original_video_name=source.name,
            video_sha256=fingerprint.sha256,
            video_size_bytes=fingerprint.size_bytes,
            video_duration_seconds=fingerprint.duration_seconds,
            video_width=fingerprint.width,
            video_height=fingerprint.height,
            video_fingerprint=fingerprint.as_payload(),
            duplicate_score=duplicate.score if duplicate is not None else None,
            duplicate_of_batch_id=duplicate.batch_id if duplicate is not None else None,
        )
        if duplicate is not None:
            message = (
                "Este video parece repetido. "
                f"Similitud visual: {duplicate.score:.0%}. "
                f"Lote similar: {duplicate.batch_id}."
            )
            self._review_service.mark_batch_failed(batch.id, message)
            raise ErrorParaElAgente(message)

        self._emit(
            progress_callback,
            "received",
            "Video registrado. Acceso temporal activo mientras se revisa.",
            current=0,
            total=1,
        )
        delivery = None
        if archivar_en_drive:
            self._emit(progress_callback, "uploading", "Subiendo video completo a Google Drive...")
            try:
                delivery = self._delivery_service.upload_video(
                    source,
                    display_name=self._drive_display_name(
                        source, session=session, batch_id=batch.id
                    ),
                )
            except Exception as exc:
                message = f"No se pudo subir el video a Google Drive: {exc}"
                self._review_service.mark_batch_failed(batch.id, message)
                self._emit(progress_callback, "failed", message, current=0, total=1)
                raise ErrorParaElAgente(message) from exc

        frames_extracted = 0
        candidates_uploaded = 0
        if extraer_fotogramas:
            # Si la extraccion falla, el video YA esta archivado en Drive y el
            # agente ya cumplio: no se tumba el lote por eso. Se anota y se
            # sigue, que es lo que separa "no tengo tus fotos" de "no tengo tu
            # video".
            try:
                frames_extracted, candidates_uploaded = self._extraer_fotogramas(
                    source,
                    batch_id=batch.id,
                    user_id=session.user_id,
                    progress_callback=progress_callback,
                )
            except Exception as exc:  # noqa: BLE001
                if not archivar_en_drive:
                    self._review_service.mark_batch_failed(batch.id, str(exc))
                    raise
                self._emit(
                    progress_callback,
                    "extraction_warning",
                    f"El video quedo guardado, pero no se pudieron sacar las fotos: {exc}",
                    current=0,
                    total=1,
                )

        # Los datos de Drive solo se mandan si hubo Drive: `finish_batch` ya
        # ignora los None, pero pasarlos igual hace creer que siempre hay
        # entrega.
        entrega = {}
        if delivery is not None:
            entrega = {
                "delivery_provider": delivery.provider,
                "delivery_file_id": delivery.file_id,
                "delivery_url": delivery.url,
            }
        # `status` SI va explicito aunque coincida con el valor por defecto de
        # finish_batch: es el contrato con la puerta de acceso. Un lote nace en
        # "pending_review" y ese estado tiene que estar en
        # AccessService.ACTIVE_BATCH_STATUSES, porque la revision de fotos esta
        # deshabilitada y si el desbloqueo dependiera de aprobar, los agentes
        # quedarian bloqueados para siempre. Lo vigila
        # tests/test_video_gate_contract.py leyendo este literal.
        final_batch = self._review_service.finish_batch(
            batch_id=batch.id,
            frames_extracted=frames_extracted,
            candidates_uploaded=candidates_uploaded,
            status="pending_review",
            **entrega,
        )
        # El aviso se manda haya Drive o no: es como te enteras de que alguien
        # subio su video. Antes solo salia si habia entrega, asi que sin
        # respaldo te quedabas sin enterarte de nada.
        try:
            self._notification_service.send_video_received(
                user_label=session.display_name or session.email or session.user_id,
                original_name=source.name,
                size_bytes=fingerprint.size_bytes,
                duration_seconds=fingerprint.duration_seconds,
                drive_url=delivery.url if delivery is not None else "",
                fotos_subidas=candidates_uploaded if extraer_fotogramas else None,
            )
        except Exception as exc:
            self._emit(
                progress_callback,
                "notification_warning",
                f"El video se guardo, pero fallo el aviso por Telegram: {exc}",
                current=1,
                total=1,
            )

        self._emit(
            progress_callback,
            "done",
            self._resumen_final(
                archivado=delivery is not None,
                candidatas=candidates_uploaded,
                extraccion_pedida=extraer_fotogramas,
            ),
            current=1,
            total=1,
        )
        return VideoContributionResult(
            batch=final_batch,
            frames_extracted=frames_extracted,
            candidates_uploaded=candidates_uploaded,
        )

    @staticmethod
    def _resumen_final(*, archivado: bool, candidatas: int, extraccion_pedida: bool) -> str:
        """Lo que se le dice al agente al terminar: lo que paso, no el modo."""

        partes = []
        if archivado:
            partes.append("Video guardado y admin notificado")
        if extraccion_pedida:
            if candidatas:
                partes.append(f"{candidatas} foto(s) sacadas del video")
            else:
                partes.append("no se pudo sacar ninguna foto util del video")
        if not partes:
            return "Video recibido."
        return ". ".join(partes) + "."

    def _extraer_fotogramas(
        self,
        source: Path,
        *,
        batch_id: str,
        user_id: str,
        progress_callback: Callable[[VideoContributionProgress], None] | None = None,
    ) -> tuple[int, int]:
        """Saca las fotos utiles del video y las sube como candidatas.

        Solo eso: ni crea el lote ni lo cierra ni decide si el video vale.
        Esas tres cosas son comunes a los dos caminos y viven en
        `submit_video`, porque meterlas aqui fue lo que dejo a la rama de
        fotogramas sin huella, sin duracion minima y sin repetidos.

        Devuelve (fotogramas extraidos, candidatas subidas).
        """

        batch_dir = self._work_dir / batch_id
        self._emit(progress_callback, "extracting", "Extrayendo fotos utiles del video...")
        try:
            frames = self._extractor.extract(
                source,
                batch_dir,
                interval_seconds=self._intervalo_de_fotogramas(),
                max_frames=self._settings.video_max_candidate_frames,
                jpeg_quality=self._settings.video_jpeg_quality,
                tamano_de_huella=self._settings.video_frame_dedupe_size,
            )
            subidas = self._upload_frames(
                frames,
                batch_id=batch_id,
                user_id=user_id,
                progress_callback=progress_callback,
            )
            return len(frames), subidas
        finally:
            shutil.rmtree(batch_dir, ignore_errors=True)

    def _intervalo_de_fotogramas(self) -> float:
        """Cada cuantos segundos se mira un fotograma.

        Ahora el valor por defecto es 0, y 0 SI significa todos.

        Antes no podia significarlo: el 0 apagaba de paso el filtro de
        repetidos, porque estaban atados. Desatados, mirar todos los
        fotogramas es lo que mas fotos da, que es lo que el pool necesita.

        Historia de los numeros: 2 segundos daba SEIS fotos de un video de
        10 s -no las seis mejores, las unicas seis miradas-. Bajarlo a 0.2
        subio a treinta y pico, y ahi se vio que el techo real no era el
        muestreo sino la huella de repetidos.
        """

        try:
            intervalo = float(self._settings.video_frame_interval_seconds)
        except (TypeError, ValueError):
            intervalo = 0.0
        return intervalo if intervalo > 0 else self.INTERVALO_POR_DEFECTO_S

    # Un fotograma cada dos segundos: suficiente para que dos fotos seguidas
    # no sean la misma cara en la misma pose, y deja ~15 candidatas de un
    # video de medio minuto.
    INTERVALO_POR_DEFECTO_S = 0.0

    @staticmethod
    def _drive_display_name(source: Path, *, session: AuthSession, batch_id: str) -> str:
        user_label = (session.display_name or session.email or session.user_id).strip()
        safe_user = "".join(char if char.isalnum() or char in ("-", "_", ".") else "_" for char in user_label)
        return f"{safe_user}_{batch_id}_{source.name}"

    def _validate_min_duration(self, duration_seconds: float) -> None:
        minimum = max(float(self._settings.video_min_duration_seconds), 0.0)
        if minimum <= 0 or duration_seconds >= minimum:
            return
        raise ErrorParaElAgente(
            "El video debe durar minimo "
            f"{self._format_duration(minimum)}. "
            f"Duracion detectada: {self._format_duration(duration_seconds)}."
        )

    @staticmethod
    def _format_duration(duration_seconds: float) -> str:
        seconds_value = max(float(duration_seconds), 0.0)
        minutes = int(seconds_value // 60)
        seconds = seconds_value - (minutes * 60)
        seconds_text = f"{seconds:.1f}".rstrip("0").rstrip(".")
        if minutes:
            return f"{minutes} min {seconds_text.zfill(2)} s"
        return f"{seconds_text} s"

    def _upload_frames(
        self,
        frames: list[ExtractedFrame],
        *,
        batch_id: str,
        user_id: str,
        progress_callback: Callable[[VideoContributionProgress], None] | None,
    ) -> int:
        total = len(frames)
        uploaded_count = 0
        pending_candidates: list[dict] = []
        max_workers = min(self._MAX_CONCURRENT_UPLOADS, max(total, 1))
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            uploaded_candidates = executor.map(
                lambda current_frame: self._upload_single_frame(
                    current_frame,
                    batch_id=batch_id,
                    user_id=user_id,
                ),
                frames,
            )
            for index, candidate in enumerate(uploaded_candidates, start=1):
                uploaded_count += 1
                pending_candidates.append(candidate)
                self._emit(
                    progress_callback,
                    "uploading",
                    f"Subiendo foto candidata {index} de {total}...",
                    current=index,
                    total=total,
                )
                if len(pending_candidates) >= self._DB_BATCH_SIZE:
                    self._flush_candidates(pending_candidates)
                    pending_candidates = []
        if pending_candidates:
            self._flush_candidates(pending_candidates)
        return uploaded_count

    def _upload_single_frame(self, frame: ExtractedFrame, *, batch_id: str, user_id: str) -> dict:
        candidate_id = frame.path.stem
        storage_path = f"candidates/{user_id}/{batch_id}/{candidate_id}.jpg"
        self._retry_supabase_write(
            lambda current_path=storage_path, current_frame=frame: self._review_service.upload_candidate_binary(
                storage_path=current_path,
                content=current_frame.path.read_bytes(),
            )
        )
        return {
            "batch_id": batch_id,
            "user_id": user_id,
            "storage_path": storage_path,
            "original_name": frame.path.name,
            "frame_index": frame.frame_index,
            "timestamp_seconds": frame.timestamp_seconds,
            "blur_score": frame.blur_score,
            "brightness_score": frame.brightness_score,
        }

    def _flush_candidates(self, candidates: list[dict]) -> None:
        self._retry_supabase_write(lambda: self._review_service.create_candidates(candidates))

    def _retry_supabase_write(self, operation) -> None:
        last_error: Exception | None = None
        for delay_index, delay_seconds in enumerate((0.0, *self._RETRY_DELAYS_SECONDS)):
            if delay_seconds > 0:
                sleep(delay_seconds)
            try:
                operation()
                return
            except Exception as exc:
                last_error = exc
                if not self._is_retryable_supabase_error(exc) or delay_index >= len(self._RETRY_DELAYS_SECONDS):
                    raise
        if last_error is not None:
            raise last_error

    @staticmethod
    def _is_retryable_supabase_error(exc: Exception) -> bool:
        message = str(exc).lower()
        return any(
            marker in message
            for marker in (
                "too_many_connections",
                "too many connections",
                "statuscode': 429",
                "statuscode\": 429",
                "timeout",
                "temporarily unavailable",
            )
        )

    @staticmethod
    def _emit(
        callback: Callable[[VideoContributionProgress], None] | None,
        phase: str,
        message: str,
        *,
        current: int = 0,
        total: int = 0,
    ) -> None:
        if callback is not None:
            callback(
                VideoContributionProgress(
                    phase=phase,
                    message=message,
                    current=current,
                    total=total,
                )
            )
