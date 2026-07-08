from __future__ import annotations

import argparse
import mimetypes
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from dotenv import load_dotenv
from supabase import create_client


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PREFIXES = ("available", "candidates")


@dataclass
class MigrationStats:
    scanned: int = 0
    copied: int = 0
    deleted_source: int = 0
    failed: int = 0
    db_updated: bool = False
    db_rows_checked: int = 0
    db_rows_repointed: int = 0
    db_rows_copied_from_source: int = 0
    db_rows_discarded_missing: int = 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Copia fotos de Supabase Storage desde photos hacia photo-pool."
    )
    parser.add_argument("--source-bucket", default="photos")
    parser.add_argument("--target-bucket", default=None)
    parser.add_argument(
        "--prefix",
        action="append",
        dest="prefixes",
        help="Prefijo a migrar. Se puede repetir. Default: available y candidates.",
    )
    parser.add_argument("--limit", type=int, default=0, help="Maximo de objetos a procesar. 0 = sin limite.")
    parser.add_argument("--apply", action="store_true", help="Ejecuta la copia. Sin esto solo muestra dry-run.")
    parser.add_argument(
        "--delete-source",
        action="store_true",
        help="Borra cada objeto del bucket origen solo despues de copiarlo correctamente.",
    )
    parser.add_argument(
        "--skip-db-update",
        action="store_true",
        help="No actualiza public.photos.storage_bucket al bucket destino.",
    )
    parser.add_argument(
        "--reconcile-db-source",
        action="store_true",
        help="Verifica filas DB marcadas con el bucket origen y las corrige/limpia una por una.",
    )
    parser.add_argument(
        "--discard-missing",
        action="store_true",
        help="Con --reconcile-db-source, marca como discarded las filas cuyo archivo no existe en ningun bucket.",
    )
    return parser.parse_args()


def main() -> int:
    load_dotenv(PROJECT_ROOT / ".env")
    args = parse_args()
    source_bucket = str(args.source_bucket or "").strip()
    target_bucket = str(args.target_bucket or os.getenv("SUPABASE_STORAGE_BUCKET") or "photo-pool").strip()
    prefixes = tuple(args.prefixes or DEFAULT_PREFIXES)

    if not source_bucket or not target_bucket:
        raise SystemExit("source-bucket y target-bucket son obligatorios.")
    if source_bucket == target_bucket:
        raise SystemExit("El bucket origen y destino son iguales; no hay nada que migrar.")

    supabase_url = os.getenv("SUPABASE_URL")
    supabase_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_KEY")
    if not supabase_url or not supabase_key:
        raise SystemExit("Define SUPABASE_URL y SUPABASE_SERVICE_ROLE_KEY o SUPABASE_KEY en .env.")

    client = create_client(supabase_url, supabase_key)
    stats = MigrationStats()
    print(f"Origen: {source_bucket}")
    print(f"Destino: {target_bucket}")
    print(f"Modo: {'APPLY' if args.apply else 'DRY-RUN'}")
    if args.delete_source and not args.apply:
        print("Nota: --delete-source no tiene efecto sin --apply.")
    source_db_count, null_db_count = count_database_bucket_rows(client, source_bucket)
    print(f"Filas DB con storage_bucket='{source_bucket}': {source_db_count}")
    print(f"Filas DB con storage_bucket null: {null_db_count}")

    for storage_path in iter_selected_objects(client, source_bucket, prefixes):
        if args.limit and stats.scanned >= args.limit:
            break
        stats.scanned += 1
        print(f"[{stats.scanned}] {storage_path}")
        if not args.apply:
            continue
        try:
            copy_object(client, source_bucket, target_bucket, storage_path)
            stats.copied += 1
            if args.delete_source:
                client.storage.from_(source_bucket).remove([storage_path])
                stats.deleted_source += 1
        except Exception as exc:  # noqa: BLE001
            stats.failed += 1
            print(f"  ERROR: {exc}")

    if args.apply and not args.skip_db_update:
        if args.reconcile_db_source:
            reconcile_database_source_rows(
                client,
                source_bucket=source_bucket,
                target_bucket=target_bucket,
                stats=stats,
                apply=True,
                delete_source=args.delete_source,
                discard_missing=args.discard_missing,
                max_rows=args.limit,
            )
        else:
            update_database_bucket(client, source_bucket, target_bucket)
        stats.db_updated = True
    elif args.reconcile_db_source:
        reconcile_database_source_rows(
            client,
            source_bucket=source_bucket,
            target_bucket=target_bucket,
            stats=stats,
            apply=False,
            delete_source=False,
            discard_missing=args.discard_missing,
            max_rows=args.limit,
        )

    print("")
    print("Resumen")
    print(f"  Objetos revisados: {stats.scanned}")
    print(f"  Objetos copiados: {stats.copied}")
    print(f"  Objetos borrados del origen: {stats.deleted_source}")
    print(f"  Errores: {stats.failed}")
    print(f"  Filas DB revisadas: {stats.db_rows_checked}")
    print(f"  Filas DB apuntadas a destino: {stats.db_rows_repointed}")
    print(f"  Filas DB copiadas desde origen: {stats.db_rows_copied_from_source}")
    print(f"  Filas DB descartadas por archivo faltante: {stats.db_rows_discarded_missing}")
    print(f"  DB actualizada: {'si' if stats.db_updated else 'no'}")
    return 1 if stats.failed else 0


