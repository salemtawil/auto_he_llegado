from __future__ import annotations

import json
from pathlib import Path

from config.paths import DEFAULT_LOCAL_DATA_DIR
from core.models import LastResultSnapshot, ProcessExecutionResult


class LastResultService:
    def __init__(self, root_dir: Path | None = None) -> None:
        self._root_dir = (root_dir or DEFAULT_LOCAL_DATA_DIR / "results").resolve()
        self._latest_general_path = self._root_dir / "latest_general.json"
        self._latest_success_path = self._root_dir / "latest_success.json"

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

    def _write_snapshot(self, target: Path, snapshot: LastResultSnapshot) -> None:
        target.write_text(snapshot.model_dump_json(indent=2), encoding="utf-8")
