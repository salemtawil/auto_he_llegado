from __future__ import annotations

import hashlib
import json
import platform
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable
from urllib.request import Request, urlopen


GITHUB_API_BASE = "https://api.github.com/repos"
USER_AGENT = "AutoHeLlegado-Updater"
PLACEHOLDER_SHA_VALUES = {"", "REEMPLAZAR_CON_SHA256_REAL", "sha256-placeholder"}


class ReleaseUpdateError(RuntimeError):
    pass


@dataclass(slots=True)
class UpdateConfig:
    latest_url: str | None = None
    owner: str | None = None
    repo: str | None = None
    channel: str = "stable"


@dataclass(slots=True)
class ReleaseAsset:
    revision: str
    url: str
    sha256: str
    platform_key: str
    file_name: str
    notes: list[str] = field(default_factory=list)


@dataclass(slots=True)
class DownloadedUpdate:
    asset: ReleaseAsset
    path: Path
    sha256: str


def load_update_config(config_path: Path) -> UpdateConfig:
    if not config_path.is_file():
        raise ReleaseUpdateError(f"No se encontro {config_path}.")
    try:
        payload = json.loads(config_path.read_text(encoding="utf-8-sig"))
    except Exception as exc:  # noqa: BLE001
        raise ReleaseUpdateError(f"No se pudo leer update_config.json: {exc}") from exc
    if not isinstance(payload, dict):
        raise ReleaseUpdateError("update_config.json debe ser un objeto JSON.")
    return UpdateConfig(
        latest_url=_clean_optional_string(payload.get("latest_url")),
        owner=_clean_optional_string(payload.get("owner")),
        repo=_clean_optional_string(payload.get("repo")),
        channel=str(payload.get("channel") or "stable").strip() or "stable",
    )


def fetch_json(
    url: str,
    *,
    urlopen_func: Callable = urlopen,
    timeout: int = 60,
) -> dict:
    request = Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": USER_AGENT,
        },
    )
    try:
        with urlopen_func(request, timeout=timeout) as response:
            raw_payload = response.read()
    except Exception as exc:  # noqa: BLE001
        raise ReleaseUpdateError(f"No se pudo consultar GitHub: {exc}") from exc
    try:
        payload = json.loads(raw_payload.decode("utf-8-sig"))
    except Exception as exc:  # noqa: BLE001
        raise ReleaseUpdateError(f"GitHub devolvio un JSON invalido: {exc}") from exc
    if not isinstance(payload, dict):
        raise ReleaseUpdateError("La respuesta de GitHub no tiene el formato esperado.")
    return payload


def load_latest_manifest(
    config: UpdateConfig,
    *,
    urlopen_func: Callable = urlopen,
) -> dict:
    if config.latest_url:
        return fetch_json(config.latest_url, urlopen_func=urlopen_func)
    if config.owner and config.repo:
        release_url = f"{GITHUB_API_BASE}/{config.owner}/{config.repo}/releases/latest"
        return normalize_github_release(fetch_json(release_url, urlopen_func=urlopen_func))
    raise ReleaseUpdateError("Configura latest_url o owner/repo en updater/update_config.json.")


def normalize_github_release(payload: dict) -> dict:
    revision = str(payload.get("tag_name") or payload.get("name") or "").strip()
    notes_text = str(payload.get("body") or "").strip()
    notes = [line.strip("- ").strip() for line in notes_text.splitlines() if line.strip()]
    assets: list[dict] = []
    for raw_asset in payload.get("assets") or []:
        if not isinstance(raw_asset, dict):
            continue
        name = str(raw_asset.get("name") or "").strip()
        url = str(raw_asset.get("browser_download_url") or "").strip()
        digest = str(raw_asset.get("digest") or "").strip()
        sha256 = digest.split("sha256:", 1)[1] if digest.startswith("sha256:") else ""
        if name and url:
            assets.append(
                {
                    "name": name,
                    "url": url,
                    "sha256": sha256,
                }
            )
    return {
        "revision": revision,
        "notes": notes,
        "assets": assets,
    }


