from __future__ import annotations

import json
from pathlib import Path

from config.paths import DEFAULT_CONFIG_DATA_DIR
from config.settings import Settings, get_settings
from core.models import LocalConfig


class LocalConfigService:
    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._config_dir = self._settings.local_data_dir / "config"
        self._config_dir.mkdir(parents=True, exist_ok=True)
        self._config_path = self._config_dir / "main_app_config.json"

    @property
    def config_path(self) -> Path:
        return self._config_path

    def load(self) -> LocalConfig:
        if not self._config_path.exists():
            config = LocalConfig()
            self.save(config)
            return config
        data = json.loads(self._config_path.read_text(encoding="utf-8"))
        should_migrate = False
        if "agent_name_confirmed" not in data:
            agent_name = str(data.get("agent_name", "") or "").strip()
            data["agent_name_confirmed"] = bool(agent_name and agent_name.lower() != "agente local")
            should_migrate = True
        if "flow_engine" not in data:
            data["flow_engine"] = "traditional"
            should_migrate = True
        if "enable_browser_extension" not in data:
            data["enable_browser_extension"] = True
            should_migrate = True
        if "browser_extension_overlay" not in data:
            data["browser_extension_overlay"] = True
            should_migrate = True
        config = LocalConfig.model_validate(data)
        if should_migrate:
            self.save(config)
        return config

    def save(self, config: LocalConfig) -> LocalConfig:
        self._config_dir.mkdir(parents=True, exist_ok=True)
        self._config_path.write_text(
            json.dumps(config.model_dump(mode="json"), indent=2),
            encoding="utf-8",
        )
        return config
