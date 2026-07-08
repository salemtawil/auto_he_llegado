from __future__ import annotations

from collections import Counter
from threading import RLock

from config.settings import Settings, get_settings


_lock = RLock()
_counts_by_process: dict[str, Counter[str]] = {}


def reset_photo_source_counts(process_id: str | None) -> None:
    if not process_id:
        return
    with _lock:
        _counts_by_process.pop(process_id, None)


def record_photo_source(process_id: str | None, bucket_name: str, settings: Settings | None = None) -> None:
    if not process_id or not bucket_name:
        return
    label = _bucket_label(bucket_name, settings or get_settings())
    with _lock:
        _counts_by_process.setdefault(process_id, Counter())[label] += 1


def get_photo_source_summary(process_id: str | None) -> str:
    if not process_id:
        return ""
    with _lock:
        counts = Counter(_counts_by_process.get(process_id) or {})
    if not counts:
        return ""
    ordered_labels = ["photo-pool", "pool viejo", "pool nuevo"]
    parts = [f"{label}: {counts[label]}" for label in ordered_labels if counts.get(label)]
    parts.extend(
        f"{label}: {count}"
        for label, count in sorted(counts.items())
        if label not in ordered_labels
    )
    return " | ".join(parts)


def _bucket_label(bucket_name: str, settings: Settings) -> str:
    normalized = bucket_name.strip()
    if normalized == settings.supabase_storage_bucket:
        if not settings.supabase_legacy_storage_buckets:
            return normalized or "bucket activo"
        return "pool nuevo"
    if normalized in settings.supabase_legacy_storage_buckets:
        return "pool viejo"
    return normalized or "bucket desconocido"
