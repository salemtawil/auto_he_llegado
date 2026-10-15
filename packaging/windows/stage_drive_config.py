"""Stage private Google Drive configuration for the internal Windows installer.

Only the staged .env is rewritten. The developer's .env and OAuth token are
never changed or copied into the installer.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import shutil


class DriveConfigError(RuntimeError):
    pass


def _env_values(lines: list[str]) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def _replace_env_values(lines: list[str], replacements: dict[str, str]) -> str:
    rendered: list[str] = []
    handled: set[str] = set()
    for line in lines:
        if "=" not in line or line.lstrip().startswith("#"):
            rendered.append(line)
            continue
        key = line.split("=", 1)[0].strip()
        if key in replacements:
            rendered.append(f"{key}={replacements[key]}")
            handled.add(key)
        else:
            rendered.append(line)
    for key, value in replacements.items():
        if key not in handled:
            rendered.append(f"{key}={value}")
    return "\n".join(rendered) + "\n"


def stage_drive_config(
    source_env: Path,
    project_root: Path,
    stage_root: Path | None = None,
) -> Path:
    """Validate Drive settings and optionally copy them into an isolated build."""
    if not source_env.is_file():
        raise DriveConfigError("Falta el .env operativo del proyecto.")

    lines = source_env.read_text(encoding="utf-8-sig").splitlines()
    values = _env_values(lines)
    mode = (values.get("GOOGLE_DRIVE_AUTH_MODE") or "oauth").lower()
    if mode not in {"oauth", "service_account"}:
        raise DriveConfigError("GOOGLE_DRIVE_AUTH_MODE debe ser oauth o service_account.")
    if not values.get("GOOGLE_DRIVE_FOLDER_ID", "").strip():
        raise DriveConfigError("Falta GOOGLE_DRIVE_FOLDER_ID en .env.")

    credential_key = (
        "GOOGLE_DRIVE_OAUTH_CLIENT_FILE"
        if mode == "oauth"
        else "GOOGLE_DRIVE_SERVICE_ACCOUNT_FILE"
    )
    configured = values.get(credential_key, "").strip()
    if not configured:
        raise DriveConfigError(f"Falta {credential_key} en .env.")
    credential_source = Path(configured).expanduser()
    if not credential_source.is_absolute():
        credential_source = project_root / credential_source
    if not credential_source.is_file():
        raise DriveConfigError(f"No existe el archivo indicado por {credential_key}.")

    if stage_root is None:
        return credential_source
    if stage_root.resolve() == project_root.resolve():
        raise DriveConfigError("La salida no puede ser la raiz del proyecto.")
    if not stage_root.is_dir():
        raise DriveConfigError("La carpeta aislada del build no existe.")

    credential_name = (
        "google_drive_oauth_client.json"
        if mode == "oauth"
        else "google_drive_service_account.json"
    )
    credential_relative = Path("config") / credential_name
    credential_target = stage_root / credential_relative
    credential_target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(credential_source, credential_target)

    replacements = {credential_key: credential_relative.as_posix()}
    if mode == "oauth":
        # Each installation authorizes separately; never ship the builder's token.
        replacements["GOOGLE_DRIVE_OAUTH_TOKEN_FILE"] = (
            "local_data/google_drive_token.json"
        )
    (stage_root / ".env").write_text(
        _replace_env_values(lines, replacements), encoding="utf-8"
    )
    return credential_target


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-env", type=Path, required=True)
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--stage-root", type=Path)
    args = parser.parse_args()
    try:
        stage_drive_config(args.source_env, args.project_root, args.stage_root)
    except DriveConfigError as exc:
        parser.exit(1, f"{exc}\n")


if __name__ == "__main__":
    main()
