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
    _DB_BATCH_SIZE = 25

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
        pending_db_batch: list[tuple[int, Path, UploadItemResult, PhotoCreate]] = []

        self._emit_batch_progress(
            progress_callback,
            total_files=total_files,
            processed_count=0,
            success_count=0,
            pending_count=0,
            failed_count=0,
            current_index=0,
            status_text="Preparando archivos...",
        )

        for index, file_path in enumerate(file_paths, start=1):
            path = Path(file_path)
            item_progress_callback = self._build_batch_item_callback(
                progress_callback=progress_callback,
                total_files=total_files,
                results=results,
                pending_db_batch_count=len(pending_db_batch),
                current_index=index,
            )
            result, photo_create = self._upload_storage_stage(
                path,
                progress_callback=item_progress_callback,
            )
            if photo_create is None:
                results.append(result)
                self._emit_file_processed_progress(
                    progress_callback=progress_callback,
                    total_files=total_files,
                    results=results,
                    pending_db_batch_count=len(pending_db_batch),
                    current_index=index,
                    result=result,
                )
            else:
                self._mark_pending_database(result, progress_callback=item_progress_callback)
                pending_db_batch.append((index, path, result, photo_create))
            if len(pending_db_batch) >= self._DB_BATCH_SIZE:
                self._flush_pending_database_batch(
                    pending_db_batch,
                    delete_local_on_success=delete_local_on_success,
                    progress_callback=progress_callback,
                    total_files=total_files,
                    results=results,
                )
                pending_db_batch = []

        if pending_db_batch:
            self._flush_pending_database_batch(
                pending_db_batch,
                delete_local_on_success=delete_local_on_success,
                progress_callback=progress_callback,
                total_files=total_files,
                results=results,
            )

        success_count, failed_count, pending_count = self._summarize_results(
            results,
            pending_db_batch_count=0,
        )
        self._emit_batch_progress(
            progress_callback,
            total_files=total_files,
            processed_count=success_count + failed_count,
            success_count=success_count,
            pending_count=pending_count,
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
        result, photo_create = self._upload_storage_stage(
            path,
            progress_callback=progress_callback,
        )
        if photo_create is None:
            return result
        try:
            photo_record = self._create_photo_record(photo_create)
        except Exception as exc:
            return self._finalize_database_failure(
                result,
                path,
                exc,
                progress_callback=progress_callback,
            )
        return self._finalize_database_success(
            progress_callback,
            result,
            path,
            photo_record,
            delete_local_on_success=delete_local_on_success,
        )

    def _create_photo_record(
        self,
        photo: PhotoCreate,
    ) -> PhotoRecord:
        return self._photos_repository.create(photo)

    def _upload_storage_stage(
        self,
        path: Path,
        *,
        progress_callback: Callable[[UploadItemResult, str, str], None] | None = None,
    ) -> tuple[UploadItemResult, PhotoCreate | None]:
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
            return result, None

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
            return result, None

        return result, self._build_photo_create(path, photo_id, storage_path)

    def _build_photo_create(
        self,
        path: Path,
        photo_id: str,
        storage_path: str,
    ) -> PhotoCreate:
        return PhotoCreate(
            id=photo_id,
            original_filename=path.name,
            storage_path=storage_path,
            storage_bucket=self._settings.supabase_storage_bucket,
            status=PhotoStatus.AVAILABLE,
            source="uploader_app",
        )

    def _flush_pending_database_batch(
        self,
        pending_db_batch: list[tuple[int, Path, UploadItemResult, PhotoCreate]],
        *,
        delete_local_on_success: bool,
        progress_callback: Callable[[UploadBatchProgress], None] | None,
        total_files: int,
        results: list[UploadItemResult],
    ) -> None:
        finalized_items: list[tuple[int, UploadItemResult]] = []
        try:
            records_by_id = self._bulk_create_photo_records(
                [photo_create for _, _, _, photo_create in pending_db_batch]
            )
        except Exception:
            records_by_id = None

        if records_by_id is not None:
            for index, path, result, _photo_create in pending_db_batch:
                finalized_items.append(
                    (
                        index,
                        self._finalize_database_success(
                            self._build_batch_item_callback(
                                progress_callback=progress_callback,
                                total_files=total_files,
                                results=results,
                                pending_db_batch_count=max(len(pending_db_batch) - 1, 0),
                                current_index=index,
                            ),
                            result,
                            path,
                            records_by_id[result.photo_id or ""],
                            delete_local_on_success=delete_local_on_success,
                        ),
                    )
                )
        else:
            for index, path, result, photo_create in pending_db_batch:
                item_progress_callback = self._build_batch_item_callback(
                    progress_callback=progress_callback,
                    total_files=total_files,
                    results=results,
                    pending_db_batch_count=max(len(pending_db_batch) - 1, 0),
                    current_index=index,
                )
                try:
                    photo_record = self._create_photo_record(photo_create)
                    finalized = self._finalize_database_success(
                        item_progress_callback,
                        result,
                        path,
                        photo_record,
                        delete_local_on_success=delete_local_on_success,
                    )
                except Exception as exc:
                    finalized = self._finalize_database_failure(
                        result,
                        path,
                        exc,
                        progress_callback=item_progress_callback,
                    )
                finalized_items.append((index, finalized))

        for processed_in_flush, (index, finalized) in enumerate(finalized_items, start=1):
            results.append(finalized)
            self._emit_file_processed_progress(
                progress_callback=progress_callback,
                total_files=total_files,
                results=results,
                pending_db_batch_count=max(len(pending_db_batch) - processed_in_flush, 0),
                current_index=index,
                result=finalized,
            )

    def _bulk_create_photo_records(
        self,
        photos: list[PhotoCreate],
    ) -> dict[str, PhotoRecord]:
        bulk_create = getattr(self._photos_repository, "bulk_create", None)
        if not callable(bulk_create):
            raise AttributeError("bulk_create no disponible")
        records = bulk_create(photos)
        records_by_id = {record.id: record for record in records}
        expected_ids = {photo.id for photo in photos if photo.id}
        if set(records_by_id) != expected_ids:
            raise RuntimeError("bulk_create devolvio un conjunto incompleto de filas.")
        return records_by_id

    def _finalize_database_success(
        self,
        progress_callback: Callable[[UploadItemResult, str, str], None] | None,
        result: UploadItemResult,
        path: Path,
        photo_record: PhotoRecord,
        *,
        delete_local_on_success: bool,
    ) -> UploadItemResult:
        result.photo_id = photo_record.id
        result.storage_path = photo_record.storage_path
        result.database_inserted = True
        self._update_item_progress(
            progress_callback,
            result,
            status="Database OK",
            message=f"Finalizando {path.name}...",
        )

        result.success = True
        if delete_local_on_success:
            try:
                path.unlink()
                result.local_file_deleted = True
                result.local_cleanup_message = "Archivo local eliminado."
            except OSError as exc:
                result.local_cleanup_error = f"No se pudo borrar el archivo local: {exc}"
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

    def _finalize_database_failure(
        self,
        result: UploadItemResult,
        path: Path,
        exc: Exception,
        *,
        progress_callback: Callable[[UploadItemResult, str, str], None] | None = None,
    ) -> UploadItemResult:
        result.database_error = str(exc)
        rollback_error = self._rollback_storage_file(result.storage_path or "")
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

    def _mark_pending_database(
        self,
        result: UploadItemResult,
        *,
        progress_callback: Callable[[UploadItemResult, str, str], None] | None = None,
    ) -> None:
        result.message = "Storage upload completado. Pendiente de insert en batch DB."
        self._update_item_progress(
            progress_callback,
            result,
            status="Pendiente DB",
            message=result.message,
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
            progress_callback(result.model_copy(), status, message)

    @staticmethod
    def _emit_batch_progress(
        progress_callback: Callable[[UploadBatchProgress], None] | None,
        *,
        total_files: int,
        processed_count: int,
        success_count: int,
        pending_count: int,
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
                pending_count=pending_count,
                failed_count=failed_count,
                current_index=current_index,
                status_text=status_text,
                result=result.model_copy() if result is not None else None,
                current_file=current_file,
                current_file_status=current_file_status,
            )
        )

    def _build_batch_item_callback(
        self,
        *,
        progress_callback: Callable[[UploadBatchProgress], None] | None,
        total_files: int,
        results: list[UploadItemResult],
        pending_db_batch_count: int,
        current_index: int,
    ) -> Callable[[UploadItemResult, str, str], None]:
        def emit(item: UploadItemResult, status: str, message: str) -> None:
            success_count, failed_count, pending_count = self._summarize_results(
                results,
                pending_db_batch_count=pending_db_batch_count,
                current_item=item,
                current_status=status,
            )
            processed_count = success_count + failed_count + pending_count
            self._emit_batch_progress(
                progress_callback,
                total_files=total_files,
                processed_count=processed_count,
                success_count=success_count,
                pending_count=pending_count,
                failed_count=failed_count,
                current_index=current_index,
                status_text=self._build_batch_status_text(
                    total_files=total_files,
                    processed_count=processed_count,
                    current_index=current_index,
                    status=status,
                    fallback_message=message,
                ),
                result=item,
                current_file=item.original_filename,
                current_file_status=status,
            )

        return emit

    def _emit_file_processed_progress(
        self,
        *,
        progress_callback: Callable[[UploadBatchProgress], None] | None,
        total_files: int,
        results: list[UploadItemResult],
        pending_db_batch_count: int,
        current_index: int,
        result: UploadItemResult,
    ) -> None:
        success_count, failed_count, pending_count = self._summarize_results(
            results,
            pending_db_batch_count=pending_db_batch_count,
        )
        self._emit_batch_progress(
            progress_callback,
            total_files=total_files,
            processed_count=success_count + failed_count + pending_count,
            success_count=success_count,
            pending_count=pending_count,
            failed_count=failed_count,
            current_index=current_index,
            status_text=(
                f"Procesadas {success_count + failed_count + pending_count} de {total_files}."
                if (success_count + failed_count + pending_count) < total_files
                else "Finalizado"
            ),
            result=result,
            current_file=result.original_filename,
            current_file_status=result.processing_status,
        )

    @classmethod
    def _summarize_results(
        cls,
        results: list[UploadItemResult],
        *,
        pending_db_batch_count: int = 0,
        current_item: UploadItemResult | None = None,
        current_status: str | None = None,
    ) -> tuple[int, int, int]:
        success_count = sum(1 for item in results if cls._is_success_result(item))
        failed_count = sum(1 for item in results if cls._is_failed_result(item))
        pending_count = pending_db_batch_count
        if current_item is not None and current_status is not None:
            if cls._is_success_snapshot(current_item, current_status):
                success_count += 1
            elif cls._is_failed_snapshot(current_item, current_status):
                failed_count += 1
            elif cls._is_pending_db_snapshot(current_item, current_status):
                pending_count += 1
        return success_count, failed_count, pending_count

    @classmethod
    def _calculate_processed_count(
        cls,
        results: list[UploadItemResult],
        *,
        pending_db_batch_count: int = 0,
        current_item: UploadItemResult | None = None,
        current_status: str | None = None,
    ) -> int:
        success_count, failed_count, pending_count = cls._summarize_results(
            results,
            pending_db_batch_count=pending_db_batch_count,
            current_item=current_item,
            current_status=current_status,
        )
        return success_count + failed_count + pending_count

    @staticmethod
    def _is_success_result(item: UploadItemResult) -> bool:
        return item.success and item.database_inserted

    @staticmethod
    def _is_failed_result(item: UploadItemResult) -> bool:
        return (
            item.storage_error is not None
            or item.database_error is not None
            or item.processing_status in {"Error", "Movido a failed_uploads"}
        )

    @staticmethod
    def _is_pending_db_snapshot(item: UploadItemResult, status: str) -> bool:
        return (
            status == "Pendiente DB"
            or (
                item.storage_uploaded
                and not item.database_inserted
                and item.database_error is None
            )
        )

    @classmethod
    def _is_success_snapshot(cls, item: UploadItemResult, status: str) -> bool:
        return status == "Completado" or cls._is_success_result(item)

    @classmethod
    def _is_failed_snapshot(cls, item: UploadItemResult, status: str) -> bool:
        return status in {"Error", "Movido a failed_uploads"} or cls._is_failed_result(item)

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
            return f"Storage OK en {current_index} de {total_files}..."
        if status == "Pendiente DB":
            return f"Esperando batch DB para {current_index} de {total_files}..."
        if status == "Database OK":
            return f"Finalizando {current_index} de {total_files}..."
        if status == "Completado":
            return f"Procesadas {processed_count} de {total_files}."
        return fallback_message