def select_release_asset(
    manifest: dict,
    *,
    sys_platform: str | None = None,
    machine: str | None = None,
) -> ReleaseAsset:
    revision = str(manifest.get("revision") or manifest.get("version") or "").strip()
    if not revision:
        raise ReleaseUpdateError("El manifiesto no indica revision/version.")
    notes = [str(item) for item in manifest.get("notes") or []]
    platform_candidates = detect_platform_candidates(sys_platform=sys_platform, machine=machine)
    raw_assets = manifest.get("assets")

    if isinstance(raw_assets, dict):
        for platform_key in platform_candidates:
            raw_asset = raw_assets.get(platform_key)
            if isinstance(raw_asset, dict):
                return _asset_from_payload(raw_asset, revision=revision, platform_key=platform_key, notes=notes)

    if isinstance(raw_assets, list):
        named_assets = [item for item in raw_assets if isinstance(item, dict)]
        for platform_key in platform_candidates:
            for raw_asset in named_assets:
                explicit_platform = _clean_optional_string(raw_asset.get("platform"))
                if explicit_platform == platform_key:
                    return _asset_from_payload(raw_asset, revision=revision, platform_key=platform_key, notes=notes)
        for platform_key in platform_candidates:
            for raw_asset in named_assets:
                name = str(raw_asset.get("name") or raw_asset.get("file_name") or "").lower()
                if _asset_name_matches_platform(name, platform_key):
                    return _asset_from_payload(raw_asset, revision=revision, platform_key=platform_key, notes=notes)

    if manifest.get("url"):
        return _asset_from_payload(manifest, revision=revision, platform_key=platform_candidates[0], notes=notes)

    raise ReleaseUpdateError(f"No hay un ZIP de actualizacion compatible con {platform_candidates[0]}.")


def detect_platform_candidates(*, sys_platform: str | None = None, machine: str | None = None) -> list[str]:
    current_platform = sys_platform or platform.system().lower()
    current_machine = (machine or platform.machine() or "").lower()
    if current_platform.startswith("win"):
        return ["windows", "win32"]
    if current_platform == "darwin":
        if current_machine in {"arm64", "aarch64"}:
            return ["macos-arm64", "macos-universal", "macos", "darwin"]
        return ["macos-x86_64", "macos-universal", "macos", "darwin"]
    raise ReleaseUpdateError(f"Plataforma no soportada para updater: {current_platform}")


def download_release_asset(
    asset: ReleaseAsset,
    *,
    target_dir: Path,
    urlopen_func: Callable = urlopen,
    timeout: int = 120,
) -> DownloadedUpdate:
    if not asset.file_name.lower().endswith(".zip"):
        raise ReleaseUpdateError("El updater integrado necesita un archivo .zip de actualizacion.")
    if asset.sha256.strip() in PLACEHOLDER_SHA_VALUES:
        raise ReleaseUpdateError("El manifiesto de actualizacion no tiene un sha256 real.")

    target_dir.mkdir(parents=True, exist_ok=True)
    target_path = target_dir / asset.file_name
    partial_path = target_path.with_name(f"{target_path.name}.part")
    digest = hashlib.sha256()
    request = Request(asset.url, headers={"User-Agent": USER_AGENT})
    try:
        with urlopen_func(request, timeout=timeout) as response, partial_path.open("wb") as target:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                digest.update(chunk)
                target.write(chunk)
    except Exception as exc:  # noqa: BLE001
        partial_path.unlink(missing_ok=True)
        raise ReleaseUpdateError(f"No se pudo descargar la actualizacion: {exc}") from exc

    actual_sha = digest.hexdigest()
    expected_sha = asset.sha256.lower().replace("sha256:", "").strip()
    if actual_sha.lower() != expected_sha:
        partial_path.unlink(missing_ok=True)
        raise ReleaseUpdateError(
            "La descarga no paso la verificacion SHA256. "
            f"Esperado={expected_sha}, recibido={actual_sha}."
        )
    partial_path.replace(target_path)
    return DownloadedUpdate(asset=asset, path=target_path, sha256=actual_sha)


def prepare_release_update(
    *,
    config_path: Path,
    staging_dir: Path,
    urlopen_func: Callable = urlopen,
) -> DownloadedUpdate:
    config = load_update_config(config_path)
    manifest = load_latest_manifest(config, urlopen_func=urlopen_func)
    asset = select_release_asset(manifest)
    return download_release_asset(asset, target_dir=staging_dir, urlopen_func=urlopen_func)


def _asset_from_payload(payload: dict, *, revision: str, platform_key: str, notes: list[str]) -> ReleaseAsset:
    url = str(payload.get("url") or payload.get("browser_download_url") or "").strip()
    sha256 = str(payload.get("sha256") or payload.get("digest") or "").replace("sha256:", "").strip()
    file_name = str(payload.get("file_name") or payload.get("name") or Path(url).name).strip()
    if not url:
        raise ReleaseUpdateError(f"El asset para {platform_key} no tiene url.")
    if not file_name:
        raise ReleaseUpdateError(f"El asset para {platform_key} no tiene nombre.")
    return ReleaseAsset(
        revision=revision,
        url=url,
        sha256=sha256,
        platform_key=platform_key,
        file_name=file_name,
        notes=notes,
    )


def _asset_name_matches_platform(name: str, platform_key: str) -> bool:
    if not name.endswith(".zip"):
        return False
    if platform_key.startswith("windows"):
        return "update" in name and ("windows" in name or "win" in name or "autohellegado_update" in name)
    if platform_key.startswith("macos") or platform_key == "darwin":
        return "update" in name and ("mac" in name or "darwin" in name)
    return False


def _clean_optional_string(value: object) -> str | None:
    if value is None:
        return None
    cleaned = str(value).strip()
    return cleaned or None
