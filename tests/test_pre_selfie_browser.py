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


def test_compinche_owner_step_follows_recreated_generic_iframe(browser):
    site = CompincheSite()
    context = browser.new_context()
    page = context.new_page()
    start_html = """
        <main>
          <button id="start">Iniciar verificaci&#243;n</button>
        </main>
        <script>
          document.querySelector('#start').onclick = () => parent.postMessage('owner', '*');
        </script>
    """
    owner_html = """
        <section aria-modal="true">
          <h2>Verificaci&#243;n del propietario de la cuenta</h2>
          <div role="button" id="selfie">Continuar con selfie</div>
        </section>
        <script>
          document.querySelector('#selfie').onclick = () => parent.postMessage('photo', '*');
        </script>
    """
    photo_html = """
        <section aria-modal="true">
          <input type="file" id="user_avatar" hidden>
          <button>Continuar</button>
        </section>
    """
    try:
        page.route("https://compinche-flow.example/start", lambda route: route.fulfill(body=start_html, content_type="text/html"))
        page.route("https://owner-check.example/step", lambda route: route.fulfill(body=owner_html, content_type="text/html"))
        page.route("https://owner-check.example/photo", lambda route: route.fulfill(body=photo_html, content_type="text/html"))
        page.set_content(
            """
            <script>
              window.addEventListener('message', event => {
                const current = document.querySelector('iframe');
                if (current) current.remove();
                const frame = document.createElement('iframe');
                frame.src = event.data === 'owner'
                  ? 'https://owner-check.example/step'
                  : 'https://owner-check.example/photo';
                document.body.appendChild(frame);
              });
            </script>
            <iframe src="https://compinche-flow.example/start"></iframe>
            """
        )
        page.frames[1].locator("#start").wait_for()

        root = site._wait_for_flow_root(page, site._get_action_spec("He llegado"), timeout_ms=1000).root
        result = site._complete_pre_selfie_account_step(root, page=page, progress_callback=None, timeout_ms=1000)

        assert result.locator("input[type=file]").count() == 1
        assert "owner-check.example/photo" in result.evaluate("() => window.location.href")
        assert site._active_flow_context is not None
    finally:
        context.close()


def test_ready4drive_owner_step_follows_recreated_generic_iframe(browser):
    site = Ready4DriveSite()
    context = browser.new_context()
    page = context.new_page()
    start_html = """
        <main>
          <button id="start">Iniciar verificaci&#243;n</button>
        </main>
        <script>
          document.querySelector('#start').onclick = () => parent.postMessage('owner', '*');
        </script>
    """
    owner_html = """
        <section aria-modal="true">
          <h2>Verificaci&#243;n del propietario de la cuenta</h2>
          <div role="button" id="selfie">Continuar con selfie</div>
        </section>
        <script>
          document.querySelector('#selfie').onclick = () => parent.postMessage('photo', '*');
        </script>
    """
    photo_html = """
        <section aria-modal="true">
          <input type="file" id="user_avatar" hidden>
          <button>Continuar</button>
        </section>
    """
    try:
        page.route("https://ready4drive-flow.example/start", lambda route: route.fulfill(body=start_html, content_type="text/html"))
        page.route("https://owner-check.example/ready-step", lambda route: route.fulfill(body=owner_html, content_type="text/html"))
        page.route("https://owner-check.example/ready-photo", lambda route: route.fulfill(body=photo_html, content_type="text/html"))
        page.set_content(
            """
            <script>
              window.addEventListener('message', event => {
                const current = document.querySelector('iframe');
                if (current) current.remove();
                const frame = document.createElement('iframe');
                frame.src = event.data === 'owner'
                  ? 'https://owner-check.example/ready-step'
                  : 'https://owner-check.example/ready-photo';
                document.body.appendChild(frame);
              });
            </script>
            <iframe src="https://ready4drive-flow.example/start"></iframe>
            """
        )
        page.frames[1].locator("#start").wait_for()

        root = site._wait_for_flow_root(page, site._get_action_spec("He llegado"), timeout_ms=1000).root
        result = site._complete_pre_selfie_account_step(root, page=page, progress_callback=None, timeout_ms=1000)

        assert result.locator("input[type=file]").count() == 1
        assert "owner-check.example/ready-photo" in result.evaluate("() => window.location.href")
        assert site._active_flow_context is not None
    finally:
        context.close()


