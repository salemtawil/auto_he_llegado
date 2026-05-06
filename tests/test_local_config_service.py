import json

from services.local_config_service import LocalConfigService


def test_load_old_config_adds_theme_default(tmp_path) -> None:
    service = LocalConfigService()
    service._config_dir = tmp_path  # noqa: SLF001
    service._config_path = tmp_path / "main_app_config.json"  # noqa: SLF001
    service._config_path.write_text(  # noqa: SLF001
        json.dumps(
            {
                "agent_name": "Agente Local",
                "page_timeout_seconds": 30,
                "action_timeout_seconds": 20,
            }
        ),
        encoding="utf-8",
    )

    config = service.load()

    assert config.theme_mode == "light"
    assert config.max_selfie_retries == 10
    assert config.keep_browser_open is True
    assert config.flow_engine == "traditional"
    assert config.enable_browser_extension is True
    assert config.browser_extension_overlay is True
    assert config.last_result_filter == "general"
    assert config.agent_name_confirmed is False


def test_save_persists_theme_mode(tmp_path) -> None:
    service = LocalConfigService()
    service._config_dir = tmp_path  # noqa: SLF001
    service._config_path = tmp_path / "main_app_config.json"  # noqa: SLF001

    saved = service.save(
        service.load().model_copy(
            update={
                "agent_name": "Agente Nocturno",
                "theme_mode": "dark",
            }
        )
    )

    raw_data = json.loads(service._config_path.read_text(encoding="utf-8"))  # noqa: SLF001

    assert saved.theme_mode == "dark"
    assert raw_data["theme_mode"] == "dark"


def test_save_persists_browser_extension_flags(tmp_path) -> None:
    service = LocalConfigService()
    service._config_dir = tmp_path  # noqa: SLF001
    service._config_path = tmp_path / "main_app_config.json"  # noqa: SLF001

    saved = service.save(
        service.load().model_copy(
            update={
                "enable_browser_extension": True,
                "browser_extension_overlay": False,
            }
        )
    )

    raw_data = json.loads(service._config_path.read_text(encoding="utf-8"))  # noqa: SLF001

    assert saved.enable_browser_extension is True
    assert saved.browser_extension_overlay is False
    assert raw_data["enable_browser_extension"] is True
    assert raw_data["browser_extension_overlay"] is False


def test_save_persists_selfie_retry_limit(tmp_path) -> None:
    service = LocalConfigService()
    service._config_dir = tmp_path  # noqa: SLF001
    service._config_path = tmp_path / "main_app_config.json"  # noqa: SLF001

    saved = service.save(
        service.load().model_copy(
            update={
                "max_selfie_retries": 0,
            }
        )
    )

    raw_data = json.loads(service._config_path.read_text(encoding="utf-8"))  # noqa: SLF001

    assert saved.max_selfie_retries == 0
    assert raw_data["max_selfie_retries"] == 0


def test_load_existing_agent_name_marks_it_confirmed_when_not_placeholder(tmp_path) -> None:
    service = LocalConfigService()
    service._config_dir = tmp_path  # noqa: SLF001
    service._config_path = tmp_path / "main_app_config.json"  # noqa: SLF001
    service._config_path.write_text(  # noqa: SLF001
        json.dumps(
            {
                "agent_name": "Carlos",
                "page_timeout_seconds": 180,
                "action_timeout_seconds": 180,
            }
        ),
        encoding="utf-8",
    )

    config = service.load()

    assert config.agent_name == "Carlos"
    assert config.agent_name_confirmed is True


def test_load_old_config_migrates_browser_extension_defaults(tmp_path) -> None:
    service = LocalConfigService()
    service._config_dir = tmp_path  # noqa: SLF001
    service._config_path = tmp_path / "main_app_config.json"  # noqa: SLF001
    service._config_path.write_text(  # noqa: SLF001
        json.dumps(
            {
                "agent_name": "Carlos",
                "page_timeout_seconds": 180,
                "action_timeout_seconds": 180,
            }
        ),
        encoding="utf-8",
    )

    config = service.load()
    raw_data = json.loads(service._config_path.read_text(encoding="utf-8"))  # noqa: SLF001

    assert config.enable_browser_extension is True
    assert config.browser_extension_overlay is True
    assert raw_data["flow_engine"] == "traditional"
    assert raw_data["enable_browser_extension"] is True
    assert raw_data["browser_extension_overlay"] is True
