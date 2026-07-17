from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from time import sleep
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from dotenv import load_dotenv
from supabase import create_client


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = PROJECT_ROOT / ".env"
DEFAULT_BUCKETS = ("photo-pool", "photos")
DEFAULT_PREFIXES = ("available", "candidates")
MAX_PAGE_SIZE = 1000
MAX_DELETE_SIZE = 1000
CONFIRMATION = "RESET_PHOTO_POOL"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Destructive reset of photo pool Storage and active DB rows."
    )
    parser.add_argument("--bucket", action="append", dest="buckets", help="Bucket to reset. Can be repeated.")
    parser.add_argument("--prefix", action="append", dest="prefixes", help="Storage prefix to delete. Can be repeated.")
    parser.add_argument("--apply", action="store_true", help="Actually delete Storage objects and update DB.")
    parser.add_argument("--confirm", default="", help=f"Required with --apply: {CONFIRMATION}")
    parser.add_argument("--sleep", type=float, default=0.2, help="Seconds between delete batches.")
    parser.add_argument("--skip-db", action="store_true", help="Only delete Storage; do not mark DB rows.")
    return parser.parse_args()


def _require_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Falta configurar {name}.")
    return value


def _request_json(
    *,
    method: str,
    url: str,
    service_role_key: str,
    payload: dict | None = None,
) -> list[dict] | dict:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = Request(
        url,
        data=data,
        method=method,
        headers={
            "apikey": service_role_key,
            "Authorization": f"Bearer {service_role_key}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urlopen(request, timeout=60) as response:
            raw = response.read()
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code}: {detail}") from exc
    except URLError as exc:
        raise RuntimeError(str(exc)) from exc
    if not raw:
        return {}
    return json.loads(raw.decode("utf-8"))


def _list_storage_folder(
    *,
    supabase_url: str,
    service_role_key: str,
    bucket_name: str,
    folder_path: str,
) -> list[dict]:
    url = f"{supabase_url.rstrip('/')}/storage/v1/object/list/{quote(bucket_name, safe='')}"
    entries: list[dict] = []
    offset = 0
    while True:
        payload = {
            "prefix": folder_path,
            "limit": MAX_PAGE_SIZE,
            "offset": offset,
            "sortBy": {"column": "name", "order": "asc"},
        }
        page = _request_json(
            method="POST",
            url=url,
            service_role_key=service_role_key,
            payload=payload,
        )
        if not isinstance(page, list) or not page:
            break
        entries.extend(page)
        if len(page) < MAX_PAGE_SIZE:
            break
        offset += MAX_PAGE_SIZE
    return entries


def _is_storage_folder(entry: dict, name: str) -> bool:
    if entry.get("id"):
        return False
    metadata = entry.get("metadata")
    if isinstance(metadata, dict) and metadata:
        return False
    return "." not in name


def _iter_storage_objects(
    *,
    supabase_url: str,
    service_role_key: str,
    bucket_name: str,
    folder_path: str,
):
    for entry in _list_storage_folder(
        supabase_url=supabase_url,
        service_role_key=service_role_key,
        bucket_name=bucket_name,
        folder_path=folder_path,
    ):
        name = str(entry.get("name") or "").strip()
        if not name:
            continue
        storage_path = f"{folder_path}/{name}" if folder_path else name
        if _is_storage_folder(entry, name):
            yield from _iter_storage_objects(
                supabase_url=supabase_url,
                service_role_key=service_role_key,
                bucket_name=bucket_name,
                folder_path=storage_path,
            )
        else:
            yield storage_path.replace("\\", "/").lstrip("/")


def _delete_storage_paths(
    *,
    supabase_url: str,
    service_role_key: str,
    bucket_name: str,
    paths: list[str],
) -> None:
    url = f"{supabase_url.rstrip('/')}/storage/v1/object/{quote(bucket_name, safe='')}"
    _request_json(
        method="DELETE",
        url=url,
        service_role_key=service_role_key,
        payload={"prefixes": paths},
    )


def _chunked(values: list[str], size: int):
    for index in range(0, len(values), size):
        yield values[index : index + size]


def _mark_database_reset(*, supabase_url: str, service_role_key: str) -> None:
    client = create_client(supabase_url, service_role_key)
    now = datetime.now(timezone.utc).isoformat()
    photos_table = os.getenv("SUPABASE_PHOTOS_TABLE") or "photos"
    candidates_table = os.getenv("SUPABASE_PHOTO_CANDIDATES_TABLE") or "photo_candidates"

    consumed_payload = {
        "storage_deleted_at": now,
        "cleanup_reason": "reset_pool_cleanup",
        "cleanup_error": None,
        "cleaned_by": "admin_reset",
    }
    (
        client.table(photos_table)
        .update(consumed_payload)
        .eq("status", "consumed")
        .like("file_path", "available/%")
        .is_("storage_deleted_at", "null")
        .execute()
    )

    discarded_payload = {
        "status": "discarded",
        "reserved_at": None,
        "reserved_by_process_id": None,
        "storage_deleted_at": now,
        "cleanup_reason": "reset_pool_cleanup",
        "cleanup_error": None,
        "cleaned_by": "admin_reset",
    }
    (
        client.table(photos_table)
        .update(discarded_payload)
        .neq("status", "consumed")
        .like("file_path", "available/%")
        .is_("storage_deleted_at", "null")
        .execute()
    )

    candidate_payload = {
        "status": "deleted",
        "reviewed_at": now,
        "rejection_reason": "reset_pool_cleanup",
        "updated_at": now,
    }
    (
        client.table(candidates_table)
        .update(candidate_payload)
        .eq("status", "pending")
        .execute()
    )


def main() -> int:
    load_dotenv(ENV_FILE, override=False)
    args = _parse_args()
    buckets = tuple(args.buckets or DEFAULT_BUCKETS)
    prefixes = tuple(args.prefixes or DEFAULT_PREFIXES)

    if args.apply and args.confirm != CONFIRMATION:
        print(f"ERROR: Para aplicar debes usar --confirm {CONFIRMATION}", file=sys.stderr)
        return 2

    try:
        supabase_url = _require_env("SUPABASE_URL")
        service_role_key = _require_env("SUPABASE_SERVICE_ROLE_KEY")
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    paths_by_bucket: dict[str, list[str]] = {}
    print("Escaneando Storage...")
    for bucket_name in buckets:
        bucket_paths: list[str] = []
        for prefix in prefixes:
            paths = list(
                _iter_storage_objects(
                    supabase_url=supabase_url,
                    service_role_key=service_role_key,
                    bucket_name=bucket_name,
                    folder_path=prefix.strip("/"),
                )
            )
            print(f"  - {bucket_name}/{prefix}: {len(paths)} archivos")
            bucket_paths.extend(paths)
        paths_by_bucket[bucket_name] = sorted(set(bucket_paths))

    total_paths = sum(len(paths) for paths in paths_by_bucket.values())
    mode = "APPLY" if args.apply else "DRY-RUN"
    print(f"Modo: {mode}")
    print(f"Total a borrar de Storage: {total_paths}")
    if not args.apply:
        print(f"No se borro nada. Para aplicar: --apply --confirm {CONFIRMATION}")
        return 0

    deleted_count = 0
    for bucket_name, paths in paths_by_bucket.items():
        for chunk in _chunked(paths, MAX_DELETE_SIZE):
            _delete_storage_paths(
                supabase_url=supabase_url,
                service_role_key=service_role_key,
                bucket_name=bucket_name,
                paths=chunk,
            )
            deleted_count += len(chunk)
            print(f"Borrados de Storage: {deleted_count}/{total_paths}")
            sleep(max(float(args.sleep), 0.0))

    if args.skip_db:
        print("DB no actualizada por --skip-db.")
        return 0

    print("Marcando DB como descartada/limpia...")
    _mark_database_reset(supabase_url=supabase_url, service_role_key=service_role_key)
    print("Reset del pool completado.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
