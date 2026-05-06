from __future__ import annotations

from contextlib import suppress
from datetime import datetime, timedelta, timezone
from pathlib import Path
import shutil

from config.settings import Settings, get_settings
from core.enums import PhotoStatus
from core.models import PhotoRecord, PhotoUpdate
from storage.photos_repository import PhotosRepository
from storage.supabase_client import SupabaseClientProvider


class MaintenanceService:
    def __init__(
        self,
        *,
        settings: Settings | None = None,
        photos_repository: PhotosRepository | None = None,
        client_provider: SupabaseClientProvider | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._photos_repository = photos_repository or PhotosRepository(settings=self._settings)
        self._client_provider = client_provider or SupabaseClientProvider(self._settings)
        self._local_data_dir = self._settings.local_data_dir.resolve()

    def audit(
        self,
        *,
        stale_reserved_hours: int = 12,
        archive_after_days: int = 7,
        include_storage: bool = True,
        storage_limit: int = 1000,
    ) -> dict:
        report = {
            "generated_at": self._utcnow().isoformat(),
            "supabase_enabled": self._settings.supabase_enabled,
            "local_data": self.audit_local_data(),
            "photos": self.audit_photo_pool(
                stale_reserved_hours=stale_reserved_hours,
                archive_after_days=archive_after_days,
            ),
        }
        if include_storage and self._settings.supabase_enabled:
            report["storage"] = self.audit_storage(storage_limit=storage_limit)
        return report

    def audit_local_data(self) -> dict:
        targets = {
            "temp_photos": self._local_data_dir / "temp_photos",
            "failed_uploads": self._local_data_dir / "failed_uploads",
            "results": self._local_data_dir / "results",
            "results_screenshots": self._local_data_dir / "results" / "screenshots",
            "debug": self._local_data_dir / "debug",
            "browser_profiles": self._local_data_dir / "browser_profiles",
            "logs": self._local_data_dir / "logs",
        }
        report: dict[str, dict] = {}
        for name, path in targets.items():
            report[name] = self._summarize_path(path)
        return report

    def audit_photo_pool(
        self,
        *,
        stale_reserved_hours: int = 12,
        archive_after_days: int = 7,
        sample_limit_per_status: int = 200,
    ) -> dict:
        counts = {
            status.value: self._photos_repository.count_by_status(status)
            for status in (
                PhotoStatus.AVAILABLE,
                PhotoStatus.RESERVED,
                PhotoStatus.CONSUMED,
                PhotoStatus.ARCHIVED,
                PhotoStatus.FAILED,
            )
        }
        reserved_records = self._photos_repository.list(status=PhotoStatus.RESERVED, limit=sample_limit_per_status)
        consumed_records = self._photos_repository.list(status=PhotoStatus.CONSUMED, limit=sample_limit_per_status)
        stale_reserved_cutoff = self._utcnow() - timedelta(hours=max(stale_reserved_hours, 1))
        archive_cutoff = self._utcnow() - timedelta(days=max(archive_after_days, 1))
        stale_reserved = [
            self._serialize_photo(record)
            for record in reserved_records
            if record.reserved_at is not None and record.reserved_at <= stale_reserved_cutoff
        ]
        archive_candidates = [
            self._serialize_photo(record)
            for record in consumed_records
            if record.consumed_at is not None and record.consumed_at <= archive_cutoff
        ]
        return {
            "counts": counts,
            "used_photo_rule_current_code": (
                "La foto queda consumida cuando el flujo termina y llama consume_photo, "
                "incluyendo retries exitosos o fallidos despues de reservarla."
            ),
            "stale_reserved_candidates": stale_reserved,
            "archive_candidates": archive_candidates,
            "sample_limit_per_status": sample_limit_per_status,
        }

    def audit_storage(self, *, storage_limit: int = 1000) -> dict:
        records = self._sample_photo_records(limit_per_status=min(max(storage_limit, 200), 500))
        db_paths = {
            self._normalize_storage_path(record.storage_path)
            for record in records
            if record.storage_path
        }
        available_files = self._list_storage_paths("available", limit=storage_limit)
        archived_files = self._list_storage_paths("archived", limit=storage_limit)
        storage_paths = set(available_files) | set(archived_files)
        orphan_storage_files = sorted(path for path in storage_paths if path not in db_paths)
        missing_storage_files = sorted(
            path for path in db_paths if path.startswith(("available/", "archived/")) and path not in storage_paths
        )
        return {
            "storage_limit": storage_limit,
            "known_db_paths": len(db_paths),
            "available_files": len(available_files),
            "archived_files": len(archived_files),
            "orphan_storage_files": orphan_storage_files[:50],
            "missing_storage_files": missing_storage_files[:50],
        }

    def cleanup_local_data(
        self,
        *,
        dry_run: bool = True,
        temp_photos_hours: int = 8,
        failed_uploads_days: int = 30,
        screenshots_days: int = 14,
        debug_days: int = 7,
        browser_profiles_days: int = 3,
    ) -> dict:
        return {
            "dry_run": dry_run,
            "temp_photos": self._cleanup_files(
                self._local_data_dir / "temp_photos",
                older_than=timedelta(hours=max(temp_photos_hours, 1)),
                dry_run=dry_run,
            ),
            "failed_uploads": self._cleanup_files(
                self._local_data_dir / "failed_uploads",
                older_than=timedelta(days=max(failed_uploads_days, 1)),
                dry_run=dry_run,
            ),
            "results_screenshots": self._cleanup_files(
                self._local_data_dir / "results" / "screenshots",
                older_than=timedelta(days=max(screenshots_days, 1)),
                dry_run=dry_run,
            ),
            "debug": self._cleanup_directories(
                self._local_data_dir / "debug",
                older_than=timedelta(days=max(debug_days, 1)),
                dry_run=dry_run,
            ),
            "browser_profiles": self._cleanup_directories(
                self._local_data_dir / "browser_profiles",
                older_than=timedelta(days=max(browser_profiles_days, 1)),
                dry_run=dry_run,
            ),
        }

    def archive_consumed_photos(
        self,
        *,
        dry_run: bool = True,
        older_than_days: int = 7,
        limit: int = 100,
    ) -> dict:
        consumed_records = self._photos_repository.list(status=PhotoStatus.CONSUMED, limit=max(limit * 2, limit))
        cutoff = self._utcnow() - timedelta(days=max(older_than_days, 1))
        items: list[dict] = []
        archived_count = 0
        for record in consumed_records:
            if len(items) >= limit:
                break
            if record.consumed_at is None or record.consumed_at > cutoff:
                continue
            current_path = self._normalize_storage_path(record.storage_path)
            target_name = current_path.rsplit("/", maxsplit=1)[-1]
            target_path = current_path if current_path.startswith("archived/") else f"archived/{target_name}"
            item = {
                "photo_id": record.id,
                "from_path": current_path,
                "to_path": target_path,
                "current_status": record.status,
                "consumed_at": record.consumed_at.isoformat() if record.consumed_at else None,
                "action": "archive",
            }
            if not dry_run:
                if current_path != target_path:
                    self._client_provider.move_file(
                        bucket_name=self._settings.supabase_storage_bucket,
                        from_path=current_path,
                        to_path=target_path,
                    )
                self._photos_repository.update(
                    record.id,
                    PhotoUpdate(
                        status=PhotoStatus.ARCHIVED,
                        storage_path=target_path,
                    ),
                )
                archived_count += 1
            items.append(item)
        return {
            "dry_run": dry_run,
            "older_than_days": older_than_days,
            "requested_limit": limit,
            "matched_items": len(items),
            "archived_count": archived_count,
            "items": items,
        }

    def _sample_photo_records(self, *, limit_per_status: int) -> list[PhotoRecord]:
        seen: set[str] = set()
        records: list[PhotoRecord] = []
        for status in (
            PhotoStatus.AVAILABLE,
            PhotoStatus.RESERVED,
            PhotoStatus.CONSUMED,
            PhotoStatus.ARCHIVED,
            PhotoStatus.FAILED,
        ):
            for record in self._photos_repository.list(status=status, limit=limit_per_status):
                if record.id in seen:
                    continue
                seen.add(record.id)
                records.append(record)
        return records

    def _list_storage_paths(self, folder: str, *, limit: int) -> list[str]:
        entries = self._client_provider.list_files(
            bucket_name=self._settings.supabase_storage_bucket,
            folder_path=folder,
            limit=limit,
        )
        paths: list[str] = []
        for entry in entries:
            name = str(entry.get("name") or "").strip().lstrip("/")
            if not name or name.endswith("/"):
                continue
            paths.append(f"{folder}/{name}")
        return paths

    def _cleanup_files(self, root: Path, *, older_than: timedelta, dry_run: bool) -> dict:
        if not root.exists():
            return {"removed": 0, "bytes_freed": 0, "items": []}
        cutoff = self._utcnow() - older_than
        removed = 0
        bytes_freed = 0
        items: list[dict] = []
        for path in sorted((candidate for candidate in root.rglob("*") if candidate.is_file()), key=lambda item: item.stat().st_mtime):
            if not self._is_safe_local_target(path):
                continue
            if path.name == ".gitkeep":
                continue
            modified_at = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
            if modified_at > cutoff:
                continue
            size = path.stat().st_size
            items.append(
                {
                    "path": str(path),
                    "size_bytes": size,
                    "modified_at": modified_at.isoformat(),
                }
            )
            if dry_run:
                continue
            with suppress(OSError):
                path.unlink()
                removed += 1
                bytes_freed += size
        return {
            "removed": removed,
            "bytes_freed": bytes_freed,
            "items": items,
        }

    def _cleanup_directories(self, root: Path, *, older_than: timedelta, dry_run: bool) -> dict:
        if not root.exists():
            return {"removed": 0, "bytes_freed": 0, "items": []}
        cutoff = self._utcnow() - older_than
        removed = 0
        bytes_freed = 0
        items: list[dict] = []
        directories = [candidate for candidate in root.iterdir() if candidate.is_dir()]
        directories.sort(key=lambda item: item.stat().st_mtime)
        for path in directories:
            if not self._is_safe_local_target(path):
                continue
            modified_at = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
            if modified_at > cutoff:
                continue
            size = self._measure_path_size(path)
            items.append(
                {
                    "path": str(path),
                    "size_bytes": size,
                    "modified_at": modified_at.isoformat(),
                }
            )
            if dry_run:
                continue
            with suppress(OSError):
                shutil.rmtree(path, ignore_errors=False)
                removed += 1
                bytes_freed += size
        return {
            "removed": removed,
            "bytes_freed": bytes_freed,
            "items": items,
        }

    def _summarize_path(self, path: Path) -> dict:
        if not path.exists():
            return {"exists": False, "file_count": 0, "size_bytes": 0}
        files = [candidate for candidate in path.rglob("*") if candidate.is_file()]
        if not files:
            return {"exists": True, "file_count": 0, "size_bytes": 0}
        files.sort(key=lambda item: item.stat().st_mtime)
        return {
            "exists": True,
            "file_count": len(files),
            "size_bytes": sum(item.stat().st_size for item in files),
            "oldest_file": str(files[0]),
            "newest_file": str(files[-1]),
        }

    def _serialize_photo(self, record: PhotoRecord) -> dict:
        return {
            "id": record.id,
            "status": record.status,
            "storage_path": self._normalize_storage_path(record.storage_path),
            "original_filename": record.original_filename,
            "reserved_at": record.reserved_at.isoformat() if record.reserved_at else None,
            "consumed_at": record.consumed_at.isoformat() if record.consumed_at else None,
            "created_at": record.created_at.isoformat() if record.created_at else None,
        }

    def _is_safe_local_target(self, path: Path) -> bool:
        resolved = path.resolve()
        return resolved == self._local_data_dir or self._local_data_dir in resolved.parents

    @staticmethod
    def _normalize_storage_path(storage_path: str) -> str:
        return storage_path.replace("\\", "/").lstrip("/")

    @staticmethod
    def _measure_path_size(path: Path) -> int:
        if path.is_file():
            return path.stat().st_size
        total = 0
        for child in path.rglob("*"):
            if child.is_file():
                total += child.stat().st_size
        return total

    @staticmethod
    def _utcnow() -> datetime:
        return datetime.now(timezone.utc)