@pytest.mark.parametrize("site_type", [CompincheSite, Ready4DriveSite])
def test_el_dialogo_de_tres_opciones_se_resuelve_omitiendo(browser, site_type):
    """La version nueva del dialogo del propietario, con el HTML real.

    Llega con "Enviar enlace al dueno" ya elegida, que espera a una persona
    que no esta delante, y el boton de seguir no existe hasta elegir. Elegir
    la equivocada, o no elegir, deja el proceso parado para siempre.
    """

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
    # Radiogroup de Headless UI, igual que el selector de cuenta: las tres
    # opciones comparten aria-label y lo que las distingue es el texto.
    owner_html = """
        <div role="dialog" aria-modal="true">
          <h2>Verificaci&#243;n del propietario de la cuenta</h2>
          <p>Elige c&#243;mo continuar</p>
          <div role="radiogroup" id="opciones">
            <span role="radio" aria-label="owner-verification" aria-checked="true" data-checked="" id="enlace">
              <span>Enviar enlace al due&#241;o</span>
              <span>El due&#241;o se verifica desde su propio tel&#233;fono.</span>
              <button id="copiar">Copiar enlace</button>
            </span>
            <span role="radio" aria-label="owner-verification" aria-checked="false" id="video">
              <span>Verificaci&#243;n autom&#225;tica de video</span>
              <span>Sube tres selfies del due&#241;o.</span>
            </span>
            <span role="radio" aria-label="owner-verification" aria-checked="false" id="omitir">
              <span>Omitir verificaci&#243;n</span>
              <span>Contin&#250;a solo con tu selfie.</span>
            </span>
          </div>
          <div id="pie"><button id="seguir" disabled>Continuar con selfie</button></div>
        </div>
        <script>
          window.elegidas = [];
          for (const opcion of document.querySelectorAll('[role="radio"]')) {
            opcion.onclick = () => {
              window.elegidas.push(opcion.id);
              for (const otra of document.querySelectorAll('[role="radio"]')) {
                otra.setAttribute('aria-checked', String(otra === opcion));
                if (otra === opcion) otra.setAttribute('data-checked', '');
                else otra.removeAttribute('data-checked');
              }
              // El boton de seguir solo existe tras elegir, y solo si la
              // opcion elegida permite continuar sin el dueno.
              // El boton ya estaba ahi, deshabilitado: solo se activa al
              // elegir la opcion que permite seguir sin el dueno.
              const seguir = document.querySelector('#seguir');
              seguir.disabled = opcion.id !== 'omitir';
              seguir.onclick = () => {
                if (seguir.disabled) return;
                parent.postMessage('photo', '*');
              };
            };
          }
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

        root = site._wait_for_flow_root(page, site._get_action_spec("He llegado"), timeout_ms=1000).root
        result = site._complete_pre_selfie_account_step(root, page=page, progress_callback=None, timeout_ms=3000)

        assert result.locator("input[type=file]").count() == 1
        assert "verify.example/photo" in result.evaluate("() => window.location.href")
        assert site._active_flow_context is not None
    finally:
        context.close()


@pytest.mark.parametrize("site_type", [CompincheSite, Ready4DriveSite, ParipeSite])
def test_nunca_se_elige_enviar_enlace_ni_verificacion_de_video(browser, site_type):
    """Las otras dos opciones esperan a una persona que no esta.

    Si el paso eligiera una de ellas, el proceso se quedaria colgado sin que
    nada fallara, que es la peor forma de fallar.
    """

    site = site_type()
    context = browser.new_context()
    page = context.new_page()
    owner_html = """
        <div role="dialog" aria-modal="true">
          <h2>Verificaci&#243;n del propietario de la cuenta</h2>
          <div role="radiogroup">
            <span role="radio" aria-checked="true" data-checked="" id="enlace">
              <span>Enviar enlace al due&#241;o</span>
              <button id="copiar">Copiar enlace</button>
            </span>
            <span role="radio" aria-checked="false" id="video">
              <span>Verificaci&#243;n autom&#225;tica de video</span>
            </span>
            <span role="radio" aria-checked="false" id="omitir">
              <span>Omitir verificaci&#243;n</span>
            </span>
          </div>
        </div>
        <script>
          window.elegidas = [];
          for (const opcion of document.querySelectorAll('[role="radio"], button')) {
            opcion.onclick = () => window.elegidas.push(opcion.id);
          }
        </script>
    """
    try:
        page.route("https://verify.example/owner", lambda route: route.fulfill(body=owner_html, content_type="text/html"))
        page.set_content('<iframe title="He llegado" src="https://verify.example/owner"></iframe>')
        frame = page.frames[1]
        frame.locator("#omitir").wait_for()

        site._omitir_verificacion_del_propietario(frame, progress_callback=None)

        elegidas = frame.evaluate("elegidas")
        assert "omitir" in elegidas
        assert "enlace" not in elegidas
        assert "video" not in elegidas
        assert "copiar" not in elegidas, "'Copiar enlace' no es el boton de seguir"
    finally:
        context.close()


@pytest.mark.parametrize("site_type", [CompincheSite, Ready4DriveSite, ParipeSite])
def test_las_opciones_dibujadas_como_tarjetas_tambien_se_pulsan(browser, site_type):
    """El caso real: las tres opciones no son radios, son <div> con texto.

    Sin rol, sin input, sin label. Los selectores de control no las ven, y
    el paso se quedaba diciendo "ausente" mientras el agente veia las tres
    opciones en pantalla.
    """

    site = site_type()
    context = browser.new_context()
    page = context.new_page()
    owner_html = """
        <style>.tarjeta { cursor: pointer; padding: 8px; display: block; }</style>
        <div role="dialog" aria-modal="true">
          <h2>Verificaci&#243;n del propietario de la cuenta</h2>
          <div class="lista">
            <div class="tarjeta" id="enlace">
              <span>Enviar enlace al due&#241;o</span>
              <button id="copiar">Copiar enlace</button>
            </div>
            <div class="tarjeta" id="video"><span>Verificaci&#243;n autom&#225;tica de video</span></div>
            <div class="tarjeta" id="omitir">
              <span>Omitir verificaci&#243;n</span>
              <span>Contin&#250;a solo con tu selfie.</span>
            </div>
          </div>
        </div>
        <script>
          window.elegidas = [];
          for (const tarjeta of document.querySelectorAll('.tarjeta, #copiar')) {
            tarjeta.onclick = (evento) => {
              window.elegidas.push(evento.currentTarget.id);
            };
          }
        </script>
    """
    try:
        page.route("https://verify.example/owner", lambda route: route.fulfill(body=owner_html, content_type="text/html"))
        page.set_content('<iframe title="He llegado" src="https://verify.example/owner"></iframe>')
        frame = page.frames[1]
        frame.locator("#omitir").wait_for()

        site._omitir_verificacion_del_propietario(frame, progress_callback=None)

        elegidas = frame.evaluate("elegidas")
        assert "omitir" in elegidas, f"no se pulso la tarjeta correcta: {elegidas}"
        assert "enlace" not in elegidas
        assert "video" not in elegidas
        assert "copiar" not in elegidas
        # Y la pagina queda como estaba: la marca que se usa para apuntar al
        # elemento no puede quedarse puesta.
        assert frame.evaluate("document.querySelectorAll('[data-ahl-opcion]').length") == 0
    finally:
        context.close()


@pytest.mark.parametrize("site_type", [CompincheSite, Ready4DriveSite])
def test_la_tarjeta_que_se_pulsa_es_la_fila_entera_no_la_lista(browser, site_type):
    """Subir de más pulsaría el contenedor de las tres opciones.

    Ahí el click no elige nada, o elige la que quede debajo del cursor.
    """

    site = site_type()
    context = browser.new_context()
    page = context.new_page()
    owner_html = """
        <style>.lista, .tarjeta, .t { cursor: pointer; display: block; padding: 6px; }</style>
        <div role="dialog" aria-modal="true">
          <h2>Verificaci&#243;n del propietario de la cuenta</h2>
          <div class="lista" id="lista">
            <div class="tarjeta" id="enlace"><span class="t">Enviar enlace al due&#241;o</span></div>
            <div class="tarjeta" id="omitir"><span class="t">Omitir verificaci&#243;n</span></div>
          </div>
        </div>
        <script>
          window.pulsado = null;
          for (const nodo of document.querySelectorAll('[id]')) {
            nodo.addEventListener('click', (evento) => {
              if (window.pulsado === null) window.pulsado = evento.target.closest('[id]').id;
            });
          }
        </script>
    """
    try:
        page.route("https://verify.example/owner", lambda route: route.fulfill(body=owner_html, content_type="text/html"))
        page.set_content('<iframe title="He llegado" src="https://verify.example/owner"></iframe>')
        frame = page.frames[1]
        frame.locator("#omitir").wait_for()

        site._omitir_verificacion_del_propietario(frame, progress_callback=None)

        assert frame.evaluate("pulsado") == "omitir", "subio hasta la lista entera"
    finally:
        context.close()


def test_el_diagnostico_graba_la_opcion_aunque_no_sea_un_control(browser):
    """La prueba de fondo: que el archivo sirva para lo que se hizo.

    Si una opcion dibujada como <div> no apareciera en el archivo, el modo
    diagnostico no resolveria nada: seguiriamos sin saber que hay en la
    pantalla, que es justo lo que pasaba con las capturas de pantalla.
    """

    from services.diagnostic_recorder import DiagnosticRecorder

    context = browser.new_context()
    page = context.new_page()
    owner_html = """
        <style>.tarjeta { cursor: pointer; display: block; padding: 8px; }</style>
        <div role="dialog" aria-modal="true">
          <h2>Verificaci&#243;n del propietario de la cuenta</h2>
          <div class="tarjeta" id="enlace"><span>Enviar enlace al due&#241;o</span></div>
          <div class="tarjeta" id="omitir"><span>Omitir verificaci&#243;n</span></div>
        </div>
        <p id="fuera">esto esta fuera del dialogo</p>
    """
    try:
        page.route("https://verify.example/owner", lambda route: route.fulfill(body=owner_html, content_type="text/html"))
        page.goto("https://verify.example/owner")
        page.locator("#omitir").wait_for()

        grabador = DiagnosticRecorder()
        grabador.capturar(page, "dialogo_del_propietario")
        captura = grabador.exportar()["capturas"][0]

        # 1. La opcion aparece, con su ruta, aunque no sea ningun control.
        cadena = captura["coincidencias"].get("Omitir verificación")
        assert cadena, "la opcion no aparece en el archivo"
        assert cadena[0]["ruta"], "sin ruta no se puede volver a encontrar"
        assert any(nodo["id"] == "omitir" for nodo in cadena)
        assert any(nodo["pulsable"] for nodo in cadena), "no dice cual responde al raton"

        # 2. El HTML es el del dialogo, no el de media pagina.
        assert "Omitir verificaci" in captura["html"]
        assert "esto esta fuera del dialogo" not in captura["html"]

        # 3. Y el texto que ve el agente queda tal cual.
        assert any("Omitir verificaci" in linea for linea in captura["texto_visible"])
    finally:
        context.close()


@pytest.mark.parametrize("site_type", [CompincheSite, Ready4DriveSite, ParipeSite])
def test_no_se_pulsa_el_boton_antes_de_elegir_la_opcion(browser, site_type):
    """La trampa del atajo: el boton ya esta ahi, pero deshabilitado.

    La busqueda rapida mira tamano y visibilidad, no si el boton esta
    activo, asi que lo encontraba igual. Si se buscara el boton antes de
    elegir, se pulsaria un boton muerto y el proceso se quedaria mirando un
    dialogo que no avanza, sin que nada fallara.
    """

    site = site_type()
    context = browser.new_context()
    page = context.new_page()
    owner_html = """
        <style>.tarjeta { cursor: pointer; display: block; padding: 8px; }</style>
        <div role="dialog" aria-modal="true">
          <h2>Verificaci&#243;n del propietario de la cuenta</h2>
          <div class="tarjeta" id="enlace"><span>Enviar enlace al due&#241;o</span></div>
          <div class="tarjeta" id="omitir"><span>Omitir verificaci&#243;n</span></div>
          <button id="seguir" disabled>Continuar con selfie</button>
        </div>
        <script>
          window.orden = [];
          document.querySelector('#omitir').onclick = () => {
            window.orden.push('omitir');
            document.querySelector('#seguir').disabled = false;
          };
          document.querySelector('#seguir').onclick = () => window.orden.push('seguir');
        </script>
    """
    try:
        page.route("https://verify.example/owner", lambda route: route.fulfill(body=owner_html, content_type="text/html"))
        page.set_content('<iframe title="He llegado" src="https://verify.example/owner"></iframe>')
        frame = page.frames[1]
        frame.locator("#omitir").wait_for()

        site._omitir_verificacion_del_propietario(frame, progress_callback=None)
        boton = site._esperar_boton_de_continuar(
            frame,
            site._selectors.self_owner_continue_texts + site._selectors.continue_texts,
        )
        assert boton is not None
        boton.click()

        assert frame.evaluate("orden") == ["omitir", "seguir"], (
            "se pulso el boton antes de elegir la opcion"
        )
    finally:
        context.close()
