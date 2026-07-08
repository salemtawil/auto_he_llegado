from automation.browser_manager import BrowserManager, BrowserSession
from config.settings import Settings
from pathlib import Path
from types import SimpleNamespace


class StubPage:
    def __init__(self, value=None, *, frames=None, main_frame=None) -> None:
        self._value = value
        self.frames = frames or []
        self.main_frame = main_frame

    def evaluate(self, expression, *args):
        if callable(self._value):
            return self._value(expression, *args)
        return self._value


class StubFrame:
    def __init__(self, value=None, *, url=None, name=None, parent_frame=None, is_detached=False) -> None:
        self._value = value
        self.url = url
        self.name = name
        self.parent_frame = parent_frame
        self._is_detached = is_detached

    def evaluate(self, expression, *args):
        if callable(self._value):
            return self._value(expression, *args)
        return self._value

    def is_detached(self):
        return self._is_detached


def build_settings(
    tmp_path,
    *,
    use_chrome_profile_extension=False,
    chrome_profile_dir=None,
    chrome_executable_path=None,
) -> Settings:
    return Settings(
        app_name="test-app",
        app_env="test",
        log_level="INFO",
        project_root=tmp_path,
        local_data_dir=tmp_path / "local_data",
        supabase_url="https://example.supabase.co",
        supabase_key="test-key",
        supabase_storage_bucket="photo-pool",
        supabase_photos_table="photos",
        supabase_process_logs_table="process_logs",
        supabase_photo_batches_table="photo_ingest_batches",
        supabase_photo_candidates_table="photo_candidates",
        supabase_profiles_table="profiles",
        supabase_timeout_seconds=30,
        admin_access_password="secret",
        weekly_min_approved_photos=20,
        video_frame_interval_seconds=0.0,
        video_max_candidate_frames=300,
        video_jpeg_quality=88,
        use_chrome_profile_extension=use_chrome_profile_extension,
        chrome_profile_dir=chrome_profile_dir,
        chrome_executable_path=chrome_executable_path,
    )


def test_build_extension_launch_args_points_to_extension_dir(tmp_path) -> None:
    extension_dir = tmp_path / "browser_extension"
    extension_dir.mkdir()

    args = BrowserManager._build_extension_launch_args(extension_dir, extension_overlay=False)  # noqa: SLF001

    assert f"--disable-extensions-except={extension_dir.resolve()}" in args
    assert f"--load-extension={extension_dir.resolve()}" in args
    assert "--auto-he-llegado-overlay=off" in args


def test_browser_manager_detects_extension_launch_args() -> None:
    args = [
        "--window-size=1440,960",
        "--disable-extensions-except=C:\\ext",
        "--load-extension=C:\\ext",
    ]

    assert BrowserManager._has_extension_launch_arg(args, "--load-extension=") is True  # noqa: SLF001
    assert BrowserManager._has_extension_launch_arg(args, "--disable-extensions-except=") is True  # noqa: SLF001
    assert BrowserManager._has_extension_launch_arg(args, "--user-data-dir=") is False  # noqa: SLF001


def test_installed_profile_launch_args_omit_unpacked_extension_flags() -> None:
    args = BrowserManager._build_installed_profile_launch_args()  # noqa: SLF001

    assert "--disable-extensions-except=" not in " ".join(args)
    assert "--load-extension=" not in " ".join(args)


def test_installed_profile_launch_kwargs_use_executable_path_when_defined(tmp_path) -> None:
    profile_dir = tmp_path / "chrome-profile"
    executable_path = tmp_path / "chrome.exe"

    kwargs = BrowserManager._build_installed_profile_launch_kwargs(  # noqa: SLF001
        chrome_profile_dir=profile_dir,
        chrome_executable_path=executable_path,
        browser_launch_args=["--window-size=1440,960"],
    )

    assert kwargs["user_data_dir"] == str(profile_dir)
    assert kwargs["executable_path"] == str(executable_path)
    assert "channel" not in kwargs
    assert "--load-extension=" not in " ".join(kwargs["args"])


def test_installed_profile_launch_kwargs_never_include_channel() -> None:
    kwargs = BrowserManager._build_installed_profile_launch_kwargs(  # noqa: SLF001
        chrome_profile_dir=Path(r"D:\profile"),
        chrome_executable_path=Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
        browser_launch_args=["--window-size=1440,960"],
    )

    assert "channel" not in kwargs
    assert kwargs["executable_path"] == r"C:\Program Files\Google\Chrome\Application\chrome.exe"


def test_installed_profile_cdp_command_uses_real_chrome_profile_and_debug_port() -> None:
    command = BrowserManager._build_installed_profile_cdp_command(  # noqa: SLF001
        chrome_executable_path=Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
        chrome_profile_dir=Path(r"D:\profile"),
        browser_launch_args=["--window-size=1440,960"],
    )

    assert command[0] == r"C:\Program Files\Google\Chrome\Application\chrome.exe"
    assert "--remote-debugging-port=9222" in command
    assert "--user-data-dir=D:\\profile" in command
    assert "--load-extension=" not in " ".join(command)
    assert "--disable-extensions-except=" not in " ".join(command)


