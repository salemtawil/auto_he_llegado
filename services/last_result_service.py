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
    """El ultimo resultado de cada panel, guardado por separado.

    Antes era un fichero unico para toda la app. Con cuatro paneles corriendo
    a la vez, el que terminaba de ultimo pisaba el resultado de los otros
    tres: al reabrir la app, tres paneles mostraban una corrida que no era la
    suya. Ahora cada panel tiene su carpeta y nadie pisa a nadie.
    """

    def __init__(self, root_dir: Path | None = None) -> None:
        self._root_dir = (root_dir or DEFAULT_LOCAL_DATA_DIR / "results").resolve()
        # Los de antes, sin panel. Se siguen leyendo -para no dejar en blanco
        # el panel la primera vez que se abre la app ya actualizada- pero no
        # se vuelven a escribir.
        self._heredado_general = self._root_dir / "latest_general.json"
        self._heredado_success = self._root_dir / "latest_success.json"
        # Dos corridas pueden terminar a la vez, aunque sean de paneles
        # distintos: `mkdir` y el reemplazo se serializan.
        self._candado = threading.Lock()

    _PANEL_POR_DEFECTO = "slot_1"

    def _carpeta(self, slot_id: str | None) -> Path:
        """La carpeta de un panel. Un slot_id raro no puede sacarnos de aqui."""

        nombre = (slot_id or self._PANEL_POR_DEFECTO).strip() or self._PANEL_POR_DEFECTO
        limpio = "".join(c for c in nombre if c.isalnum() or c in "-_")
        return self._root_dir / (limpio or self._PANEL_POR_DEFECTO)

    def _rutas(self, slot_id: str | None) -> tuple[Path, Path]:
        carpeta = self._carpeta(slot_id)
        return carpeta / "latest_general.json", carpeta / "latest_success.json"

    def save_result(
        self, result: ProcessExecutionResult, *, slot_id: str | None = None
    ) -> LastResultSnapshot:
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
        general, exitoso = self._rutas(slot_id)
        with self._candado:
            general.parent.mkdir(parents=True, exist_ok=True)
            self._write_snapshot(general, snapshot)
            if snapshot.success:
                self._write_snapshot(exitoso, snapshot)
        return snapshot

    def load_latest(
        self, *, slot_id: str | None = None, only_successful: bool = False
    ) -> LastResultSnapshot | None:
        general, exitoso = self._rutas(slot_id)
        objetivo = exitoso if only_successful else general
        snapshot = self._read_snapshot(objetivo)
        if snapshot is not None:
            return snapshot
        # Primera apertura tras actualizar: todavia no hay nada en la carpeta
        # del panel, pero puede quedar el fichero compartido de antes. Se
        # muestra solo en el primer panel, que es el que lo escribio mas
        # veces; repartirlo a los cuatro seria inventarse corridas.
        if (slot_id or self._PANEL_POR_DEFECTO) != self._PANEL_POR_DEFECTO:
            return None
        heredado = self._heredado_success if only_successful else self._heredado_general
        return self._read_snapshot(heredado)

    @staticmethod
    def _read_snapshot(target: Path) -> LastResultSnapshot | None:
        if not target.exists():
            return None
        try:
            payload = json.loads(target.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001 - un fichero roto no puede tumbar la app
            return None
        try:
            return LastResultSnapshot.model_validate(payload)
        except Exception:  # noqa: BLE001
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
