from __future__ import annotations

import json

from contextlib import suppress

from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import asdict
from time import monotonic
from typing import Any

from automation.flow_context import ActiveFlowContext, safe_root_text
from automation.flow_state_detector import FlowStateDetector, snapshot_to_dict

from core.models import LocalConfig, ProcessExecutionRequest, SiteExecutionResult

ProgressCallback = Callable[[str, str], None]


def _a_texto_corto(valor) -> str | None:
    """La radiografia del selector, en una linea, para que quepa en el log."""

    try:
        return json.dumps(valor, ensure_ascii=False, default=str)[:800]
    except Exception:  # noqa: BLE001 - el log nunca puede ser el que falle
        return str(valor)[:800]


class BaseSite(ABC):
    site_name: str = ""
    _TIME_RANGE_RE = r"\b\d{1,2}:\d{2}\s*(?:am|pm)\s*-\s*\d{1,2}:\d{2}\s*(?:am|pm)\b"
    _DURATION_RE = r"\b\d+(?:[.,]\d+)?\s*(?:horas?|hours?|hrs?)\b"
    _FLOW_STATE_THROTTLE_S = 0.5

    def clone_for_run(self):
        return self

    def _capture_extension_debug_if_useful(self, session, **kwargs):
        """Captura el diagnostico de la extension solo si hay extension.

        `capture_extension_debug` recorre TODOS los frames cuatro veces por
        llamada (marcador, marcadores de contenido, ping, listado de frames,
        este ultimo leyendo el innerText de cada uno) y hace tres copias
        profundas del resultado. Las automatizaciones la llaman 7-8 veces por
        corrida.

        Hasta ahora no habia ningun corte util: el unico era `if snapshot is
        None`, que no se cumple nunca, porque el evaluate tiene exito igual
        aunque no haya ninguna extension (devuelve un dict con nulos). Con el
        motor tradicional -que es el que corre de verdad- se pagaban asi
        decenas de evaluaciones de DOM por corrida para rellenar un
        diagnostico que nadie iba a mirar.

        El corte lo tenia `AutomationV2Mixin`, pero `DEFAULT_AUTOMATION_VERSION`
        es "v1", asi que no lo aplicaba nadie. Vive aqui, que es donde pasan
        las corridas reales.
        """

        if session is None:
            return None
        if not getattr(session, "extension_enabled", False):
            return None
        capture = getattr(session, "capture_extension_debug", None)
        if not callable(capture):
            return None
        return capture(**kwargs)

    def attach_run_context(self, run_context) -> None:
        self._process_run_context = run_context

    def _record_run_stat(self, event: str, **details: Any) -> None:
        run_context = getattr(self, "_process_run_context", None)
        if run_context is None:
            return
        run_context.run_stats.record(event, details or None)

    @staticmethod
    def _safe_page_url(page: Any) -> str:
        return str(getattr(page, "url", "") or "")

    def _build_common_run_stats_payload(self) -> dict[str, Any]:
        run_context = getattr(self, "_process_run_context", None)
        if run_context is None:
            return {}
        return {
            "process_id": run_context.process_id,
            "page_name": run_context.page_name,
            "slot_id": getattr(run_context, "slot_id", None),
            "action_name": run_context.action_name,
            "execution_mode": run_context.execution_mode,
            "run_stats_timeline": run_context.run_stats.export_timeline(),
            "run_stats_summary": run_context.run_stats.build_common_timing_summary(),
            "run_stats_summary_text": run_context.run_stats.build_common_timing_summary_text(),
        }

    def _get_flow_state_detector(self) -> FlowStateDetector:
        detector = getattr(self, "_flow_state_detector", None)
        if detector is None:
            detector = FlowStateDetector()
            setattr(self, "_flow_state_detector", detector)
        return detector

    def _reset_flow_state_detector_debug(self) -> None:
        setattr(
            self,
            "_flow_state_detector_debug",
            {
                "last_state": None,
                "last_confidence": None,
                "last_reason": "",
                "last_source": "",
                "snapshots_count": 0,
                "state_transitions": [],
                "first_seen_by_state": {},
                "snapshots": [],
            },
        )
        setattr(self, "_flow_state_detector_last_recorded_at", None)

    def _build_flow_state_detector_export(self) -> dict[str, Any]:
        debug_state = getattr(self, "_flow_state_detector_debug", None) or {}
        return {
            "last_state": debug_state.get("last_state"),
            "last_confidence": debug_state.get("last_confidence"),
            "last_reason": debug_state.get("last_reason"),
            "last_source": debug_state.get("last_source"),
            "snapshots_count": debug_state.get("snapshots_count", 0),
            "state_transitions": list(debug_state.get("state_transitions") or []),
            "first_seen_by_state": dict(debug_state.get("first_seen_by_state") or {}),
            "snapshots": [dict(item) for item in debug_state.get("snapshots") or []],
        }

    def _observe_flow_state(self, context, page, source: str):
        detector = self._get_flow_state_detector()
        run_context = getattr(self, "_process_run_context", None)
        process_id = getattr(run_context, "process_id", None)
        snapshot = detector.snapshot(
            site=self.site_name,
            process_id=process_id,
            context=context,
            page=page,
            source=source,
        )
        debug_state = getattr(self, "_flow_state_detector_debug", None)
        if debug_state is None:
            self._reset_flow_state_detector_debug()
            debug_state = getattr(self, "_flow_state_detector_debug")
        last_state = debug_state.get("last_state")
        now = monotonic()
        last_recorded_at = getattr(self, "_flow_state_detector_last_recorded_at", None)
        force_record = snapshot.state in {FlowStateDetector.FINAL_BUTTON_VISIBLE, FlowStateDetector.ERROR}
        state_changed = snapshot.state != last_state
        throttled = (
            last_recorded_at is not None
            and (now - float(last_recorded_at)) < self._FLOW_STATE_THROTTLE_S
            and not state_changed
            and not force_record
        )
        if throttled:
            return snapshot

        snapshot_payload = snapshot_to_dict(snapshot)
        debug_state["last_state"] = snapshot.state
        debug_state["last_confidence"] = snapshot.confidence
        debug_state["last_reason"] = snapshot.reason
        debug_state["last_source"] = snapshot.source
        debug_state["snapshots_count"] = int(debug_state.get("snapshots_count", 0)) + 1
        first_seen_by_state = dict(debug_state.get("first_seen_by_state") or {})
        first_seen_by_state.setdefault(snapshot.state, snapshot.detected_at)
        debug_state["first_seen_by_state"] = first_seen_by_state
        if state_changed and last_state is not None:
            transitions = list(debug_state.get("state_transitions") or [])
            transitions.append(
                {
                    "from": last_state,
                    "to": snapshot.state,
                    "detected_at": snapshot.detected_at,
                    "source": snapshot.source,
                }
            )
            debug_state["state_transitions"] = transitions
        snapshots = list(debug_state.get("snapshots") or [])
        snapshots.append(snapshot_payload)
        debug_state["snapshots"] = snapshots[-50:]
        setattr(self, "_flow_state_detector_last_recorded_at", now)

        record_timeline_event = getattr(self, "_record_timeline_event", None)
        if callable(record_timeline_event):
            record_timeline_event(
                "flow_detector_state",
                state=snapshot.state,
                confidence=snapshot.confidence,
                reason=snapshot.reason,
                source=snapshot.source,
                signals=asdict(snapshot.signals),
                text_preview=snapshot.text_preview,
                context_type=snapshot.context_type,
            )
        self._record_run_stat(
            "flow_detector_state",
            state=snapshot.state,
            confidence=snapshot.confidence,
            reason=snapshot.reason,
            source=snapshot.source,
            signals=asdict(snapshot.signals),
            text_preview=snapshot.text_preview,
            context_type=snapshot.context_type,
        )
        return snapshot

    def _is_cancel_requested(self) -> bool:
        run_context = getattr(self, "_process_run_context", None)
        return bool(run_context is not None and run_context.cancel_event.is_set())

    def _raise_if_cancelled(self) -> None:
        if self._is_cancel_requested():
            raise RuntimeError("Proceso cancelado por cancel_event.")

    def _build_active_flow_context(
        self,
        *,
        page,
        root,
        source: str,
        stage: str,
        text_snapshot: str | None = None,
    ) -> ActiveFlowContext:
        return ActiveFlowContext(
            page=page,
            root=root,
            source=source,
            stage=stage,
            text_snapshot=text_snapshot if text_snapshot is not None else safe_root_text(root),
        )

    def _extract_time_range(self, text: str) -> str:
        import re

        match = re.search(self._TIME_RANGE_RE, text or "", re.IGNORECASE)
        return match.group(0).strip() if match is not None else "N/A"

    def _extract_duration_text(self, text: str) -> str:
        import re

        match = re.search(self._DURATION_RE, text or "", re.IGNORECASE)
        return match.group(0).strip() if match is not None else "N/A"

    def _looks_like_duration_text(self, text: str) -> bool:
        import re

        return re.search(self._DURATION_RE, text or "", re.IGNORECASE) is not None

    def _parse_block_snapshot_details(
        self,
        pairs: dict[str, str],
        full_text: str,
        *,
        payment_aliases: tuple[str, ...],
        station_aliases: tuple[str, ...],
        schedule_aliases: tuple[str, ...],
        duration_aliases: tuple[str, ...],
        hours_aliases: tuple[str, ...] = ("horas", "hours", "hrs"),
    ) -> tuple[str, str, str, str]:
        payment = self._pick_detail_value(pairs, payment_aliases)
        station = self._pick_detail_value(pairs, station_aliases)
        schedule = self._extract_time_range(full_text) or "N/A"
        if schedule == "N/A":
            schedule = self._pick_detail_value(pairs, schedule_aliases)
        if schedule != "N/A":
            schedule = schedule.replace("(He llegado)", "").strip()
        duration = "N/A"
        for alias_group in (hours_aliases, duration_aliases):
            candidate = self._pick_detail_value(pairs, alias_group)
            if candidate != "N/A" and self._looks_like_duration_text(candidate):
                duration = candidate
                break
        if duration == "N/A":
            duration = self._extract_duration_text(full_text)
        return payment, station, schedule, duration

    # ------------------------------------------------------------------
    # Ciclo de vida de la foto reservada
    # ------------------------------------------------------------------
    #
    # Tres casos distintos, con politicas distintas:
    #
    #   1. reservada y AUN NO subida  -> release_photo + borrar la copia temporal.
    #      La foto vuelve al pool: no se gasto.
    #   2. subida (o posiblemente subida) -> consume_photo + borrar la copia temporal.
    #      Es la politica de consumo que ya existia: el sitio pudo recibirla, asi que
    #      no puede reutilizarse.
    #   3. selfie del titular -> NO es una foto del pool. Nunca llega aqui, porque
    #      reserved_photo es None en ese camino.
    #
    # La limpieza corre exactamente una vez por photo_id (exito, error, timeout o
    # cancelacion) y nunca lanza: una excepcion aqui no puede sustituir al error
    # original, pero si deja un evento de diagnostico.

    # Cuanto se espera a que el worker de reserva en segundo plano termine antes de
    # dar por buena la decision de "no hay nada que liberar". Sin esta espera, una
    # salida rapida (p. ej. no_block a ~1,5 s) dejaba la reserva huerfana: el worker
    # la creaba despues de que el flujo ya hubiera decidido que no habia nada.
    BACKGROUND_PHOTO_SETTLE_TIMEOUT_S = 20.0

    def _photo_cleanup_registry(self) -> set[str]:
        registry = getattr(self, "_photo_cleanup_done_ids", None)
        if registry is None:
            registry = set()
            setattr(self, "_photo_cleanup_done_ids", registry)
        return registry

    def _reset_photo_cleanup_registry(self) -> None:
        setattr(self, "_photo_cleanup_done_ids", set())

    def _record_photo_cleanup_warning(self, action: str, photo_id: str, exc: Exception) -> None:
        record_event = getattr(self, "_record_timeline_event", None)
        if callable(record_event):
            with suppress(Exception):
                record_event(
                    "photo_cleanup_failed",
                    action=action,
                    photo_id=photo_id,
                    error=type(exc).__name__,
                )
        record_stat = getattr(self, "_record_run_stat", None)
        if callable(record_stat):
            with suppress(Exception):
                record_stat(
                    "photo_cleanup_failed",
                    action=action,
                    photo_id=photo_id,
                    error=type(exc).__name__,
                )

    def _cleanup_reserved_photo(
        self,
        reserved_photo,
        *,
        uploaded: bool,
        progress_callback=None,
    ) -> None:
        """Cierra la reserva segun si la foto pudo haber llegado al sitio.

        Idempotente por photo_id y sin propagar excepciones.
        """

        if reserved_photo is None:
            return
        photo_id = getattr(reserved_photo, "photo_id", None)
        if not photo_id:
            return
        registry = self._photo_cleanup_registry()
        if photo_id in registry:
            return
        registry.add(photo_id)

        action = "consume" if uploaded else "release"
        try:
            if uploaded:
                self._photo_service.consume_photo(photo_id)
            else:
                self._photo_service.release_photo(photo_id)
        except Exception as exc:  # noqa: BLE001 - nunca sustituye al error original
            self._record_photo_cleanup_warning(action, photo_id, exc)
            self.emit_progress(
                progress_callback,
                phase="photo_upload",
                message=(
                    f"No se pudo {'consumir' if uploaded else 'liberar'} la foto reservada "
                    f"({type(exc).__name__}). Quedara pendiente de limpieza."
                ),
            )
        try:
            self._photo_service.delete_local_copy(getattr(reserved_photo, "local_path", ""))
        except Exception as exc:  # noqa: BLE001
            self._record_photo_cleanup_warning("delete_local_copy", photo_id, exc)

    def _settle_background_photo(self, preparation):
        """Espera de forma acotada a que el worker de reserva termine.

        Devuelve la foto reservada si el worker llego a crearla. Resuelve la carrera
        en la que el flujo abandona la preparacion mientras reserve_photo sigue en
        vuelo: sin esto la reserva quedaba RESERVED para siempre.
        """

        if preparation is None or getattr(preparation, "consumed", False):
            return None
        ready_event = getattr(preparation, "ready_event", None)
        if ready_event is not None and not ready_event.is_set():
            with suppress(Exception):
                ready_event.wait(timeout=self.BACKGROUND_PHOTO_SETTLE_TIMEOUT_S)
        return getattr(preparation, "reserved_photo", None)

    # ------------------------------------------------------------------
    # Un unico despacho del click final
    # ------------------------------------------------------------------

    def _final_click_done_recorded(self) -> bool:
        timings = getattr(self, "_timing_first_by_event", None)
        return bool(timings) and "final_click_done" in timings

    def _mark_final_submit_clicked(self, *, clicked_at: float | None = None) -> None:
        """Registra que el click final ya se despacho. Irreversible en la corrida."""

        from time import monotonic as _monotonic

        setattr(self, "_final_submit_already_clicked", True)
        setattr(
            self,
            "_final_submit_fast_clicked_at",
            clicked_at if clicked_at is not None else _monotonic(),
        )

    def _final_submit_resolved(self) -> bool:
        """True en cuanto se despacho (o se intento despachar) el click final."""

        return bool(getattr(self, "_final_submit_already_clicked", False)) or self._final_click_done_recorded()


    # JS que mira QUE hay encima del centro de un elemento y lo neutraliza.
    # Sube hasta el contenedor flotante real, porque los chats suelen ser un
    # iframe dentro de un div con position:fixed, y ocultar solo el iframe deja
    # el div capturando los clicks igual.
    _JS_APARTAR_ESTORBO = r"""(el) => {
        const r = el.getBoundingClientRect();
        if (!r.width || !r.height) return null;
        const x = r.left + r.width / 2;
        const y = r.top + r.height / 2;
        const encima = document.elementFromPoint(x, y);
        if (!encima || encima === el || el.contains(encima) || encima.contains(el)) {
            return null;
        }
        let nodo = encima;
        for (let i = 0; i < 6 && nodo && nodo !== document.body; i++) {
            const pos = getComputedStyle(nodo).position;
            if (pos === 'fixed' || pos === 'sticky') break;
            nodo = nodo.parentElement;
        }
        const objetivo = (nodo && nodo !== document.body) ? nodo : encima;
        const clases = typeof objetivo.className === 'string'
            ? objetivo.className.trim().split(/\s+/).slice(0, 2).join('.')
            : '';
        const descripcion = objetivo.tagName.toLowerCase()
            + (objetivo.id ? '#' + objetivo.id : '')
            + (clases ? '.' + clases : '');
        objetivo.style.setProperty('pointer-events', 'none', 'important');
        objetivo.style.setProperty('visibility', 'hidden', 'important');
        return descripcion;
    }"""

    def _apartar_lo_que_tape(self, locator: Locator) -> str | None:
        """Oculta lo que este cubriendo el centro del elemento. Nunca lanza.

        El caso real: el chat del sitio recibe un mensaje, su burbuja crece y
        tapa el boton Continuar. El click normal falla -Playwright comprueba
        que el elemento reciba el puntero- y la escalada a force=True disparaba
        en esas coordenadas, o sea EN EL CHAT: se abria el chat y la corrida se
        quedaba ahi.

        Se usa visibility+pointer-events y no display:none a proposito: asi el
        estorbo deja de recibir clicks pero no se recoloca la pagina, y el
        boton sigue donde estaba.
        """

        try:
            return locator.evaluate(self._JS_APARTAR_ESTORBO)
        except Exception:  # noqa: BLE001 - apartar es un extra, nunca un bloqueo
            return None

    # ------------------------------------------------------------------
    # Selector "Cuenta prestada" / "Cuenta propia"
    # ------------------------------------------------------------------
    #
    # Aparece en dos sitios: en el panel de Paripe nada mas entrar, y en el
    # iframe de Compinche/Ready4Drive al pulsar "He llegado". El proceso solo
    # va bien con "Cuenta prestada".
    #
    # La regla de este bloque es la carga de la prueba: SOLO se pulsa cuando
    # hay prueba positiva de que el selector esta en "Cuenta propia". No basta
    # con "no parece estar en prestada". La version anterior hacia justo eso
    # -si no veia senales, daba por hecho propia y pulsaba- y asi se puede
    # voltear un selector que ya estaba bien, que es el peor resultado
    # posible: la corrida falla por culpa del arreglo. Cuando no se sabe, no
    # se toca, y se guarda una radiografia del control en el log para poder
    # decidirlo despues con datos en vez de con suposiciones.
    #
    # Hay DOS controles distintos segun el sitio:
    #
    # - Compinche/Ready4Drive, dentro del iframe: un `role="radiogroup"` de
    #   Headless UI con dos `role="radio"`. El elegido lleva
    #   `aria-checked="true"` y `data-checked` (vacio). Ojo con
    #   `aria-label="borrowed-account"`: esta en LAS DOS opciones, es el
    #   nombre del grupo y no distingue nada. Lo que distingue es el texto.
    # - Paripe, en el panel: un `role="switch"` con una etiqueta a cada lado.
    #   Ahi `aria-checked` del switch aparece INVERTIDO respecto a lo que se
    #   ve, asi que no decide nada: se miran las dos etiquetas y se exige que
    #   una, y solo una, de senales de estar activa.

    _CUENTA_PRESTADA_RE = r"cuenta\s+prestada|borrowed\s+account|conta\s+emprestada"
    _CUENTA_PROPIA_RE = r"cuenta\s+propia|own\s+account|personal\s+account|conta\s+pr[oó]pria"

    _JS_ESTADO_DE_CUENTA = r"""([rePrestada, rePropia]) => {
        const prestada = new RegExp(rePrestada, 'i');
        const propia = new RegExp(rePropia, 'i');
        const texto = (e) => (((e && e.textContent) || '')).replace(/\s+/g, ' ').trim();
        const cajas = [...document.querySelectorAll('div, section, fieldset')]
            .filter((d) => prestada.test(texto(d)) && propia.test(texto(d)));
        if (!cajas.length) return { encontrado: false, motivo: 'sin_caja' };
        // La mas interna: la que menos descendientes tiene sigue conteniendo
        // las dos etiquetas y el control, sin arrastrar media pagina.
        const masInterno = (lista) => {
            if (!lista.length) return null;
            const copia = [...lista];
            copia.sort((a, b) => a.querySelectorAll('*').length - b.querySelectorAll('*').length);
            return copia[0];
        };
        const caja = masInterno(cajas);
        // El checkbox "Permitirme subir una selfie del propietario" vive en
        // este mismo modal en Compinche. NO es el selector de cuenta, y
        // pulsarlo activaria una opcion que el agente no pidio. Se mira solo
        // su entorno inmediato: subir hasta el primer `div` traia la caja
        // entera y descartaba tambien el control bueno.
        const ambas = (t) => prestada.test(t) && propia.test(t);
        // El entorno propio del control: se sube mientras el ancestro siga
        // hablando de UN solo lado. En cuanto aparecen los dos textos ya es
        // la caja compartida, y su texto no dice nada de este control.
        const entorno = (e) => {
            let n = e;
            let mejor = e;
            while (n && n !== caja) {
                if (ambas(texto(n))) break;
                mejor = n;
                n = n.parentElement;
            }
            return mejor;
        };
        const vecinos = (e) => [e.previousElementSibling, e.nextElementSibling]
            .map((v) => (v && !ambas(texto(v)) ? texto(v) : ''))
            .join(' ');
        const esDelPropietario = (e) => {
            const cerca = entorno(e);
            const etiquetas = [e.getAttribute('aria-label'), e.getAttribute('name'), e.id]
                .filter(Boolean).join(' ');
            return /propietario|owner\s*selfie|titular/i.test(
                etiquetas + ' ' + texto(cerca) + ' ' + vecinos(cerca)
            );
        };
        const interruptor = [...caja.querySelectorAll('[role="switch"], input[type="checkbox"]')]
            .find((c) => !esDelPropietario(c)) || null;
        const candidatos = [...caja.querySelectorAll('button, label, [role="radio"], span, div')];
        const senales = (e) => {
            if (!e) return null;
            const clases = typeof e.className === 'string' ? e.className : '';
            return {
                tag: e.tagName,
                rol: e.getAttribute('role'),
                aria: e.getAttribute('aria-checked'),
                data: e.hasAttribute('data-checked') ? (e.getAttribute('data-checked') || '') : null,
                off: Boolean(e.disabled) || e.getAttribute('aria-disabled') === 'true',
                acento: /text-primary|font-semibold|font-bold|bg-primary/.test(clases),
                clases: clases.slice(0, 120),
                texto: texto(e).slice(0, 50),
            };
        };
        // Tri-estado a proposito: true, false o null ("no se sabe"). Null no
        // es false: confundirlos es lo que hacia pulsar a ciegas.
        const activo = (s) => {
            if (!s) return null;
            if (s.aria === 'true' || s.data !== null) return true;
            if (s.aria === 'false') return false;
            if (s.off || s.acento) return true;
            return null;
        };
        // De todos los elementos que hablan de un solo lado se elige el que
        // LLEVA la senal, no el mas interno. En el panel real la etiqueta es
        // un <span> sin nada dentro de un <button disabled> con la clase de
        // acento: quedarse con el span mas interno es quedarse justo con el
        // unico trozo que no dice nada.
        const elegir = (lista) => {
            if (!lista.length) return null;
            return lista.find((e) => activo(senales(e)) !== null) || masInterno(lista);
        };
        const ladoPrestada = elegir(
            candidatos.filter((b) => prestada.test(texto(b)) && !propia.test(texto(b)))
        );
        const ladoPropia = elegir(
            candidatos.filter((b) => propia.test(texto(b)) && !prestada.test(texto(b)))
        );
        const sPrestada = senales(ladoPrestada);
        const sPropia = senales(ladoPropia);
        const p = activo(sPrestada);
        const q = activo(sPropia);
        let estado = null;
        if (p === true && q !== true) estado = true;
        else if (q === true && p !== true) estado = false;
        else if (p === false && q === null) estado = false;
        else if (q === false && p === null) estado = true;
        return {
            encontrado: Boolean(ladoPrestada || ladoPropia),
            motivo: (ladoPrestada || ladoPropia) ? null : 'sin_lados',
            prestada: estado,
            aria: interruptor ? interruptor.getAttribute('aria-checked') : null,
            radiografia: {
                prestada: sPrestada,
                propia: sPropia,
                sw: senales(interruptor),
            },
        };
    }"""

    # Cuanto se espera a que el control refleje el cambio tras pulsarlo.
    CUENTA_SWITCH_TIMEOUT_MS = 2_500
    # Cuanto se espera a poder LEER el estado antes de decidir nada. El panel
    # de Paripe se pinta justo despues de entrar: si se mira demasiado pronto
    # las dos etiquetas estan ahi pero todavia sin deshabilitar ni pintar, y
    # entonces no hay forma de saber cual esta activa. Esperar a que el sitio
    # termine es la diferencia entre leer bien y pulsar a ciegas.
    CUENTA_LECTURA_TIMEOUT_MS = 3_000
    # Y cuanto se espera cuando NO hay ni rastro del selector. Tiene que ser
    # corto: este paso esta en el camino del boton de verificacion, y gastar
    # ahi el presupuesto largo retrasa el click varios segundos en pantallas
    # donde el selector sencillamente no existe, que son la mayoria.
    CUENTA_BUSQUEDA_TIMEOUT_MS = 300

    def _leer_estado_de_cuenta(self, root) -> dict:
        """En que lado esta el selector de cuenta. Nunca lanza.

        `prestada` es tri-estado: True, False o None cuando no se pudo
        determinar. Quien llame NO debe tratar None como False.
        """

        opcion = self._opcion_prestada_de_radiogrupo(root)
        if opcion is not None:
            aria = None
            with suppress(Exception):
                aria = opcion.get_attribute("aria-checked")
            return {
                "encontrado": True,
                "prestada": self._radio_esta_marcado(opcion),
                "aria": aria,
                "modo": "radio",
            }
        try:
            estado = root.evaluate(
                self._JS_ESTADO_DE_CUENTA,
                [self._CUENTA_PRESTADA_RE, self._CUENTA_PROPIA_RE],
            )
        except Exception as exc:  # noqa: BLE001 - si no se puede mirar, no hay paso que dar
            return {
                "encontrado": False,
                "motivo": f"error:{type(exc).__name__}",
                "modo": "switch",
            }
        if not isinstance(estado, dict):
            return {"encontrado": False, "motivo": "sin_respuesta", "modo": "switch"}
        estado["modo"] = "switch"
        return estado

    def _opcion_prestada_de_radiogrupo(self, root):
        """La tarjeta "Cuenta prestada" de un grupo de radios, o None."""

        import re as _re

        with suppress(Exception):
            opcion = (
                root.locator('[role="radio"]')
                .filter(has_text=_re.compile(self._CUENTA_PRESTADA_RE, _re.I))
                .first
            )
            if opcion.count() > 0:
                return opcion
        return None

    @staticmethod
    def _radio_esta_marcado(opcion):
        """True, False o None si no se pudo saber. None NO es False."""

        with suppress(Exception):
            # Headless UI lo pone vacio (`data-checked=""`), asi que vale con
            # que exista: comparar contra "true" daria siempre falso.
            if opcion.get_attribute("data-checked") is not None:
                return True
        aria = None
        with suppress(Exception):
            aria = opcion.get_attribute("aria-checked")
        if aria == "true":
            return True
        if aria == "false":
            return False
        return None

    def _esperar_estado_de_cuenta(self, root, *, busqueda_ms: int | None = None) -> dict:
        """Lee el selector hasta poder decir en que lado esta, o se rinde.

        Devuelve la primera lectura concluyente; si no la hay, la ultima que
        consiguio, para que quede en el log tal cual se vio.
        """

        ahora = monotonic()
        # Dos presupuestos: uno corto para encontrarlo y otro largo para
        # leerlo. Mientras no aparezca se espera poco, porque lo normal es
        # que no este; en cuanto aparece se le da tiempo a terminar de
        # pintarse, que es cuando merece la pena esperar.
        if busqueda_ms is None:
            busqueda_ms = self.CUENTA_BUSQUEDA_TIMEOUT_MS
        limite = ahora + busqueda_ms / 1000
        largo = ahora + self.CUENTA_LECTURA_TIMEOUT_MS / 1000
        ultimo: dict = {"encontrado": False, "motivo": "sin_lectura"}
        while True:
            ultimo = self._leer_estado_de_cuenta(root)
            if ultimo.get("encontrado"):
                if ultimo.get("prestada") is not None:
                    return ultimo
                limite = largo
            if monotonic() >= limite:
                return ultimo
            with suppress(Exception):
                root.wait_for_timeout(150)

    def _asegurar_cuenta_prestada(
        self, root, *, progress_callback=None, busqueda_ms: int | None = None
    ) -> str:
        """Intenta dejar el selector en 'Cuenta prestada'. NUNCA lanza.

        Respuestas: "ausente" (no hay selector en esta pantalla, que es lo
        normal en la mayoria de pasos), "ya_estaba", "indeterminado" (esta,
        pero no se pudo leer en que lado), "cambiado" y "no_confirmado".

        Lo importante es lo que NO hace: no tumba la corrida. La primera
        version lanzaba si no conseguia confirmar el cambio, y eso convirtio
        en fallo seguro un flujo que antes funcionaba sin tocar el selector.
        Un paso de conveniencia no puede ser la causa de que una corrida
        muera: si no se puede confirmar, se avisa, se deja anotado que leyo y
        el flujo sigue. Si de verdad hacia falta la cuenta prestada, el sitio
        lo dira mas adelante con su propio error, que es informacion real; si
        la lectura estaba equivocada, la corrida se salva.
        """

        estado = self._esperar_estado_de_cuenta(root, busqueda_ms=busqueda_ms)
        if not estado.get("encontrado"):
            # Se anota aunque no haya nada: distinguir "no hay selector en esta
            # pantalla" de "lo hay y no lo vi" es justo lo que hace falta para
            # diagnosticar, y desde fuera las dos se parecen al silencio.
            self._anotar("cuenta_selector_ausente", **self._detalles(estado))
            return "ausente"
        marcado = estado.get("prestada")
        if marcado is True:
            self._record_run_stat("cuenta_prestada_ya_activa", **self._detalles(estado))
            return "ya_estaba"
        if marcado is None:
            # No se sabe en que lado esta. No se toca: pulsar a ciegas puede
            # voltear un selector que ya estaba en prestada y tumbar una
            # corrida que iba bien. Queda la radiografia en el log.
            self._anotar("cuenta_estado_indeterminado", **self._detalles(estado))
            self.emit_progress(
                progress_callback,
                phase="account_selection",
                message=(
                    "No se pudo leer en que lado esta el selector de cuenta."
                    " Se deja como esta para no empeorarlo."
                ),
            )
            return "indeterminado"

        self._anotar("cuenta_en_propia_detectada", **self._detalles(estado))
        self.emit_progress(
            progress_callback,
            phase="account_selection",
            message="El selector parece estar en 'Cuenta propia'. Cambiando a 'Cuenta prestada'...",
        )
        control = self._localizar_control_de_cuenta(root)
        if control is None:
            self._anotar("cuenta_sin_control", **self._detalles(estado))
            self.emit_progress(
                progress_callback,
                phase="account_selection",
                message=(
                    "No se encontro el control para cambiar la cuenta. Se sigue"
                    " sin tocarlo."
                ),
            )
            return "no_confirmado"

        with suppress(Exception):
            self._click_locator_resilient(
                control,
                phase="account_selection",
                error_message="No se pudo pulsar el control de cuenta prestada/propia.",
            )

        limite = monotonic() + self.CUENTA_SWITCH_TIMEOUT_MS / 1000
        ultimo = estado
        while monotonic() < limite:
            ultimo = self._leer_estado_de_cuenta(root)
            if ultimo.get("prestada") is True:
                self._anotar("cuenta_prestada_activada", **self._detalles(ultimo))
                self.emit_progress(
                    progress_callback,
                    phase="account_selection",
                    message="Selector puesto en 'Cuenta prestada'.",
                )
                return "cambiado"
            with suppress(Exception):
                root.wait_for_timeout(100)

        # No se pudo confirmar. Se anota TODO lo que se leyo -antes y despues-
        # porque la causa mas probable es que la lectura del estado este
        # equivocada para esta pantalla, y sin esos datos no hay forma de
        # saberlo desde fuera.
        self._anotar(
            "cuenta_prestada_no_confirmada",
            antes=self._detalles(estado),
            despues=self._detalles(ultimo),
        )
        self.emit_progress(
            progress_callback,
            phase="account_selection",
            message=(
                "No se pudo confirmar que el selector quedara en 'Cuenta"
                " prestada'. La corrida sigue: si el sitio lo necesita, lo dira."
            ),
        )
        return "no_confirmado"

    @staticmethod
    def _detalles(estado: dict) -> dict:
        """Lo que se leyo del selector, para el log. Sin el no hay diagnostico."""

        radiografia = estado.get("radiografia")
        if radiografia is not None and not isinstance(radiografia, str):
            radiografia = _a_texto_corto(radiografia)
        return {
            "modo": estado.get("modo"),
            "prestada": estado.get("prestada"),
            "aria": estado.get("aria"),
            "encontrado": estado.get("encontrado"),
            "motivo": estado.get("motivo"),
            "radiografia": radiografia,
        }

    def _anotar(self, evento: str, **detalles) -> None:
        """Deja el evento en la linea de tiempo y en las estadisticas."""

        registrar = getattr(self, "_record_timeline_event", None)
        if callable(registrar):
            with suppress(Exception):
                registrar(evento, **detalles)
        with suppress(Exception):
            self._record_run_stat(evento, **detalles)

    def _localizar_control_de_cuenta(self, root):
        """Lo que hay que pulsar para quedarse en "Cuenta prestada".

        En un grupo de radios es la tarjeta misma; en un switch, el switch.
        """

        import re as _re

        opcion = self._opcion_prestada_de_radiogrupo(root)
        if opcion is not None:
            return opcion

        with suppress(Exception):
            caja = (
                root.locator("div")
                .filter(has_text=_re.compile(self._CUENTA_PRESTADA_RE, _re.I))
                .filter(has_text=_re.compile(self._CUENTA_PROPIA_RE, _re.I))
                .last
            )
            interruptor = (
                caja.locator('[role="switch"], input[type="checkbox"]')
                # Mismo motivo que en el JS: el checkbox de la selfie del
                # propietario esta en el mismo modal y no es este control.
                .filter(has_not_text=_re.compile("propietario|titular|owner", _re.I))
                .first
            )
            if interruptor.count() > 0:
                return interruptor
        with suppress(Exception):
            suelto = root.locator('[role="switch"]').first
            if suelto.count() > 0:
                return suelto
        return None

    def _dispatch_final_click_once(self, button, *, progress_callback=None) -> Exception | None:
        """Despacha el click final exactamente una vez.

        Devuelve la excepcion si Playwright no lo confirmo, y NUNCA reintenta: un
        timeout no prueba que el click no llegara al sitio, y force=True, press() o
        evaluate("node.click()") habrian activado el boton una segunda vez.
        """

        try:
            button.click(timeout=self.FINAL_CLICK_DISPATCH_TIMEOUT_MS)
        except Exception as exc:  # noqa: BLE001 - puede haber llegado igualmente
            self.emit_progress(
                progress_callback,
                phase="final_submit",
                message=(
                    "El click final se despacho pero Playwright no lo confirmo "
                    f"({type(exc).__name__}). No se reintenta: se verifica el resultado."
                ),
            )
            return exc
        return None

    # Presupuesto para despachar el click final. Se mide una sola vez: si expira,
    # NO se reintenta, porque el click puede haber llegado al sitio igualmente.
    FINAL_CLICK_DISPATCH_TIMEOUT_MS = 2_000
    # Presupuesto para esperar a que el boton final quede visible/habilitado. Esta
    # espera SI es reintentable: ocurre antes de enviar nada al sitio.
    FINAL_CLICK_READY_TIMEOUT_MS = 1_500

    def _try_fast_click_final_from_flow_context(
        self,
        page,
        context,
        progress_callback: ProgressCallback | None,
        *,
        source: str,
    ) -> bool:
        if context is None:
            return False
        if not hasattr(context, "locator"):
            return False
        page_url = self._safe_page_url(page)
        looks_like_body = getattr(self, "_looks_like_body_context", None)
        if callable(looks_like_body) and looks_like_body(context):
            self.emit_progress(progress_callback, phase="block_read", message="dashboard/body descartado como contexto principal")
            return False
        find_button = getattr(self, "_find_final_submit_button", None)
        if not callable(find_button):
            return False
        try:
            button = find_button(context, page=page)
        except TypeError:
            button = find_button(context)
        if button is None:
            return False
        context_has_block_details = getattr(self, "_context_has_block_details", None)
        if callable(context_has_block_details) and not context_has_block_details(context):
            return False
        capture_snapshot = getattr(self, "_capture_block_snapshot_text", None)
        snapshot_text = capture_snapshot(context, page) if callable(capture_snapshot) else safe_root_text(context)
        setattr(self, "_latest_block_snapshot_text", snapshot_text)
        set_active_flow_context = getattr(self, "_set_active_flow_context", None)
        if callable(set_active_flow_context):
            set_active_flow_context(context, page=page, source=source)
        remember_candidate = getattr(self, "_remember_final_button_candidate", None)
        if callable(remember_candidate):
            remember_candidate(context=context, button=button, page=page, source=source)
        self._mark_phase_timing("block_visual_detected", source=source, url=page_url)
        self._record_run_stat("block_visual_detected", source=source, url=page_url)
        self.emit_progress(progress_callback, phase="final_submit", message="bloque detectado por boton final: click inmediato")
        self._mark_phase_timing("final_click_started", source=source, url=page_url)
        self._record_run_stat("final_click_started", source=source, url=page_url)

        # UNA SOLA ACTIVACION POR CORRIDA.
        #
        # El flag se marca ANTES de despachar, no despues: un timeout de Playwright
        # no prueba que el click no llegara al sitio. El patron anterior
        # (click -> click(force=True) -> evaluate("node.click()")) podia enviar el
        # bloque tres veces cuando el primer click si llego pero la comprobacion
        # post-click expiro por una navegacion o un detach del iframe.
        from time import monotonic

        dispatch_at = monotonic()
        setattr(self, "_final_submit_already_clicked", True)
        setattr(self, "_final_submit_fast_clicked_at", dispatch_at)
        mark_clicked = getattr(self, "_mark_final_submit_clicked", None)
        if callable(mark_clicked):
            mark_clicked(clicked_at=dispatch_at)

        dispatch_error: Exception | None = None
        try:
            button.click(timeout=self.FINAL_CLICK_DISPATCH_TIMEOUT_MS)
        except Exception as exc:  # noqa: BLE001 - puede haber llegado igualmente
            dispatch_error = exc

        self._mark_phase_timing(
            "final_click_done",
            source=source,
            url=page_url,
            dispatch_error=type(dispatch_error).__name__ if dispatch_error is not None else None,
        )
        self._record_run_stat(
            "final_click_done",
            source=source,
            url=page_url,
            dispatch_error=type(dispatch_error).__name__ if dispatch_error is not None else None,
        )
        if dispatch_error is None:
            self.emit_progress(
                progress_callback,
                phase="final_submit",
                message="boton final presionado directamente desde contexto activo",
            )
        else:
            # No se reintenta: se deja que la deteccion de resultado decida.
            self.emit_progress(
                progress_callback,
                phase="final_submit",
                message=(
                    "El click final se despacho pero Playwright no lo confirmo "
                    f"({type(dispatch_error).__name__}). No se reintenta: se verifica el resultado."
                ),
            )
        return True

    @abstractmethod
    def execute(
        self,
        request: ProcessExecutionRequest,
        *,
        local_config: LocalConfig,
        progress_callback: ProgressCallback | None = None,
    ) -> SiteExecutionResult:
        raise NotImplementedError

    @staticmethod
    def emit_progress(
        progress_callback: ProgressCallback | None,
        *,
        phase: str,
        message: str,
    ) -> None:
        if progress_callback is not None:
            progress_callback(phase, message)