def test_browser_manager_uses_fixed_chrome_profile_dir_for_installed_profile_mode(tmp_path) -> None:
    profile_dir = tmp_path / "chrome-profile"
    profile_dir.mkdir()
    settings = build_settings(
        tmp_path,
        use_chrome_profile_extension=True,
        chrome_profile_dir=profile_dir,
    )
    manager = BrowserManager(settings=settings)

    resolved = manager._get_required_chrome_profile_dir()  # noqa: SLF001

    assert resolved == profile_dir.resolve()
    assert manager._use_installed_chrome_profile_extension() is True  # noqa: SLF001


def test_browser_manager_requires_profile_dir_in_installed_profile_mode(tmp_path) -> None:
    manager = BrowserManager(
        settings=build_settings(
            tmp_path,
            use_chrome_profile_extension=True,
            chrome_profile_dir=None,
        )
    )

    try:
        manager._get_required_chrome_profile_dir()  # noqa: SLF001
    except RuntimeError as exc:
        assert "AUTO_HE_LLEGADO_CHROME_PROFILE_DIR" in str(exc)
    else:
        raise AssertionError("Expected missing Chrome profile dir to raise.")


def test_browser_manager_requires_existing_profile_dir_in_installed_profile_mode(tmp_path) -> None:
    manager = BrowserManager(
        settings=build_settings(
            tmp_path,
            use_chrome_profile_extension=True,
            chrome_profile_dir=tmp_path / "missing-profile",
        )
    )

    try:
        manager._get_required_chrome_profile_dir()  # noqa: SLF001
    except RuntimeError as exc:
        assert "AUTO_HE_LLEGADO_CHROME_PROFILE_DIR does not exist" in str(exc)
    else:
        raise AssertionError("Expected missing profile dir to raise.")


def test_browser_manager_requires_valid_chrome_executable_path(tmp_path) -> None:
    manager = BrowserManager(
        settings=build_settings(
            tmp_path,
            use_chrome_profile_extension=True,
            chrome_profile_dir=tmp_path / "chrome-profile",
            chrome_executable_path=tmp_path / "missing-chrome.exe",
        )
    )

    try:
        manager._get_configured_chrome_executable_path()  # noqa: SLF001
    except RuntimeError as exc:
        assert "AUTO_HE_LLEGADO_CHROME_EXECUTABLE_PATH does not exist" in str(exc)
    else:
        raise AssertionError("Expected invalid chrome executable path to raise.")


def test_browser_manager_optional_real_chrome_executable_path_uses_configured_value(tmp_path) -> None:
    executable_path = tmp_path / "Program Files" / "Google" / "Chrome" / "Application" / "chrome.exe"
    executable_path.parent.mkdir(parents=True)
    executable_path.write_text("", encoding="utf-8")
    manager = BrowserManager(
        settings=build_settings(
            tmp_path,
            chrome_executable_path=executable_path,
        )
    )

    resolved = manager._get_optional_real_chrome_executable_path()  # noqa: SLF001

    assert resolved == executable_path.resolve()


def test_browser_manager_optional_real_chrome_executable_path_returns_none_when_unset(tmp_path) -> None:
    manager = BrowserManager(settings=build_settings(tmp_path))

    assert manager._get_optional_real_chrome_executable_path() is None  # noqa: SLF001


def test_browser_manager_optional_real_chrome_executable_path_returns_none_when_setting_missing(tmp_path) -> None:
    legacy_settings = SimpleNamespace(
        project_root=tmp_path,
        local_data_dir=tmp_path / "local_data",
        use_chrome_profile_extension=False,
        chrome_profile_dir=None,
    )
    manager = BrowserManager(settings=legacy_settings)

    assert manager._get_optional_real_chrome_executable_path() is None  # noqa: SLF001


def test_browser_manager_optional_real_chrome_executable_path_returns_none_when_empty(tmp_path) -> None:
    legacy_settings = SimpleNamespace(
        project_root=tmp_path,
        local_data_dir=tmp_path / "local_data",
        use_chrome_profile_extension=False,
        chrome_profile_dir=None,
        chrome_executable_path="",
    )
    manager = BrowserManager(settings=legacy_settings)

    assert manager._get_optional_real_chrome_executable_path() is None  # noqa: SLF001


def test_browser_manager_rejects_playwright_bundled_chromium_executable(tmp_path) -> None:
    executable_path = tmp_path / "ms-playwright" / "chromium-1208" / "chrome-win64" / "chrome.exe"
    executable_path.parent.mkdir(parents=True)
    executable_path.write_text("", encoding="utf-8")
    manager = BrowserManager(
        settings=build_settings(
            tmp_path,
            use_chrome_profile_extension=True,
            chrome_profile_dir=tmp_path,
            chrome_executable_path=executable_path,
        )
    )

    try:
        manager._get_configured_chrome_executable_path()  # noqa: SLF001
    except RuntimeError as exc:
        assert "must use real Google Chrome" in str(exc)
    else:
        raise AssertionError("Expected Playwright chromium executable to raise.")


