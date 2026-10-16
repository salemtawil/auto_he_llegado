"""Que version esta instalada ahora mismo.

Sin esto, pulsar "Actualizar app" se descargaba y reaplicaba la misma version
una y otra vez: `prepare_release_update` se bajaba la ultima sin comparar con
nada, porque no habia nada con que comparar.

El archivo vive en `local_data/`, que es una de las rutas protegidas del helper
(`PROTECTED_PATH_PATTERNS`), asi que sobrevive a las actualizaciones.

Lo escribe el HELPER, no la app, y solo cuando la actualizacion se aplico de
verdad. Si el helper revierte, no se escribe: asi el archivo nunca miente sobre
lo que hay instalado.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

REVISION_FILE_RELATIVE = Path("local_data") / "installed_revision.json"


def revision_file_path(install_dir: Path) -> Path:
    return install_dir / REVISION_FILE_RELATIVE


def read_installed_revision(install_dir: Path) -> str | None:
    """La revision instalada, o None si no se sabe.

    Ante cualquier duda devuelve None, que significa "actualiza igualmente".
    Equivocarse hacia None cuesta una descarga de mas; equivocarse hacia una
    revision falsa deja al agente sin actualizar y sin saberlo.
    """

    path = revision_file_path(install_dir)
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    revision = payload.get("revision")
    if not isinstance(revision, str):
        return None
    revision = revision.strip()
    return revision or None


def write_installed_revision(install_dir: Path, revision: str) -> bool:
    """Deja constancia de la revision aplicada. Devuelve si pudo escribirla."""

    revision = (revision or "").strip()
    if not revision:
        return False
    path = revision_file_path(install_dir)
    payload = {
        "revision": revision,
        "applied_at": datetime.now().isoformat(timespec="seconds"),
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    except Exception:
        return False
    return True