def iter_selected_objects(client, bucket_name: str, prefixes: tuple[str, ...]) -> Iterator[str]:
    for prefix in prefixes:
        normalized = normalize_storage_path(prefix)
        yield from iter_storage_objects(client, bucket_name, normalized)


def iter_storage_objects(client, bucket_name: str, folder_path: str = "") -> Iterator[str]:
    offset = 0
    limit = 1000
    while True:
        entries = client.storage.from_(bucket_name).list(
            folder_path,
            {
                "limit": limit,
                "offset": offset,
                "sortBy": {"column": "name", "order": "asc"},
            },
        ) or []
        if not entries:
            break
        for entry in entries:
            name = str(entry.get("name") or "").strip()
            if not name:
                continue
            storage_path = f"{folder_path}/{name}" if folder_path else name
            if is_storage_folder(entry, name):
                yield from iter_storage_objects(client, bucket_name, storage_path)
            else:
                yield normalize_storage_path(storage_path)
        if len(entries) < limit:
            break
        offset += limit


def is_storage_folder(entry: dict, name: str) -> bool:
    if entry.get("id"):
        return False
    metadata = entry.get("metadata")
    if isinstance(metadata, dict) and metadata:
        return False
    return "." not in name


def copy_object(client, source_bucket: str, target_bucket: str, storage_path: str) -> None:
    content = client.storage.from_(source_bucket).download(storage_path)
    content_type = mimetypes.guess_type(storage_path)[0] or "application/octet-stream"
    client.storage.from_(target_bucket).upload(
        path=storage_path,
        file=content,
        file_options={
            "content-type": content_type,
            "upsert": True,
        },
    )


def update_database_bucket(client, source_bucket: str, target_bucket: str) -> None:
    table_name = os.getenv("SUPABASE_PHOTOS_TABLE") or "photos"
    (
        client.table(table_name)
        .update({"storage_bucket": target_bucket})
        .eq("storage_bucket", source_bucket)
        .is_("storage_deleted_at", "null")
        .execute()
    )
    (
        client.table(table_name)
        .update({"storage_bucket": target_bucket})
        .is_("storage_bucket", "null")
        .is_("storage_deleted_at", "null")
        .execute()
    )


