from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from services.maintenance_service import MaintenanceService


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Auditoria y mantenimiento conservador del sistema.")
    parser.add_argument("--apply", action="store_true", help="Aplica los cambios. Sin esta bandera todo corre en dry-run.")
    parser.add_argument("--skip-storage-audit", action="store_true", help="Omite la auditoria de Supabase Storage.")
    parser.add_argument("--archive-consumed", action="store_true", help="Mueve a archived/ las fotos consumed antiguas y actualiza su estado en DB.")
    parser.add_argument("--stale-reserved-hours", type=int, default=12, help="Umbral para reportar fotos reserved como estancadas.")
    parser.add_argument("--archive-after-days", type=int, default=7, help="Antigüedad mínima para archivar fotos consumed.")
    parser.add_argument("--storage-limit", type=int, default=1000, help="Límite de archivos a revisar por carpeta remota.")
    parser.add_argument("--temp-hours", type=int, default=8, help="Antigüedad para limpiar temp_photos.")
    parser.add_argument("--failed-days", type=int, default=30, help="Antigüedad para limpiar failed_uploads.")
    parser.add_argument("--screenshots-days", type=int, default=14, help="Antigüedad para limpiar results/screenshots.")
    parser.add_argument("--debug-days", type=int, default=7, help="Antigüedad para limpiar local_data/debug.")
    parser.add_argument("--browser-profiles-days", type=int, default=3, help="Antigüedad para limpiar browser_profiles.")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    service = MaintenanceService()
    dry_run = not args.apply
    payload = {
        "audit": service.audit(
            stale_reserved_hours=args.stale_reserved_hours,
            archive_after_days=args.archive_after_days,
            include_storage=not args.skip_storage_audit,
            storage_limit=args.storage_limit,
        ),
        "local_cleanup": service.cleanup_local_data(
            dry_run=dry_run,
            temp_photos_hours=args.temp_hours,
            failed_uploads_days=args.failed_days,
            screenshots_days=args.screenshots_days,
            debug_days=args.debug_days,
            browser_profiles_days=args.browser_profiles_days,
        ),
    }
    if args.archive_consumed:
        payload["archive_consumed"] = service.archive_consumed_photos(
            dry_run=dry_run,
            older_than_days=args.archive_after_days,
            limit=args.storage_limit,
        )
    print(json.dumps(payload, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