def test_begin_new_run_initializes_extension_config_snapshot() -> None:
    run_id = BrowserManager.begin_new_run(flow_engine="extension")

    payload = BrowserManager.get_latest_extension_debug()

    assert payload is not None
    assert payload["run_id"] == run_id
    assert payload["note"] == "process_start_pending"
    assert payload["extension_enabled"] is True
    assert str(payload["extension_path"]).endswith("browser_extension")
    assert str(payload["manifest_path"]).replace("\\", "/").endswith("browser_extension/manifest.json")


def test_is_real_google_chrome_executable_accepts_real_chrome_name(tmp_path) -> None:
    executable_path = tmp_path / "Program Files" / "Google" / "Chrome" / "Application" / "chrome.exe"
    executable_path.parent.mkdir(parents=True)
    executable_path.write_text("", encoding="utf-8")

    assert BrowserManager._is_real_google_chrome_executable(str(executable_path)) is True  # noqa: SLF001


def test_is_real_google_chrome_executable_rejects_playwright_chromium(tmp_path) -> None:
    executable_path = tmp_path / "ms-playwright" / "chromium-1208" / "chrome-win64" / "chrome.exe"
    executable_path.parent.mkdir(parents=True)
    executable_path.write_text("", encoding="utf-8")

    assert BrowserManager._is_real_google_chrome_executable(str(executable_path)) is False  # noqa: SLF001


def test_is_real_google_chrome_executable_rejects_missing_path(tmp_path) -> None:
    executable_path = tmp_path / "missing" / "chrome.exe"

    assert BrowserManager._is_real_google_chrome_executable(str(executable_path)) is False  # noqa: SLF001


def test_has_expected_extension_entry_matches_exact_extension_name() -> None:
    entries = [
        {"name": "Otro Extension"},
        {"name": "Auto He Llegado Observer"},
    ]

    assert BrowserManager._has_expected_extension_entry(entries) is True  # noqa: SLF001


def test_has_expected_extension_entry_rejects_unrelated_entries() -> None:
    entries = [
        {"name": "Otro Extension"},
        {"name": "service_worker.js"},
    ]

    assert BrowserManager._has_expected_extension_entry(entries) is False  # noqa: SLF001


def test_browser_session_reports_extension_launch_diagnostics(tmp_path) -> None:
    extension_dir = tmp_path / "browser_extension"
    extension_dir.mkdir()
    (extension_dir / "manifest.json").write_text("{}", encoding="utf-8")
    (extension_dir / "content.js").write_text("// test", encoding="utf-8")
    BrowserManager.begin_new_run(flow_engine="extension")
    BrowserManager.remember_extension_debug(
        {
            "run_id": BrowserManager.current_run_id(),
            "browser_args": BrowserManager._build_browser_launch_args(  # noqa: SLF001
                BrowserManager._build_extension_launch_args(extension_dir, extension_overlay=True)  # noqa: SLF001
            ),
        }
    )
    page = StubPage(
        lambda expression, *args: {
            "state": {"phase": "dashboard"},
            "marker": "loaded",
            "overlayPresent": False,
            "overlayFramePresent": False,
        }
    )
    browser_type = type("BrowserType", (), {"executable_path": r"C:\Program Files\Google\Chrome\Application\chrome.exe"})()
    browser = type("Browser", (), {"browser_type": browser_type})()
    session = BrowserSession(
        playwright=object(),
        browser=browser,
        context=object(),
        page=page,
        extension_enabled=True,
        extension_loaded=True,
        extension_path=str(extension_dir.resolve()),
    )

    payload = session.capture_extension_debug(note="launch_diagnostics")

    assert payload is not None
    assert payload["browser_channel"] == "chrome"
    assert payload["browser_executable"] == r"C:\Program Files\Google\Chrome\Application\chrome.exe"
    assert payload["extension_dir"] == str(extension_dir.resolve())
    assert payload["extension_dir_is_absolute"] is True
    assert payload["manifest_exists"] is True
    assert payload["load_extension_arg_present"] is True
    assert payload["disable_extensions_except_arg_present"] is True


def test_browser_session_reads_observer_state_from_page() -> None:
    page = StubPage({"phase": "selfie_stage"})
    session = BrowserSession(
        playwright=object(),
        browser=object(),
        context=object(),
        page=page,
    )

    state = session.read_observer_state()

    assert state is not None
    assert state["phase"] == "selfie_stage"
    assert state["frame_role"] == "top"
    assert state.get("stateSource") != "dom_markers"