def reconcile_database_source_rows(
    client,
    *,
    source_bucket: str,
    target_bucket: str,
    stats: MigrationStats,
    apply: bool,
    delete_source: bool,
    discard_missing: bool,
    max_rows: int = 0,
) -> None:
    table_name = os.getenv("SUPABASE_PHOTOS_TABLE") or "photos"
    offset = 0
    page_size = 100
    while True:
        rows = fetch_source_bucket_rows(
            client,
            table_name=table_name,
            source_bucket=source_bucket,
            offset=offset,
            limit=page_size,
            apply_mode=apply,
        )
        if not rows:
            break
        for row in rows:
            if max_rows and stats.db_rows_checked >= max_rows:
                return
            stats.db_rows_checked += 1
            photo_id = str(row.get("id") or "")
            storage_path = normalize_storage_path(str(row.get("file_path") or ""))
            if not photo_id or not storage_path:
                continue

            if object_exists(client, target_bucket, storage_path):
                if apply:
                    repoint_photo_row(client, table_name, photo_id, target_bucket, storage_path)
                stats.db_rows_repointed += 1
                continue

            if object_exists(client, source_bucket, storage_path):
                if apply:
                    copy_object(client, source_bucket, target_bucket, storage_path)
                    repoint_photo_row(client, table_name, photo_id, target_bucket, storage_path)
                    if delete_source:
                        client.storage.from_(source_bucket).remove([storage_path])
                stats.db_rows_copied_from_source += 1
                continue

            if discard_missing:
                if apply:
                    discard_missing_photo_row(client, table_name, photo_id, storage_path)
                stats.db_rows_discarded_missing += 1
        if apply:
            continue
        if len(rows) < page_size:
            break
        offset += page_size


def fetch_source_bucket_rows(
    client,
    *,
    table_name: str,
    source_bucket: str,
    offset: int,
    limit: int,
    apply_mode: bool,
) -> list[dict]:
    query = (
        client.table(table_name)
        .select("id,file_path,status,storage_bucket")
        .eq("storage_bucket", source_bucket)
        .is_("storage_deleted_at", "null")
        .order("created_at", desc=False)
    )
    if apply_mode:
        query = query.range(0, limit - 1)
    else:
        query = query.range(offset, offset + limit - 1)
    return list(query.execute().data or [])


def object_exists(client, bucket_name: str, storage_path: str) -> bool:
    try:
        client.storage.from_(bucket_name).download(storage_path)
    except Exception:
        return False
    return True


def repoint_photo_row(client, table_name: str, photo_id: str, target_bucket: str, storage_path: str) -> None:
    (
        client.table(table_name)
        .update({"storage_bucket": target_bucket, "file_path": storage_path})
        .eq("id", photo_id)
        .execute()
    )


def discard_missing_photo_row(client, table_name: str, photo_id: str, storage_path: str) -> None:
    (
        client.table(table_name)
        .update(
            {
                "status": "discarded",
                "reserved_at": None,
                "reserved_by_process_id": None,
                "storage_deleted_at": datetime.now(timezone.utc).isoformat(),
                "cleanup_reason": "missing_storage_during_bucket_unification",
                "cleanup_error": f"Storage object missing in source and target buckets: {storage_path}",
                "cleaned_by": "bucket_unification_script",
            }
        )
        .eq("id", photo_id)
        .execute()
    )


def count_database_bucket_rows(client, source_bucket: str) -> tuple[int, int]:
    table_name = os.getenv("SUPABASE_PHOTOS_TABLE") or "photos"
    source_response = (
        client.table(table_name)
        .select("id", count="exact")
        .eq("storage_bucket", source_bucket)
        .is_("storage_deleted_at", "null")
        .limit(1)
        .execute()
    )
    null_response = (
        client.table(table_name)
        .select("id", count="exact")
        .is_("storage_bucket", "null")
        .is_("storage_deleted_at", "null")
        .limit(1)
        .execute()
    )
    return int(getattr(source_response, "count", 0) or 0), int(getattr(null_response, "count", 0) or 0)


def normalize_storage_path(value: str) -> str:
    return str(value or "").strip().replace("\\", "/").strip("/")


if __name__ == "__main__":
    raise SystemExit(main())
