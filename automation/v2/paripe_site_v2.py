"""Paripe v2: la automatizacion de siempre, sin las esperas que no esperan nada.

Cada metodo redefinido documenta que hacia la v1 y por que cambia. Todo sale de
la auditoria del 2026-10-14, verificada linea a linea contra el codigo.

La v1 (`automation/paripe_site.py`) NO se toca.
"""

from __future__ import annotations

from collections.abc import Mapping
from contextlib import suppress

from automation.paripe_site import ParipeSite
from automation.v2.mixins import AutomationV2Mixin


class ParipeSiteV2(AutomationV2Mixin, ParipeSite):
    #: La v1 esperaba 800 ms tras pulsar "Continuar" descartando CUALQUIER
    #: deteccion de bloque, aunque el snapshot rapido ya mostrase el boton final
    #: y los datos. Es decir: una espera que corre con la condicion ya cumplida.
    #: En v2 se reduce y, sobre todo, se puede cortar en cuanto hay senal.
    POST_CONTINUE_GRACE_SECONDS = 0.25

    #: La v1 hacia `page.wait_for_timeout(500)` justo despues de despachar el
    #: click final. Despues solo hay un emit_progress, y a continuacion el
    #: pipeline sondea el mismo DOM con _detect_final_result. No espera nada.
    POST_FINAL_CLICK_SETTLE_MS = 0

    # ------------------------------------------------------------------
    # Login
    # ------------------------------------------------------------------

    def _open_login(self, page, *, timeout_ms: int) -> None:
        """Abre el login sin la pausa ciega de 3 segundos.

        La v1 (paripe_site.py:1235) hacia `page.wait_for_timeout(3_000)` justo
        despues de navegar, y acto seguido llamaba a `_first_visible(...)` sobre
        el telefono y la contrasena con 8 s de timeout cada uno. Esas dos
        esperas YA comprueban la condicion real, asi que los 3 s eran tiempo
        regalado en cada corrida, estuviera el formulario listo o no. Y si la
        URL no era la de login, se repetian otros 3 s.

        Aqui se navega igual y se deja que las esperas por condicion hagan su
        trabajo. Si la pagina tarda, `_first_visible` espera lo que haga falta;
        si esta lista, se sigue de inmediato.
        """

        def _navigate() -> None:
            try:
                page.goto(self._ENTRY_URL, wait_until="commit", timeout=10_000)
            except Exception:
                with suppress(Exception):
                    page.goto(self._ENTRY_URL, timeout=10_000)

        print(f"Paripe v2 initial_url={self._ENTRY_URL}")
        _navigate()

        if "paripe.io/login" not in page.url:
            _navigate()

        phone_input = self._first_visible(page, self._selectors.login_phone, timeout_ms=8_000)
        password_input = self._first_visible(page, self._selectors.login_password, timeout_ms=8_000)
        print(
            "Paripe v2 login_inputs_found "
            f"phone={phone_input is not None} password={password_input is not None} "
            f"current_url={page.url}"
        )

    # ------------------------------------------------------------------
    # Foto en segundo plano
    # ------------------------------------------------------------------

    def _await_background_photo(
        self,
        preparation,
        *,
        progress_callback=None,
        process_id=None,
    ):
        """Igual que la v1, pero la espera del hilo de foto tiene tope.

        La v1 (paripe_site.py:564) hacia `preparation.ready_event.wait()` SIN
        timeout. Si el hilo que reserva la foto se colgaba —Supabase sin
        responder, por ejemplo— la corrida se quedaba bloqueada ahi para
        siempre, sin error y sin forma de detectarlo. El equivalente en
        base_site.py si estaba acotado.

        Aqui se espera con tope. Si vence, se cae al mismo camino de reserva
        directa que la v1 ya usa cuando no hay preparacion en marcha, asi que
        el comportamiento observable sigue siendo "la corrida consigue su foto",
        no "la corrida falla".
        """

        if preparation is not None and not preparation.ready_event.is_set():
            llego_a_tiempo = preparation.ready_event.wait(
                timeout=self.BACKGROUND_PHOTO_WAIT_TIMEOUT_S
            )
            if not llego_a_tiempo:
                self._record_timeline_event(
                    "photo_future_wait_timeout",
                    process_id=process_id,
                    timeout_seconds=self.BACKGROUND_PHOTO_WAIT_TIMEOUT_S,
                )
                self._record_run_stat(
                    "photo_future_wait_timeout",
                    process_id=process_id,
                    timeout_seconds=self.BACKGROUND_PHOTO_WAIT_TIMEOUT_S,
                )
                self.emit_progress(
                    progress_callback,
                    phase="photo_prepare",
                    message=(
                        "La preparacion de foto en segundo plano no respondio en "
                        f"{self.BACKGROUND_PHOTO_WAIT_TIMEOUT_S:.0f}s: reservando directamente."
                    ),
                )
                with suppress(Exception):
                    preparation.consumed = True
                reserved_photo = self._photo_service.reserve_photo(process_id=process_id)
                return reserved_photo, False

        return super()._await_background_photo(
            preparation,
            progress_callback=progress_callback,
            process_id=process_id,
        )

    # ------------------------------------------------------------------
    # Diagnostico de selfie: mismo valor, calculado solo si se usa
    # ------------------------------------------------------------------

    def _selfie_signal_diagnostics(self, page, dialog=None):
        """Difiere el calculo hasta que alguien lea el resultado.

        Medido con un Locator que cuenta llamadas: la version v1 cuesta ~6
        idas y vueltas a Playwright por cada elemento clicable, mas 6 fijas
        (30 elementos -> 186 llamadas). El grueso esta en
        `_count_continue_buttons`, que recorre todos los `button, [role=button],
        a` preguntando visible + enabled + texto, y se ejecuta dos veces
        (pagina y dialogo).

        `_wait_for_details_dialog` lo calcula en CADA vuelta del bucle
        (paripe_site.py:2586, poll de 75 ms) pero solo lo lee dentro de
        `if should_log_timing:`, limitado a ~0.35 s. Es decir: 3 de cada 4
        veces se tira entero.

        Aqui NO se cambia que se mide ni como: se devuelve un mapping perezoso
        que llama a la implementacion de la v1 la primera vez que alguien pide
        una clave. Si ese poll no acaba logueando, no se toca el DOM. Los
        valores, cuando se leen, son identicos a los de la v1.
        """

        return _DiagnosticoPerezoso(lambda: super(ParipeSiteV2, self)._selfie_signal_diagnostics(page, dialog))


    # ------------------------------------------------------------------
    # Señales de bloque: sin re-resolver un contexto ya resuelto
    # ------------------------------------------------------------------

    def _collect_block_signals(self, flow_context, page):
        """Mide el contexto que llega, en vez de volver a buscarlo.

        La v1 empieza con `candidate = self._resolve_block_context(...)`, y
        `_resolve_block_context` cuesta ~2,1 s medidos contra Chromium real
        (recorre candidatos llamando a `_find_photo_phase_dialog`,
        `_context_looks_like_block` y `_score_block_context` por cada uno).

        El problema es que sus DOS puntos de llamada ya le pasan un contexto
        resuelto:
          - paripe_site.py:2578, con el `block_context` resuelto en la 2556.
          - paripe_site.py:3093, con el `candidate` resuelto en la 3092.

        O sea: resuelve lo ya resuelto. Comprobado contra Chromium real que
        `_resolve_block_context` es idempotente (resolver dos veces devuelve el
        mismo nodo del DOM) y que las señales salen identicas.

        Se reutiliza `_collect_block_signals_from_dialog`, que ya existe en la
        v1 y es esta misma funcion sin la re-resolucion.
        """

        return self._collect_block_signals_from_dialog(flow_context)


class _DiagnosticoPerezoso(Mapping):
    """Dict que no calcula nada hasta la primera lectura, y solo una vez."""

    __slots__ = ("_calcular", "_valores")

    def __init__(self, calcular):
        self._calcular = calcular
        self._valores = None

    def _resolver(self):
        if self._valores is None:
            self._valores = dict(self._calcular())
        return self._valores

    def __getitem__(self, clave):
        return self._resolver()[clave]

    def __iter__(self):
        return iter(self._resolver())

    def __len__(self):
        return len(self._resolver())

    def __repr__(self):
        if self._valores is None:
            return "<diagnostico sin calcular>"
        return repr(self._valores)