def test_browser_session_reads_observer_state_from_first_valid_frame() -> None:
    main_frame = StubFrame({"phase": "unknown"}, url="https://paripe.io/app", name="main")
    child_frame = StubFrame(
        {"phase": "selfie_stage", "href": "https://widget.example/frame"},
        url="https://widget.example/frame",
        name="flow-frame",
    )
    page = StubPage(
        {"phase": "unknown"},
        frames=[main_frame, child_frame],
        main_frame=main_frame,
    )
    session = BrowserSession(
        playwright=object(),
        browser=object(),
        context=object(),
        page=page,
    )

    state = session.read_observer_state()

    assert state is not None
    assert state["phase"] == "selfie_stage"
    assert state["frame_url"] == "https://widget.example/frame"
    assert state["frame_name"] == "flow-frame"
    assert state["frame_role"] == "iframe"
    assert state["diagnostics"]["frameCount"] == 2
    assert state["diagnostics"]["frameScan"][0]["selected"] is False
    assert state["diagnostics"]["frameScan"][1]["selected"] is True


def test_browser_session_falls_back_to_page_when_no_frame_state_is_valid() -> None:
    main_frame = StubFrame({"phase": "unknown"}, url="https://paripe.io/app", name="main")
    child_frame = StubFrame({"site": "unknown"}, url="about:blank", name="child")
    page = StubPage(
        {"phase": "unknown", "diagnostics": {"href": "https://paripe.io/app"}},
        frames=[main_frame, child_frame],
        main_frame=main_frame,
    )
    session = BrowserSession(
        playwright=object(),
        browser=object(),
        context=object(),
        page=page,
    )

    state = session.read_observer_state()

    assert state is not None
    assert state["frame_role"] == "top"
    assert state["diagnostics"]["selectedFrameRole"] == "top"
    assert state["diagnostics"]["frameCount"] == 2


def test_browser_session_reads_extension_state_from_dom_markers() -> None:
    main_frame = StubFrame(
        {
            "contentLoaded": "true",
            "contentHref": "https://paripe.io/app",
            "contentHostname": "paripe.io",
            "contentFrame": "top",
            "bridgeStatus": "missing",
            "mainWorldReady": None,
            "mainWorldHref": None,
            "mainWorldHostname": None,
            "pingLoaded": None,
            "pingHref": None,
            "pingHostname": None,
        },
        url="https://paripe.io/app",
        name="main",
    )
    child_frame = StubFrame(
        {
            "contentLoaded": "true",
            "contentHref": "https://widget.example/frame",
            "contentHostname": "widget.example",
            "contentFrame": "iframe",
            "bridgeStatus": "ready",
            "mainWorldReady": "ready",
            "mainWorldHref": "https://widget.example/frame",
            "mainWorldHostname": "widget.example",
            "pingLoaded": "true",
            "pingHref": "https://widget.example/frame",
            "pingHostname": "widget.example",
            "site": "paripe",
            "lang": "es",
            "phase": "selfie_stage",
            "lastValidPhase": "selfie_stage",
            "signalsUserAvatar": "true",
            "signalsContinue": "1",
            "signalsLoading": "false",
            "signalsBlock": "false",
            "signalsIframe": "1",
            "updatedAt": "2026-04-23T12:00:00.000Z",
        },
        url="https://widget.example/frame",
        name="flow-frame",
    )
    page = StubPage(None, frames=[main_frame, child_frame], main_frame=main_frame)
    session = BrowserSession(
        playwright=object(),
        browser=object(),
        context=object(),
        page=page,
    )

    state = session.read_extension_state_from_dom_markers()

    assert state is not None
    assert state["stateSource"] == "marker_report"
    assert state["frameRole"] == "iframe"
    assert state["href"] == "https://widget.example/frame"
    assert state["hostname"] == "widget.example"
    assert state["site"] == "paripe"
    assert state["lang"] == "es"
    assert state["phase"] == "selfie_stage"
    assert state["signals"]["userAvatarVisible"] is True
    assert state["signals"]["continueCount"] == 1
    assert state["bridgeStatus"] == "ready"
    assert state["pingLoaded"] is True


def test_browser_session_uses_dom_markers_when_window_state_is_missing() -> None:
    marker_payload = {
            "contentLoaded": "true",
            "contentHref": "https://paripe.io/app",
            "contentHostname": "paripe.io",
            "contentFrame": "top",
            "bridgeStatus": "ready",
            "mainWorldReady": "ready",
            "mainWorldHref": "https://paripe.io/app",
            "mainWorldHostname": "paripe.io",
            "pingLoaded": "true",
            "pingHref": "https://paripe.io/app",
            "pingHostname": "paripe.io",
            "site": "paripe",
            "lang": "es",
            "phase": "dashboard",
            "lastValidPhase": "dashboard",
            "signalsUserAvatar": "false",
            "signalsContinue": "0",
            "signalsLoading": "false",
            "signalsBlock": "false",
            "signalsIframe": "0",
            "updatedAt": "2026-04-23T12:00:00.000Z",
        }
    main_frame = StubFrame(
        lambda expression, *args: None if "__autoHeLlegadoState" in expression else marker_payload,
        url="https://paripe.io/app",
        name="main",
    )
    page = StubPage(None, frames=[main_frame], main_frame=main_frame)
    session = BrowserSession(
        playwright=object(),
        browser=object(),
        context=object(),
        page=page,
    )

    state = session.read_observer_state()

    assert state is not None
    assert state["stateSource"] == "marker_report"
    assert state["frameRole"] == "top"
    assert state["href"] == "https://paripe.io/app"
    assert state["site"] == "paripe"
    assert state["phase"] == "dashboard"


