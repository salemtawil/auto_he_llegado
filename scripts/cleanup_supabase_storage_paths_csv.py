from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from collections import defaultdict
from pathlib import Path
from time import sleep
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = PROJECT_ROOT / ".env"
MAX_REMOVE_SIZE = 1000


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Delete Supabase Storage paths listed in a CSV exported from SQL Editor."
    )
    parser.add_argument("csv_path", help="CSV with bucket_name and storage_path columns.")
    parser.add_argument("--dry-run", action="store_true", help="Preview without deleting.")
    parser.add_argument("--sleep", type=float, default=0.2, help="Seconds to wait between remove calls.")
    return parser.parse_args()


def _require_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Falta configurar {name}.")
    return value


def _chunked(values: list[str], size: int):
    for index in range(0, len(values), size):
        yield values[index : index + size]


def _delete_storage_paths(
    *,
    supabase_url: str,
    service_role_key: str,
    bucket_name: str,
    paths: list[str],
) -> None:
    endpoint = f"{supabase_url.rstrip('/')}/storage/v1/object/{quote(bucket_name, safe='')}"
    payload = json.dumps({"prefixes": paths}).encode("utf-8")
    request = Request(
        endpoint,
        data=payload,
        method="DELETE",
        headers={
            "apikey": service_role_key,
            "Authorization": f"Bearer {service_role_key}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urlopen(request, timeout=60) as response:
            response.read()
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code}: {detail}") from exc
    except URLError as exc:
        raise RuntimeError(str(exc)) from exc


def _read_paths(csv_path: Path) -> dict[str, list[str]]:
    paths_by_bucket: dict[str, list[str]] = defaultdict(list)
    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            raise RuntimeError("El CSV no tiene encabezados.")
        normalized_fields = {field.strip().lower(): field for field in reader.fieldnames if field}
        bucket_field = normalized_fields.get("bucket_name") or normalized_fields.get("bucket_id")
        path_field = normalized_fields.get("storage_path") or normalized_fields.get("name") or normalized_fields.get("file_path")
        if not bucket_field or not path_field:
            raise RuntimeError("El CSV debe tener columnas bucket_name y storage_path.")
        for row in reader:
            bucket_name = str(row.get(bucket_field) or "").strip()
            storage_path = str(row.get(path_field) or "").strip().replace("\\", "/").lstrip("/")
            if bucket_name and storage_path:
                paths_by_bucket[bucket_name].append(storage_path)
    return paths_by_bucket


def main() -> int:
    load_dotenv(ENV_FILE, override=False)
    args = _parse_args()
    csv_path = Path(args.csv_path).expanduser()
    if not csv_path.exists():
        print(f"ERROR: No existe el CSV: {csv_path}", file=sys.stderr)
        return 2
    if csv_path.is_dir():
        print(f"ERROR: La ruta apunta a una carpeta, no a un CSV: {csv_path}", file=sys.stderr)
        print(
            "Exporta el resultado del SQL como CSV y pasa la ruta completa del archivo. "
            "Ejemplo: C:\\Users\\salem\\Downloads\\orphan_paths.csv",
            file=sys.stderr,
        )
        return 2

    try:
        paths_by_bucket = _read_paths(csv_path)
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    total_paths = sum(len(paths) for paths in paths_by_bucket.values())
    print(f"Rutas cargadas: {total_paths}")
    for bucket_name, paths in sorted(paths_by_bucket.items()):
        print(f"  - {bucket_name}: {len(paths)}")
    if total_paths <= 0:
        return 0
    if args.dry_run:
        print("Dry-run activo: no se borro nada.")
        return 0

    try:
        supabase_url = _require_env("SUPABASE_URL")
        service_role_key = _require_env("SUPABASE_SERVICE_ROLE_KEY")
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    total_deleted = 0
    for bucket_name, paths in sorted(paths_by_bucket.items()):
        for chunk in _chunked(paths, MAX_REMOVE_SIZE):
            try:
                _delete_storage_paths(
                    supabase_url=supabase_url,
                    service_role_key=service_role_key,
                    bucket_name=bucket_name,
                    paths=chunk,
                )
            except Exception as exc:
                print(
                    "ERROR: Supabase rechazo la eliminacion por Storage API. "
                    f"Bucket={bucket_name}, lote={len(chunk)}. Detalle: {exc}",
                    file=sys.stderr,
                )
                print(
                    "Si el detalle menciona exceed_storage_size_quota/402, debes quitar "
                    "temporalmente el spend cap o subir el plan, borrar, y luego volver a ajustar.",
                    file=sys.stderr,
                )
                return 1
            total_deleted += len(chunk)
            print(f"Borradas: {total_deleted}/{total_paths}")
            sleep(max(float(args.sleep), 0.0))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
