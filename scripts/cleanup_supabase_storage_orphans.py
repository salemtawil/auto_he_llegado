from __future__ import annotations

import argparse
import os
import sys
from collections import defaultdict
from pathlib import Path
from time import sleep

from dotenv import load_dotenv
from supabase import create_client


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = PROJECT_ROOT / ".env"
MAX_BATCH_SIZE = 1000


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Emergency cleanup for Storage files under available/ that no longer "
            "have an active row in public.photos."
        )
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=1000,
        help="Objects to request per batch. Supabase Storage remove supports up to 1000.",
    )
    parser.add_argument(
        "--max-batches",
        type=int,
        default=25,
        help="Safety limit for how many batches to process in one run.",
    )
    parser.add_argument(
        "--sleep",
        type=float,
        default=0.2,
        help="Seconds to wait between batches.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List the first batch without deleting anything.",
    )
    return parser.parse_args()


def _require_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Falta configurar {name}.")
    return value


def _remove_bucket_paths(client, bucket_name: str, paths: list[str]) -> int:
    if not paths:
        return 0
    client.storage.from_(bucket_name).remove(paths)
    return len(paths)


def main() -> int:
    load_dotenv(ENV_FILE, override=False)
    args = _parse_args()
    batch_size = max(1, min(int(args.batch_size), MAX_BATCH_SIZE))
    max_batches = max(1, int(args.max_batches))

    try:
        supabase_url = _require_env("SUPABASE_URL")
        service_role_key = _require_env("SUPABASE_SERVICE_ROLE_KEY")
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        print(
            "Busca la service_role key en Supabase > Project Settings > API "
            "y ejecuta este script desde una terminal con esa variable configurada.",
            file=sys.stderr,
        )
        return 2

    client = create_client(supabase_url, service_role_key)
    total_deleted = 0
    total_bytes = 0

    for batch_index in range(1, max_batches + 1):
        try:
            response = client.rpc(
                "available_storage_orphan_paths",
                {"p_limit": batch_size},
            ).execute()
        except Exception as exc:
            print(
                "ERROR: Supabase bloqueo la consulta RPC para listar huerfanas.",
                file=sys.stderr,
            )
            print(f"Detalle: {exc}", file=sys.stderr)
            print(
                "Si aparece exceed_storage_size_quota/402, exporta las rutas desde "
                "SQL Editor y usa scripts/cleanup_supabase_storage_paths_csv.py. "
                "Si Storage API tambien queda bloqueado, debes quitar temporalmente "
                "el spend cap o subir el plan para restaurar el servicio.",
                file=sys.stderr,
            )
            return 1
        rows = list(getattr(response, "data", []) or [])
        if not rows:
            print("No quedan huerfanas disponibles para limpiar.")
            break

        paths_by_bucket: dict[str, list[str]] = defaultdict(list)
        batch_bytes = 0
        for row in rows:
            bucket_name = str(row.get("bucket_name") or "").strip()
            storage_path = str(row.get("storage_path") or "").strip().replace("\\", "/").lstrip("/")
            if not bucket_name or not storage_path:
                continue
            paths_by_bucket[bucket_name].append(storage_path)
            try:
                batch_bytes += int(row.get("total_bytes") or 0)
            except (TypeError, ValueError):
                pass

        found_count = sum(len(paths) for paths in paths_by_bucket.values())
        print(
            f"Lote {batch_index}: {found_count} huerfanas encontradas "
            f"({batch_bytes / 1024 / 1024:.1f} MB)."
        )
        for bucket_name, paths in sorted(paths_by_bucket.items()):
            print(f"  - {bucket_name}: {len(paths)} archivos")

        if args.dry_run:
            print("Dry-run activo: no se borro nada.")
            break

        batch_deleted = 0
        for bucket_name, paths in sorted(paths_by_bucket.items()):
            batch_deleted += _remove_bucket_paths(client, bucket_name, paths)

        total_deleted += batch_deleted
        total_bytes += batch_bytes
        print(
            f"  Borradas en lote: {batch_deleted}. "
            f"Total borradas: {total_deleted}. "
            f"Total liberado estimado: {total_bytes / 1024 / 1024:.1f} MB."
        )

        if batch_deleted <= 0:
            print("No hubo avance en este lote; deteniendo por seguridad.")
            break
        sleep(max(float(args.sleep), 0.0))
    else:
        print(
            f"Se alcanzo --max-batches={max_batches}. "
            "Puedes ejecutar el script de nuevo si aun quedan huerfanas."
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