def test_browser_session_infers_site_from_hostname_when_marker_site_is_unknown() -> None:
    marker_payload = {
        "contentLoaded": "true",
        "contentHref": "https://paripe.io/app",
        "contentHostname": "paripe.io",
        "contentFrame": "top",
        "bridgeStatus": "missing",
        "mainWorldReady": None,
        "mainWorldHref": None,
        "mainWorldHostname": None,
        "pingLoaded": None,
        "pingHref": None,
        "pingHostname": None,
        "site": "unknown",
        "lang": "unknown",
        "phase": "block_read_ready",
        "lastValidPhase": "block_read_ready",
        "signalsUserAvatar": "false",
        "signalsContinue": "0",
        "signalsLoading": "false",
        "signalsBlock": "true",
        "signalsIframe": "0",
        "updatedAt": "2026-04-23T12:00:00.000Z",
    }
    main_frame = StubFrame(marker_payload, url="https://paripe.io/app", name="main")
    page = StubPage(None, frames=[main_frame], main_frame=main_frame)
    session = BrowserSession(
        playwright=object(),
        browser=object(),
        context=object(),
        page=page,
    )

    state = session.read_extension_state_from_dom_markers()

    assert state is not None
    assert state["site"] == "paripe"
    assert state["hostname"] == "paripe.io"


def test_browser_session_reads_extension_ping_from_all_frames() -> None:
    main_frame = StubFrame(None, url="https://paripe.io/app", name="main")
    child_frame = StubFrame(
        {
            "loaded": True,
            "href": "https://widget.example/frame",
            "hostname": "widget.example",
            "timestamp": 123,
        },
        url="https://widget.example/frame",
        name="flow-frame",
    )
    page = StubPage(None, frames=[main_frame, child_frame], main_frame=main_frame)
    session = BrowserSession(
        playwright=object(),
        browser=object(),
        context=object(),
        page=page,
    )

    report = session.read_extension_ping_from_all_frames()

    assert report["total_frames"] == 2
    assert report["frames_with_ping"] == 1
    assert report["selected_frame"]["frame_url"] == "https://widget.example/frame"
    assert report["selected_frame"]["is_top_frame"] is False
    assert report["frames"][1]["selected"] is True
    assert report["frames"][1]["ping"]["loaded"] is True


def test_browser_session_reads_content_markers_from_all_frames() -> None:
    main_frame = StubFrame(
        {
            "contentLoaded": "true",
            "contentHref": "https://paripe.io/app",
            "contentHostname": "paripe.io",
            "contentFrame": "top",
            "bridgeStatus": "missing",
            "mainWorldReady": None,
            "mainWorldHref": None,
            "mainWorldHostname": None,
            "pingLoaded": None,
            "pingHref": None,
            "pingHostname": None,
        },
        url="https://paripe.io/app",
        name="main",
    )
    child_frame = StubFrame(
        {
            "contentLoaded": "true",
            "contentHref": "https://widget.example/frame",
            "contentHostname": "widget.example",
            "contentFrame": "iframe",
            "bridgeStatus": "ready",
            "mainWorldReady": "ready",
            "mainWorldHref": "https://widget.example/frame",
            "mainWorldHostname": "widget.example",
            "pingLoaded": "true",
            "pingHref": "https://widget.example/frame",
            "pingHostname": "widget.example",
            "site": "paripe",
            "lang": "es",
            "phase": "selfie_stage",
            "lastValidPhase": "selfie_stage",
            "signalsUserAvatar": "true",
            "signalsContinue": "1",
            "signalsLoading": "false",
            "signalsBlock": "false",
            "signalsIframe": "1",
            "updatedAt": "2026-04-23T12:00:00.000Z",
        },
        url="https://widget.example/frame",
        name="flow-frame",
    )
    page = StubPage(None, frames=[main_frame, child_frame], main_frame=main_frame)
    session = BrowserSession(
        playwright=object(),
        browser=object(),
        context=object(),
        page=page,
    )

    report = session.read_content_markers_from_all_frames()

    assert report["total_frames"] == 2
    assert report["frames_with_content_marker"] == 2
    assert report["frames_with_main_world_marker"] == 1
    assert report["selected_frame"]["content_href"] == "https://widget.example/frame"
    assert report["frames"][0]["bridge_status"] == "missing"
    assert report["frames"][1]["main_world_ready"] is True
    assert report["frames"][1]["selected"] is True


