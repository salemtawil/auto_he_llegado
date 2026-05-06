from __future__ import annotations

from pathlib import Path
from shutil import move
from typing import Callable
from uuid import uuid4

from config.settings import Settings, get_settings
from core.enums import PhotoStatus
from core.models import PhotoCreate, PhotoRecord, UploadBatchProgress, UploadItemResult
from storage.photos_repository import PhotosRepository
from storage.supabase_client import SupabaseClientProvider


class UploaderService:
    def __init__(
        self,
        photos_repository: PhotosRepository | None = None,
        client_provider: SupabaseClientProvider | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._client_provider = client_provider or SupabaseClientProvider(self._settings)
        self._photos_repository = photos_repository or PhotosRepository(
            client_provider=self._client_provider,
            settings=self._settings,
        )
        self._failed_uploads_dir = self._settings.local_data_dir / "failed_uploads"
        self._failed_uploads_dir.mkdir(parents=True, exist_ok=True)

    def upload_files(
        self,
        file_paths: list[str | Path],
        *,
        delete_local_on_success: bool = False,
        progress_callback: Callable[[UploadBatchProgress], None] | None = None,
    ) -> list[UploadItemResult]:
        total_files = len(file_paths)
        results: list[UploadItemResult] = []
        success_count = 0
        failed_count = 0

        self._emit_batch_progress(
            progress_callback,
            total_files=total_files,
            processed_count=0,
            success_count=0,
            failed_count=0,
            current_index=0,
            status_text="Preparando archivos...",
        )

        for index, file_path in enumerate(file_paths, start=1):
            result = self.upload_file(
                file_path,
                delete_local_on_success=delete_local_on_success,
                progress_callback=lambda item, status, message, current_index=index: (
                    self._emit_batch_progress(
                        progress_callback,
                        total_files=total_files,
                        processed_count=len(results),
                        success_count=success_count,
                        failed_count=failed_count,
                        current_index=current_index,
                        status_text=self._build_batch_status_text(
                            total_files=total_files,
                            processed_count=len(results),
                            current_index=current_index,
                            status=status,
                            fallback_message=message,
                        ),
                        result=item,
                        current_file=item.original_filename,
                        current_file_status=status,
                    )
                ),
            )
            results.append(result)
            if result.success:
                success_count += 1
            else:
                failed_count += 1

            self._emit_batch_progress(
                progress_callback,
                total_files=total_files,
                processed_count=len(results),
                success_count=success_count,
                failed_count=failed_count,
                current_index=index,
                status_text=(
                    f"Procesadas {len(results)} de {total_files}."
                    if len(results) < total_files
                    else "Finalizado"
                ),
                result=result,
                current_file=result.original_filename,
                current_file_status=result.processing_status,
            )

        self._emit_batch_progress(
            progress_callback,
            total_files=total_files,
            processed_count=len(results),
            success_count=success_count,
            failed_count=failed_count,
            current_index=total_files,
            status_text="Finalizado",
        )
        return results

    def upload_file(
        self,
        file_path: str | Path,
        *,
        delete_local_on_success: bool = False,
        progress_callback: Callable[[UploadItemResult, str, str], None] | None = None,
    ) -> UploadItemResult:
        path = Path(file_path)
        photo_id = str(uuid4())
        storage_path = f"available/{photo_id}.jpg"
        result = UploadItemResult(
            source_path=str(path),
            original_filename=path.name,
            photo_id=photo_id,
            storage_path=storage_path,
            success=False,
            message="Proceso no iniciado.",
        )
        self._update_item_progress(
            progress_callback,
            result,
            status="Subiendo",
            message=f"Subiendo archivo {path.name}...",
        )

        try:
            self._validate_source_file(path)
        except Exception as exc:
            result.storage_error = str(exc)
            result.local_cleanup_message = "Archivo local conservado."
            result.processing_status = "Error"
            result.message = f"Fallo antes de storage upload: {result.storage_error}"
            self._update_item_progress(
                progress_callback,
                result,
                status=result.processing_status,
                message=result.message,
            )
            return result

        try:
            self._client_provider.upload_binary(
                bucket_name=self._settings.supabase_storage_bucket,
                storage_path=storage_path,
                content=path.read_bytes(),
            )
            result.storage_uploaded = True
            self._update_item_progress(
                progress_callback,
                result,
                status="Storage OK",
                message=f"Registrando {path.name} en base de datos...",
            )
        except Exception as exc:
            result.storage_error = str(exc)
            self._apply_failed_upload_local_cleanup(result, path)
            result.message = f"Fallo en storage upload: {result.storage_error}"
            self._update_item_progress(
                progress_callback,
                result,
                status=result.processing_status,
                message=result.message,
            )
            return result

        try:
            photo_record = self._create_photo_record(path, photo_id, storage_path)
            result.photo_id = photo_record.id
            result.storage_path = photo_record.storage_path
            result.database_inserted = True
            self._update_item_progress(
                progress_callback,
                result,
                status="Database OK",
                message=f"Finalizando {path.name}...",
            )
        except Exception as exc:
            result.database_error = str(exc)
            rollback_error = self._rollback_storage_file(storage_path)
            self._apply_failed_upload_local_cleanup(result, path)
            result.message = (
                "Storage upload completado, pero fallo el registro en base de datos: "
                f"{result.database_error}"
            )
            if rollback_error:
                result.message = (
                    f"{result.message} No se pudo revertir el archivo en Storage: "
                    f"{rollback_error}"
                )
            self._update_item_progress(
                progress_callback,
                result,
                status=result.processing_status,
                message=result.message,
            )
            return result

        result.success = True
        if delete_local_on_success:
            try:
                path.unlink()
                result.local_file_deleted = True
                result.local_cleanup_message = "Archivo local eliminado."
            except OSError as exc:
                result.local_cleanup_error = (
                    "No se pudo borrar el archivo local: "
                    f"{exc}"
                )
        else:
            result.local_cleanup_message = "Archivo local conservado."

        if result.local_cleanup_error:
            result.message = (
                "Storage upload y database insert completados, "
                f"pero fallo el local cleanup: {result.local_cleanup_error}"
            )
        else:
            result.message = "Storage upload y database insert completados."
        result.processing_status = "Completado"
        self._update_item_progress(
            progress_callback,
            result,
            status=result.processing_status,
            message=result.message,
        )
        return result

    def _create_photo_record(
        self,
        path: Path,
        photo_id: str,
        storage_path: str,
    ) -> PhotoRecord:
        return self._photos_repository.create(
            PhotoCreate(
                id=photo_id,
                original_filename=path.name,
                storage_path=storage_path,
                status=PhotoStatus.AVAILABLE,
                source="uploader_app",
            )
        )

    @staticmethod
    def _validate_source_file(path: Path) -> None:
        if not path.exists() or not path.is_file():
            raise FileNotFoundError(f"Archivo no encontrado: {path}")
        if path.suffix.lower() not in {".jpg", ".jpeg"}:
            raise ValueError(f"Formato no soportado: {path.name}")

    def _move_to_failed_uploads(self, path: Path) -> str | None:
        if not path.exists():
            return None
        destination = self._build_failed_destination(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        move(str(path), str(destination))
        return str(destination)

    def _build_failed_destination(self, path: Path) -> Path:
        candidate = self._failed_uploads_dir / path.name
        if not candidate.exists():
            return candidate
        stem = path.stem
        suffix = path.suffix
        counter = 1
        while True:
            candidate = self._failed_uploads_dir / f"{stem}_{counter}{suffix}"
            if not candidate.exists():
                return candidate
            counter += 1

    def _rollback_storage_file(self, storage_path: str) -> str | None:
        try:
            self._client_provider.remove_file(
                bucket_name=self._settings.supabase_storage_bucket,
                storage_path=storage_path,
            )
        except Exception as exc:
            return str(exc)
        return None

    def _apply_failed_upload_local_cleanup(
        self,
        result: UploadItemResult,
        path: Path,
    ) -> None:
        try:
            result.failed_file_path = self._move_to_failed_uploads(path)
            if result.failed_file_path:
                result.processing_status = "Movido a failed_uploads"
                result.local_cleanup_message = (
                    f"Archivo movido a failed_uploads: {result.failed_file_path}"
                )
            else:
                result.processing_status = "Error"
                result.local_cleanup_message = (
                    "No fue necesario mover el archivo local."
                )
        except OSError as exc:
            result.processing_status = "Error"
            result.local_cleanup_error = (
                "No se pudo mover el archivo a failed_uploads: "
                f"{exc}"
            )

    @staticmethod
    def _update_item_progress(
        progress_callback: Callable[[UploadItemResult, str, str], None] | None,
        result: UploadItemResult,
        *,
        status: str,
        message: str,
    ) -> None:
        result.processing_status = status
        if progress_callback is not None:
            progress_callback(result.model_copy(deep=True), status, message)

    @staticmethod
    def _emit_batch_progress(
        progress_callback: Callable[[UploadBatchProgress], None] | None,
        *,
        total_files: int,
        processed_count: int,
        success_count: int,
        failed_count: int,
        current_index: int,
        status_text: str,
        result: UploadItemResult | None = None,
        current_file: str | None = None,
        current_file_status: str | None = None,
    ) -> None:
        if progress_callback is None:
            return
        progress_callback(
            UploadBatchProgress(
                total_files=total_files,
                processed_count=processed_count,
                success_count=success_count,
                failed_count=failed_count,
                current_index=current_index,
                status_text=status_text,
                result=result.model_copy(deep=True) if result is not None else None,
                current_file=current_file,
                current_file_status=current_file_status,
            )
        )

    @staticmethod
    def _build_batch_status_text(
        *,
        total_files: int,
        processed_count: int,
        current_index: int,
        status: str,
        fallback_message: str,
    ) -> str:
        if status == "Subiendo":
            return f"Subiendo {current_index} de {total_files}..."
        if status == "Storage OK":
            return "Registrando en base de datos..."
        if status == "Database OK":
            return f"Finalizando {current_index} de {total_files}..."
        if status == "Completado":
            return f"Procesadas {processed_count + 1} de {total_files}."
        return fallback_message
