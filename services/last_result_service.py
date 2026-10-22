from __future__ import annotations

import json
import os
import threading
from contextlib import suppress
from pathlib import Path
from time import sleep

from config.paths import DEFAULT_LOCAL_DATA_DIR
from core.models import LastResultSnapshot, ProcessExecutionResult


class LastResultService:
    def __init__(self, root_dir: Path | None = None) -> None:
        self._root_dir = (root_dir or DEFAULT_LOCAL_DATA_DIR / "results").resolve()
        self._latest_general_path = self._root_dir / "latest_general.json"
        self._latest_success_path = self._root_dir / "latest_success.json"
        # Un mismo servicio lo comparten los dos paneles (process_service lo
        # pasa a ambos), asi que dos corridas pueden terminar a la vez.
        self._candado = threading.Lock()

    def save_result(self, result: ProcessExecutionResult) -> LastResultSnapshot:
        snapshot = LastResultSnapshot(
            completed_at=result.completed_at,
            phone_number=result.phone_number,
            agent_name=result.agent_name,
            station_name=result.station_name,
            block_price=result.block_price,
            block_duration=result.block_duration,
            action_name=result.action_name,
            deepfakescore_retries=result.deepfakescore_retries,
            final_status=result.final_status,
            site_name=result.page_name,
            success=result.success,
            message=result.message,
        )
        with self._candado:
            self._root_dir.mkdir(parents=True, exist_ok=True)
            self._write_snapshot(self._latest_general_path, snapshot)
            if snapshot.success:
                self._write_snapshot(self._latest_success_path, snapshot)
        return snapshot

    def load_latest(self, *, only_successful: bool = False) -> LastResultSnapshot | None:
        target = self._latest_success_path if only_successful else self._latest_general_path
        if not target.exists():
            return None
        try:
            payload = json.loads(target.read_text(encoding="utf-8"))
        except Exception:
            return None
        try:
            return LastResultSnapshot.model_validate(payload)
        except Exception:
            return None

    # Reintentos del reemplazo atomico. En Windows, con la carpeta dentro de
    # OneDrive, `os.replace` sobre un fichero que el sincronizador o el
    # antivirus tiene abierto devuelve WinError 5 (acceso denegado). Es un
    # bloqueo de milisegundos: reintentar lo resuelve.
    _INTENTOS_DE_REEMPLAZO = 4
    _ESPERA_ENTRE_INTENTOS = 0.05

    def _write_snapshot(self, target: Path, snapshot: LastResultSnapshot) -> None:
        """Escribe el fichero entero o no lo toca: nunca a medias.

        Antes era un `write_text` directo. Si la app se cerraba a mitad de la
        escritura, el JSON quedaba truncado; `load_latest` se traga la
        excepcion y devuelve None, asi que el panel de "ultimo resultado" se
        quedaba vacio sin decir por que. `os.replace` es atomico dentro del
        mismo sistema de ficheros: o esta el nuevo, o sigue el anterior.

        Si el reemplazo no hay manera -OneDrive sosteniendo el fichero mas de
        lo normal- se escribe directo sobre el destino. Se pierde la garantia
        de atomicidad en ese caso concreto, pero perderla es mucho menos grave
        que no guardar el resultado de la corrida.
        """

        contenido = snapshot.model_dump_json(indent=2)
        temporal = target.with_suffix(target.suffix + ".tmp")
        temporal.write_text(contenido, encoding="utf-8")
        for intento in range(self._INTENTOS_DE_REEMPLAZO):
            try:
                os.replace(temporal, target)
                return
            except OSError:
                if intento == self._INTENTOS_DE_REEMPLAZO - 1:
                    break
                sleep(self._ESPERA_ENTRE_INTENTOS)
        target.write_text(contenido, encoding="utf-8")
        with suppress(OSError):
            temporal.unlink()