def test_browser_session_prefers_marker_frame_with_known_phase() -> None:
    main_marker_payload = {
            "contentLoaded": "true",
            "contentHref": "https://paripe.io/app",
            "contentHostname": "paripe.io",
            "contentFrame": "top",
            "bridgeStatus": "missing",
            "mainWorldReady": None,
            "mainWorldHref": None,
            "mainWorldHostname": None,
            "pingLoaded": None,
            "pingHref": None,
            "pingHostname": None,
            "site": "unknown",
            "lang": "unknown",
            "phase": "unknown",
            "lastValidPhase": "unknown",
            "signalsUserAvatar": "false",
            "signalsContinue": "0",
            "signalsLoading": "false",
            "signalsBlock": "false",
            "signalsIframe": "0",
            "updatedAt": "2026-04-23T12:00:00.000Z",
        }
    main_frame = StubFrame(
        lambda expression, *args: None if "__autoHeLlegadoState" in expression else main_marker_payload,
        url="https://paripe.io/app",
        name="main",
    )
    child_marker_payload = {
            "contentLoaded": "true",
            "contentHref": "https://widget.example/frame",
            "contentHostname": "widget.example",
            "contentFrame": "iframe",
            "bridgeStatus": "missing",
            "mainWorldReady": None,
            "mainWorldHref": None,
            "mainWorldHostname": None,
            "pingLoaded": None,
            "pingHref": None,
            "pingHostname": None,
            "site": "paripe",
            "lang": "es",
            "phase": "loading_after_continue",
            "lastValidPhase": "selfie_stage",
            "signalsUserAvatar": "false",
            "signalsContinue": "0",
            "signalsLoading": "true",
            "signalsBlock": "false",
            "signalsIframe": "1",
            "updatedAt": "2026-04-23T12:00:00.000Z",
        }
    child_frame = StubFrame(
        lambda expression, *args: None if "__autoHeLlegadoState" in expression else child_marker_payload,
        url="https://widget.example/frame",
        name="flow-frame",
    )
    page = StubPage(None, frames=[main_frame, child_frame], main_frame=main_frame)
    session = BrowserSession(
        playwright=object(),
        browser=object(),
        context=object(),
        page=page,
    )

    state = session.read_observer_state()

    assert state is not None
    assert state["stateSource"] == "marker_report"
    assert state["frameRole"] == "iframe"
    assert state["phase"] == "loading_after_continue"


def test_browser_session_keeps_current_fallback_when_dom_markers_are_all_unknown() -> None:
    marker_payload = {
        "contentLoaded": "true",
        "contentHref": "https://paripe.io/app",
        "contentHostname": "paripe.io",
        "contentFrame": "top",
        "bridgeStatus": "missing",
        "mainWorldReady": None,
        "mainWorldHref": None,
        "mainWorldHostname": None,
        "pingLoaded": None,
        "pingHref": None,
        "pingHostname": None,
        "site": "unknown",
        "lang": "unknown",
        "phase": "unknown",
        "lastValidPhase": "unknown",
        "signalsUserAvatar": "false",
        "signalsContinue": "0",
        "signalsLoading": "false",
        "signalsBlock": "false",
        "signalsIframe": "0",
        "updatedAt": "2026-04-23T12:00:00.000Z",
    }
    main_frame = StubFrame(
        lambda expression, *args: None if "__autoHeLlegadoState" in expression else marker_payload,
        url="https://paripe.io/app",
        name="main",
    )
    page = StubPage(
        {"phase": "unknown", "diagnostics": {"href": "https://paripe.io/app"}},
        frames=[main_frame],
        main_frame=main_frame,
    )
    session = BrowserSession(
        playwright=object(),
        browser=object(),
        context=object(),
        page=page,
    )

    state = session.read_observer_state()

    assert state is not None
    assert state.get("stateSource") != "dom_markers"
    assert state["phase"] == "unknown"


def test_capture_extension_debug_uses_marker_report_state_when_window_state_is_missing() -> None:
    marker_payload = {
        "contentLoaded": "true",
        "contentHref": "https://paripe.io/app",
        "contentHostname": "paripe.io",
        "contentFrame": "top",
        "bridgeStatus": "missing",
        "mainWorldReady": None,
        "mainWorldHref": None,
        "mainWorldHostname": None,
        "pingLoaded": None,
        "pingHref": None,
        "pingHostname": None,
        "site": "paripe",
        "lang": "es",
        "phase": "block_read_ready",
        "lastValidPhase": "selfie_stage",
        "signalsUserAvatar": "false",
        "signalsContinue": "0",
        "signalsLoading": "false",
        "signalsBlock": "true",
        "signalsIframe": "0",
        "updatedAt": "2026-04-23T12:00:00.000Z",
    }
    main_frame = StubFrame(
        lambda expression, *args, payload=marker_payload: None if "__autoHeLlegadoState" in expression else payload,
        url="https://paripe.io/app",
        name="main",
    )
    page = StubPage(
        lambda expression, *args: {
            "state": args[0] if args else None,
            "windowState": None,
            "marker": "loaded",
            "overlayPresent": False,
            "overlayFramePresent": False,
        },
        frames=[main_frame],
        main_frame=main_frame,
    )
    session = BrowserSession(
        playwright=object(),
        browser=object(),
        context=object(),
        page=page,
        extension_enabled=True,
        extension_loaded=True,
    )

    payload = session.capture_extension_debug(note="marker_report_state")

    assert payload is not None
    assert payload["state"]["stateSource"] == "marker_report"
    assert payload["state"]["phase"] == "block_read_ready"
    assert payload["state"]["signals"]["blockReady"] is True
    assert payload["state"]["diagnostics"]["content_frame"] == "top"


