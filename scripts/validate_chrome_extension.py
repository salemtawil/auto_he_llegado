from __future__ import annotations

import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
EXTENSION_DIR = (PROJECT_ROOT / "browser_extension").resolve()

ALLOWED_PERMISSIONS = {
    "activeTab",
    "alarms",
    "background",
    "bookmarks",
    "browsingData",
    "clipboardRead",
    "clipboardWrite",
    "contentSettings",
    "contextMenus",
    "cookies",
    "debugger",
    "declarativeContent",
    "declarativeNetRequest",
    "declarativeNetRequestFeedback",
    "declarativeNetRequestWithHostAccess",
    "downloads",
    "downloads.open",
    "downloads.ui",
    "enterprise.deviceAttributes",
    "enterprise.hardwarePlatform",
    "enterprise.networkingAttributes",
    "enterprise.platformKeys",
    "experimental",
    "favicon",
    "fileBrowserHandler",
    "fileSystemProvider",
    "fontSettings",
    "gcm",
    "geolocation",
    "history",
    "identity",
    "idle",
    "management",
    "nativeMessaging",
    "notifications",
    "offscreen",
    "pageCapture",
    "power",
    "printerProvider",
    "printing",
    "privacy",
    "proxy",
    "scripting",
    "search",
    "sessions",
    "sidePanel",
    "storage",
    "system.cpu",
    "system.display",
    "system.memory",
    "system.storage",
    "tabCapture",
    "tabGroups",
    "tabs",
    "topSites",
    "tts",
    "ttsEngine",
    "unlimitedStorage",
    "vpnProvider",
    "wallpaper",
    "webNavigation",
    "webRequest",
    "webRequestAuthProvider",
}


def _print_line(label: str, value) -> None:
    print(f"{label}: {value}")


def _load_manifest(manifest_path: Path) -> tuple[dict | None, list[str]]:
    errors: list[str] = []
    if not manifest_path.exists():
        return None, [f"manifest.json no existe en {manifest_path}"]
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return None, [f"manifest.json no es JSON válido: {exc}"]
    if not isinstance(payload, dict):
        return None, ["manifest.json no contiene un objeto JSON."]
    return payload, errors


def _validate_permissions(manifest: dict) -> list[str]:
    errors: list[str] = []
    permissions = manifest.get("permissions", [])
    if permissions is None:
        permissions = []
    if not isinstance(permissions, list):
        return ["permissions debe ser una lista."]
    for item in permissions:
        if not isinstance(item, str) or not item.strip():
            errors.append(f"permiso inválido: {item!r}")
            continue
        if item not in ALLOWED_PERMISSIONS:
            errors.append(f"permiso no reconocido para Chrome: {item}")
    return errors


def _validate_host_permissions(manifest: dict) -> list[str]:
    errors: list[str] = []
    host_permissions = manifest.get("host_permissions", [])
    if host_permissions is None:
        host_permissions = []
    if not isinstance(host_permissions, list):
        return ["host_permissions debe ser una lista."]
    for item in host_permissions:
        if not isinstance(item, str) or not item.strip():
            errors.append(f"host_permission inválido: {item!r}")
    return errors


def _validate_background_service_worker(manifest: dict, extension_dir: Path) -> tuple[str | None, bool, list[str]]:
    errors: list[str] = []
    background = manifest.get("background")
    if not isinstance(background, dict):
        return None, False, ["background debe existir y ser un objeto."]
    service_worker = background.get("service_worker")
    if not isinstance(service_worker, str) or not service_worker.strip():
        return None, False, ["background.service_worker debe existir y ser un string."]
    worker_path = extension_dir / service_worker
    if not worker_path.exists():
        errors.append(f"background.service_worker no existe físicamente: {worker_path}")
    return service_worker, worker_path.exists(), errors


def _validate_content_scripts(manifest: dict, extension_dir: Path) -> tuple[list[dict], list[str]]:
    errors: list[str] = []
    rows: list[dict] = []
    content_scripts = manifest.get("content_scripts", [])
    if not isinstance(content_scripts, list):
        return [], ["content_scripts debe ser una lista."]
    for index, entry in enumerate(content_scripts):
        if not isinstance(entry, dict):
            errors.append(f"content_scripts[{index}] debe ser un objeto.")
            continue
        js_entries = entry.get("js", [])
        if not isinstance(js_entries, list):
            errors.append(f"content_scripts[{index}].js debe ser una lista.")
            continue
        for relative_path in js_entries:
            exists = isinstance(relative_path, str) and (extension_dir / relative_path).exists()
            rows.append(
                {
                    "index": index,
                    "path": relative_path,
                    "exists": exists,
                }
            )
            if not isinstance(relative_path, str) or not relative_path.strip():
                errors.append(f"content_scripts[{index}].js contiene una ruta inválida: {relative_path!r}")
            elif not exists:
                errors.append(
                    f"content_scripts[{index}].js no existe físicamente: {extension_dir / relative_path}"
                )
    return rows, errors


def main() -> None:
    manifest_path = EXTENSION_DIR / "manifest.json"
    manifest, errors = _load_manifest(manifest_path)

    _print_line("extension_dir", EXTENSION_DIR)
    _print_line("manifest exists", manifest_path.exists())

    if manifest is None:
        for item in errors:
            print(f"ERROR: {item}")
        _print_line("result", "INVALID")
        raise SystemExit(1)

    manifest_name = manifest.get("name")
    manifest_version = manifest.get("version")
    manifest_version_number = manifest.get("manifest_version")
    _print_line("manifest name", manifest_name)
    _print_line("manifest version", manifest_version)
    _print_line("manifest_version", manifest_version_number)

    if manifest_version_number != 3:
        errors.append(f"manifest_version debe ser 3 y llegó {manifest_version_number!r}")
    if not isinstance(manifest_name, str) or not manifest_name.strip():
        errors.append("name debe existir y ser un string no vacío.")
    if not isinstance(manifest_version, str) or not manifest_version.strip():
        errors.append("version debe existir y ser un string no vacío.")

    service_worker_rel, service_worker_exists, worker_errors = _validate_background_service_worker(manifest, EXTENSION_DIR)
    errors.extend(worker_errors)
    _print_line("service_worker path", service_worker_rel)
    _print_line("service_worker path exists", service_worker_exists)

    content_script_rows, content_script_errors = _validate_content_scripts(manifest, EXTENSION_DIR)
    errors.extend(content_script_errors)
    for row in content_script_rows:
        _print_line(
            f"content_script[{row['index']}] {row['path']}",
            row["exists"],
        )

    permission_errors = _validate_permissions(manifest)
    host_permission_errors = _validate_host_permissions(manifest)
    errors.extend(permission_errors)
    errors.extend(host_permission_errors)
    _print_line("permissions", manifest.get("permissions", []))
    _print_line("host_permissions", manifest.get("host_permissions", []))

    if errors:
        for item in errors:
            print(f"ERROR: {item}")
        _print_line("result", "INVALID")
        raise SystemExit(1)

    _print_line("result", "VALID")


if __name__ == "__main__":
    main()
