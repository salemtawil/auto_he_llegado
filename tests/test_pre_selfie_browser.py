from time import monotonic

import pytest
from playwright.sync_api import Error, sync_playwright

from automation.compinche_site import CompincheSite
from automation.paripe_site import ParipeSite
from automation.ready4drive_site import Ready4DriveSite


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as playwright:
        try:
            instance = playwright.chromium.launch(headless=True, channel="chrome")
        except Error:
            pytest.skip("Local Chrome is required for the verification browser regression")
        yield instance
        instance.close()


@pytest.mark.parametrize("site_type", [CompincheSite, Ready4DriveSite, ParipeSite])
@pytest.mark.parametrize("owner_step", [False, True])
def test_buttons_advance_to_hidden_photo_input(browser, monkeypatch, site_type, owner_step):
    site = site_type()
    context = browser.new_context()
    page = context.new_page()
    html = """
        <div role="dialog" aria-modal="true" id="dialog">
          <button style="display:none">Iniciar verificaci&#243;n</button>
          <label><input type="radio" id="borrowed">Cuenta prestada</label>
          <button id="start">Iniciar verificaci&#243;n</button>
        </div>
        <script>
          window.clicks = [];
          window.delays = [];
          window.rendered = performance.now();
          function showPhoto() {
            document.querySelector('#dialog').outerHTML =
              '<div role="dialog" aria-modal="true" id="dialog"><input type="file" id="user_avatar" hidden>' +
              '<button>Continuar</button></div>';
          }
          document.querySelector('#start').onclick = () => {
            clicks.push('start');
            delays.push(performance.now() - rendered);
            if (document.querySelector('#borrowed').checked) throw new Error('Account option changed');
            document.querySelector('#dialog').innerHTML = '<p>Cargando...</p>';
            setTimeout(() => {
              if (!OWNER_STEP) { showPhoto(); return; }
              document.querySelector('#dialog').outerHTML =
                '<div role="dialog" aria-modal="true" id="dialog"><h2>Verificar con una selfie</h2>' +
                '<button id="selfie" disabled>Continuar con selfie</button></div>';
              const selfie = document.querySelector('#selfie');
              selfie.onclick = () => {
                clicks.push('selfie');
                delays.push(performance.now() - rendered);
                document.querySelector('#dialog').innerHTML = '<p>Cargando...</p>';
                setTimeout(showPhoto, 60);
              };
              setTimeout(() => { selfie.disabled = false; rendered = performance.now(); }, 60);
            }, 250);
          };
        </script>
    """.replace("OWNER_STEP", "true" if owner_step else "false")
    try:
        page.route("https://paripe.io/imhere-light", lambda route: route.fulfill(body=html, content_type="text/html"))
        page.set_content('<iframe title="He llegado" src="https://paripe.io/imhere-light"></iframe>')
        frame = page.frames[1]
        frame.locator("#start").wait_for()

        def unexpected_scan(*_args, **_kwargs):
            pytest.fail("Verification buttons were delayed by the general flow scan")

        if site_type is ParipeSite:
            monkeypatch.setattr(site, "_dom_signature", unexpected_scan)
            monkeypatch.setattr(site, "_find_photo_phase_dialog", unexpected_scan)
            root = site._wait_for_photo_phase(page, progress_callback=None, timeout_ms=1000)
        else:
            monkeypatch.setattr(site, "_find_action_frame", unexpected_scan)
            monkeypatch.setattr(site, "_resolve_current_flow_context", unexpected_scan)
            root = site._wait_for_flow_root(page, site._get_action_spec("He llegado"), timeout_ms=1000).root
            root = site._resolve_selfie_retry_root(page, root)

        started = monotonic()
        result = site._complete_pre_selfie_account_step(root, page=page, progress_callback=None, timeout_ms=1000)

        assert result.locator("input[type=file]").count() == 1
        assert site._active_flow_context is not None
        assert not result.locator("input[type=file]").is_visible()
        assert frame.evaluate("clicks") == (["start", "selfie"] if owner_step else ["start"])
        delays = frame.evaluate("delays")
        assert all(delay < 1500 for delay in delays), delays
        print(f"{site_type.__name__} owner={owner_step}: button delays={delays}, total={monotonic() - started:.3f}s")
    finally:
        context.close()


@pytest.mark.parametrize("site_type", [CompincheSite, Ready4DriveSite, ParipeSite])
def test_owner_step_follows_replaced_iframe_to_photo_input(browser, site_type):
    site = site_type()
    context = browser.new_context()
    page = context.new_page()
    start_html = """
        <div role="dialog" aria-modal="true">
          <button id="start">Iniciar verificaci&#243;n</button>
        </div>
        <script>
          document.querySelector('#start').onclick = () => parent.postMessage('owner', '*');
        </script>
    """
    owner_html = """
        <div role="dialog" aria-modal="true">
          <h2>Verificaci&#243;n del propietario de la cuenta</h2>
          <button id="selfie">Continuar con selfie</button>
        </div>
        <script>
          document.querySelector('#selfie').onclick = () => parent.postMessage('photo', '*');
        </script>
    """
    photo_html = """
        <div role="dialog" aria-modal="true">
          <input type="file" id="user_avatar" hidden>
          <button>Continuar</button>
        </div>
    """
    try:
        page.route("https://paripe.io/imhere-light", lambda route: route.fulfill(body=start_html, content_type="text/html"))
        page.route("https://verify.example/owner", lambda route: route.fulfill(body=owner_html, content_type="text/html"))
        page.route("https://verify.example/photo", lambda route: route.fulfill(body=photo_html, content_type="text/html"))
        page.set_content(
            """
            <script>
              window.addEventListener('message', event => {
                const frame = document.querySelector('iframe');
                if (event.data === 'owner') frame.src = 'https://verify.example/owner';
                if (event.data === 'photo') frame.src = 'https://verify.example/photo';
              });
            </script>
            <iframe title="He llegado" src="https://paripe.io/imhere-light"></iframe>
            """
        )
        frame = page.frames[1]
        frame.locator("#start").wait_for()

        if site_type is ParipeSite:
            root = site._wait_for_photo_phase(page, progress_callback=None, timeout_ms=1000)
        else:
            root = site._wait_for_flow_root(page, site._get_action_spec("He llegado"), timeout_ms=1000).root

        result = site._complete_pre_selfie_account_step(root, page=page, progress_callback=None, timeout_ms=1000)

        assert result.locator("input[type=file]").count() == 1
        assert "verify.example/photo" in result.evaluate("() => window.location.href")
        assert site._active_flow_context is not None
    finally:
        context.close()