def test_capture_extension_debug_marks_extension_loaded_from_dom_markers_without_service_worker() -> None:
    marker_payload = {
        "contentLoaded": "true",
        "contentHref": "https://paripe.io/app",
        "contentHostname": "paripe.io",
        "contentFrame": "top",
        "bridgeStatus": "disabled",
        "mainWorldReady": None,
        "mainWorldHref": None,
        "mainWorldHostname": None,
        "pingLoaded": "true",
        "pingHref": "https://paripe.io/app",
        "pingHostname": "paripe.io",
        "site": "paripe",
        "lang": "es",
        "phase": "dashboard",
        "lastValidPhase": "dashboard",
        "signalsUserAvatar": "false",
        "signalsContinue": "0",
        "signalsLoading": "false",
        "signalsBlock": "false",
        "signalsIframe": "0",
        "updatedAt": "2026-04-23T12:00:00.000Z",
    }
    BrowserManager.begin_new_run(flow_engine="extension")
    BrowserManager.remember_extension_debug(
        {
            "run_id": BrowserManager.current_run_id(),
            "extension_mode": "installed_profile",
            "service_worker_status": "missing_non_blocking",
            "browser_args": [],
        }
    )
    main_frame = StubFrame(
        lambda expression, *args: None if "__autoHeLlegadoState" in expression else marker_payload,
        url="https://paripe.io/app",
        name="main",
    )
    page = StubPage(
        lambda expression, *args: {
            "state": args[0] if args else None,
            "windowState": None,
            "marker": "loaded",
            "overlayPresent": True,
            "overlayFramePresent": False,
        },
        frames=[main_frame],
        main_frame=main_frame,
    )
    session = BrowserSession(
        playwright=object(),
        browser=object(),
        context=object(),
        page=page,
        extension_enabled=True,
        extension_loaded=False,
        extension_service_worker_url=None,
    )

    payload = session.capture_extension_debug(note="dom_markers_without_worker")

    assert payload is not None
    assert payload["extension_loaded"] is True
    assert payload["extension_mode"] == "dom_markers"
    assert payload["service_worker_status"] == "missing_non_blocking"
    assert payload["extension_validation_error"] is None


def test_capture_extension_debug_reports_missing_dom_markers_when_extension_inactive() -> None:
    BrowserManager.begin_new_run(flow_engine="extension")
    BrowserManager.remember_extension_debug(
        {
            "run_id": BrowserManager.current_run_id(),
            "extension_mode": "installed_profile",
            "service_worker_status": "missing_non_blocking",
            "browser_args": [],
        }
    )
    page = StubPage(
        lambda expression, *args: {
            "state": None,
            "windowState": None,
            "marker": None,
            "overlayPresent": False,
            "overlayFramePresent": False,
        },
        frames=[],
        main_frame=None,
    )
    session = BrowserSession(
        playwright=object(),
        browser=object(),
        context=object(),
        page=page,
        extension_enabled=True,
        extension_loaded=False,
        extension_service_worker_url=None,
    )

    payload = session.capture_extension_debug(note="inactive_profile")

    assert payload is not None
    assert payload["extension_loaded"] is False
    assert payload["service_worker_status"] == "missing_non_blocking"
    assert payload["extension_validation_error"] == "No DOM marker found; extension may not be active in this profile"


def test_browser_session_debug_list_all_frames_reports_text_and_parent() -> None:
    main_frame = StubFrame(
        {
            "readyState": "complete",
            "title": "Paripe",
            "textPreview": "Cuenta prestada Cuenta propia He llegado",
        },
        url="https://paripe.io/app",
        name="main",
    )
    child_frame = StubFrame(
        {
            "readyState": "interactive",
            "title": "Flow iframe",
            "textPreview": "Para continuar, selecciona una opcion y tomate una foto tipo selfie",
        },
        url="https://widget.example/frame",
        name="flow-frame",
        parent_frame=main_frame,
    )
    page = StubPage(None, frames=[main_frame, child_frame], main_frame=main_frame)
    session = BrowserSession(
        playwright=object(),
        browser=object(),
        context=object(),
        page=page,
    )

    report = session.debug_list_all_frames()

    assert report["total_frames"] == 2
    assert report["frames"][0]["frame_url"] == "https://paripe.io/app"
    assert report["frames"][1]["parent_frame_url"] == "https://paripe.io/app"
    assert report["frames"][1]["ready_state"] == "interactive"
    assert "foto tipo selfie" in report["frames"][1]["text_preview"]


def test_capture_extension_debug_includes_ping_report() -> None:
    main_frame = StubFrame(
        {
            "loaded": True,
            "href": "https://paripe.io/app",
            "hostname": "paripe.io",
            "timestamp": 123,
        },
        url="https://paripe.io/app",
        name="main",
    )
    page = StubPage(
        {
            "state": {"phase": "dashboard"},
            "marker": "loaded",
            "overlayPresent": False,
            "overlayFramePresent": False,
        },
        frames=[main_frame],
        main_frame=main_frame,
    )
    session = BrowserSession(
        playwright=object(),
        browser=object(),
        context=object(),
        page=page,
        extension_enabled=True,
        extension_loaded=True,
    )

    payload = session.capture_extension_debug(note="ping_check")

    assert payload is not None
    assert payload["ping_report"]["total_frames"] == 1
    assert payload["ping_report"]["frames_with_ping"] == 1
    assert payload["marker_report"]["total_frames"] == 1
    assert payload["frame_debug_report"]["total_frames"] == 1


def test_capture_extension_debug_keeps_last_debug_when_frame_scan_fails() -> None:
    page = StubPage(
        lambda expression, *args: {
            "state": {"phase": "dashboard"},
            "marker": "loaded",
            "overlayPresent": False,
            "overlayFramePresent": False,
        },
        frames=[],
        main_frame=None,
    )
    session = BrowserSession(
        playwright=object(),
        browser=object(),
        context=object(),
        page=page,
        extension_enabled=True,
        extension_loaded=True,
    )
    session._last_extension_debug = {  # noqa: SLF001
        "frame_debug_report": {"total_frames": 1, "frames": [{"frame_url": "cached"}]},
        "marker_report": {"total_frames": 1, "frames": []},
        "ping_report": {"total_frames": 1, "frames": []},
    }
    session.debug_list_all_frames = lambda page=None: (_ for _ in ()).throw(RuntimeError("Cannot switch to a different thread"))  # type: ignore[method-assign]  # noqa: SLF001

    payload = session.capture_extension_debug(note="thread_failure")

    assert payload is not None
    assert payload["frame_debug_report"]["total_frames"] == 1
    assert payload["frame_debug_report"]["frames"][0]["frame_url"] == "cached"
    assert payload["frame_debug_error"] == "Cannot switch to a different thread"


def test_browser_manager_remembers_latest_extension_debug() -> None:
    BrowserManager.begin_new_run(flow_engine="extension")
    BrowserManager.remember_extension_debug({"marker": "loaded", "state": {"phase": "dashboard"}})

    payload = BrowserManager.get_latest_extension_debug()

    assert payload is not None
    assert payload["marker"] == "loaded"
    assert payload["state"] == {"phase": "dashboard"}


def test_begin_new_run_hides_previous_session_from_latest_session() -> None:
    manager = BrowserManager()
    BrowserManager.begin_new_run(flow_engine="extension")
    old_session = BrowserSession(
        playwright=object(),
        browser=object(),
        context=object(),
        page=StubPage(),
        run_id=BrowserManager.current_run_id(),
    )
    BrowserManager._register_session(old_session)  # noqa: SLF001

    BrowserManager.begin_new_run(flow_engine="extension")

    assert BrowserManager.get_latest_session() is None
    debug = BrowserManager.get_latest_extension_debug()
    assert debug is not None
    assert debug["note"] == "process_start_pending"

    old_session.shutdown()


def test_browser_session_shutdown_keeps_persistent_profile_dir(tmp_path) -> None:
    profile_dir = tmp_path / "chrome-profile"
    profile_dir.mkdir()
    session = BrowserSession(
        playwright=object(),
        browser=object(),
        context=object(),
        page=StubPage(),
        profile_dir=str(profile_dir),
        cleanup_profile_dir=False,
    )

    session.shutdown()

    assert profile_dir.exists() is True


def test_browser_session_shutdown_removes_managed_temp_profile_dir(tmp_path) -> None:
    profile_dir = tmp_path / "temp-profile"
    profile_dir.mkdir()
    session = BrowserSession(
        playwright=object(),
        browser=object(),
        context=object(),
        page=StubPage(),
        profile_dir=str(profile_dir),
        cleanup_profile_dir=True,
    )

    session.shutdown()

    assert profile_dir.exists() is False


def test_browser_session_shutdown_disconnect_only_skips_browser_close() -> None:
    events: list[str] = []

    class Recorder:
        def __init__(self, name: str) -> None:
            self._name = name

        def close(self) -> None:
            events.append(f"{self._name}.close")

        def stop(self) -> None:
            events.append(f"{self._name}.stop")

    session = BrowserSession(
        playwright=Recorder("playwright"),
        browser=Recorder("browser"),
        context=Recorder("context"),
        page=Recorder("page"),
        disconnect_only=True,
    )

    session.shutdown()

    assert events == ["playwright.stop"]
