from __future__ import annotations

import json
import logging
from contextlib import suppress
import os
import platform
import queue
import threading
import unicodedata
from collections.abc import Callable
from collections import OrderedDict
from datetime import datetime, timezone
from time import monotonic

try:
    import psutil
except Exception:  # noqa: BLE001 - sin psutil solo se pierde la medicion
    psutil = None  # type: ignore[assignment]

from automation.browser_manager import BrowserManager, sesiones_vivas_en_memoria
from automation.compinche_site import CompincheSite
from automation.engine_router import FlowEngineRouter
from automation.engines.common import RegisteredSiteRunner
from automation.paripe_site import ParipeSite
from automation.ready4drive_site import Ready4DriveSite
from automation.v2 import (
    CompincheSiteV2,
    ParipeSiteV2,
    Ready4DriveSiteV2,
    normalize_automation_version,
)
from core.models import ProcessExecutionRequest, ProcessExecutionResult, SiteExecutionResult
from core.validators import sanitize_phone_number
from services.last_result_service import LastResultService
from services.local_config_service import LocalConfigService
from services.log_service import LogService
from services.photo_source_tracker import (
    clear_photo_source_counts,
    get_photo_source_summary,
    reset_photo_source_counts,
)
from services.process_run_context import ProcessRunContext


_LOGGER = logging.getLogger(__name__)


class ProcessService:
    _LOG_UPDATE_MIN_INTERVAL_SECONDS = 0.5
    # Intervalo para las fases importantes en v2. Mas corto que el general
    # seria inutil; mas largo perderia el detalle de las fases criticas.
    _V2_IMPORTANT_LOG_MIN_INTERVAL_SECONDS = 1.0
    _LOG_DRAIN_TIMEOUT_SECONDS = 20.0
    _MAX_PROCESS_DEBUG_EXPORTS = 50
    _MAX_SLOT_DEBUG_EXPORTS = 50
    _IMPORTANT_LOG_PHASES = {
        "login",
        "selfie_stage",
        "photo_upload",
        "block_read",
        "final_submit",
        "final_result",
        "unexpected",
        "finished",
    }
    _ACTION_CANONICAL_NAMES = {
        "he llegado instantaneas": "He llegado instantáneo",
        "he llegado instantaneo": "He llegado instantáneo",
    }

    def __init__(
        self,
        log_service: LogService | None = None,
        log_service_factory: Callable[[], LogService] | None = None,
        local_config_service: LocalConfigService | None = None,
        compinche_site: CompincheSite | None = None,
        paripe_site: ParipeSite | None = None,
        ready4drive_site: Ready4DriveSite | None = None,
        last_result_service: LastResultService | None = None,
        engine_router: FlowEngineRouter | None = None,
    ) -> None:
        self._log_service = log_service or LogService()
        self._run_log_service_factory = log_service_factory or LogService
        self._local_config_service = local_config_service or LocalConfigService()
        self._last_result_service = last_result_service or LastResultService()
        self._engine_router = engine_router or FlowEngineRouter()
        self._site_runner_factories = {
            "Compinche": self._build_registered_site_runner_factory(
                site_label="Compinche",
                site_host="compinche.io",
                runner_template=compinche_site,
                runner_factory=CompincheSite,
            ),
            "Paripe": self._build_registered_site_runner_factory(
                site_label="Paripe",
                site_host="paripe.io",
                runner_template=paripe_site,
                runner_factory=ParipeSite,
            ),
            "Ready4Drive": self._build_registered_site_runner_factory(
                site_label="Ready4Drive",
                site_host="ready4drive.com",
                runner_template=ready4drive_site,
                runner_factory=Ready4DriveSite,
            ),
        }
        # Registro paralelo de las automatizaciones v2. Mismo contrato, misma
        # forma: lo unico que cambia es la clase. Los runners inyectados por
        # constructor son siempre v1, asi que la v2 se construye fresca.
        self._site_runner_factories_v2 = {
            "Compinche": self._build_registered_site_runner_factory(
                site_label="Compinche",
                site_host="compinche.io",
                runner_template=None,
                runner_factory=CompincheSiteV2,
            ),
            "Paripe": self._build_registered_site_runner_factory(
                site_label="Paripe",
                site_host="paripe.io",
                runner_template=None,
                runner_factory=ParipeSiteV2,
            ),
            "Ready4Drive": self._build_registered_site_runner_factory(
                site_label="Ready4Drive",
                site_host="ready4drive.com",
                runner_template=None,
                runner_factory=Ready4DriveSiteV2,
            ),
        }
        self._process_debug_exports: OrderedDict[str, dict] = OrderedDict()
        self._slot_debug_exports: OrderedDict[str, dict] = OrderedDict()
        self._process_slot_map: dict[str, str] = {}
        self._process_debug_lock = threading.Lock()
        # Run contexts of the runs currently in flight, keyed by their worker thread.
        # A run occupies exactly one thread, so the key is stable and the entry is
        # always removed by that same thread's finally block.
        self._active_runs: dict[int, ProcessRunContext] = {}
        self._active_runs_lock = threading.Lock()
        self._closing = threading.Event()

    def begin_shutdown(self) -> int:
        """Stop accepting new runs and ask every in-flight run to cancel.

        Returns how many runs were asked to stop. This only *requests* the stop:
        each run notices its cancel_event at the next checkpoint and then closes its
        own browser session on its own thread, which is what Playwright's sync API
        requires. The caller must wait for those threads before tearing anything down.
        """

        self._closing.set()
        with self._active_runs_lock:
            contexts = list(self._active_runs.values())
        for context in contexts:
            context.cancel_event.set()
        return len(contexts)

    def active_run_count(self) -> int:
        with self._active_runs_lock:
            return len(self._active_runs)

    def is_closing(self) -> bool:
        return self._closing.is_set()

    def _register_active_run(self, run_context: ProcessRunContext) -> None:
        with self._active_runs_lock:
            self._active_runs[threading.get_ident()] = run_context

    def request_cancel(self, slot_id: str) -> int:
        """Pide a la corrida de un panel que se detenga. Devuelve cuantas lo recibieron.

        Solo SENALIZA: la corrida lo nota en su siguiente punto de control
        (base_site._raise_if_cancelled) y cierra su propia sesion de navegador
        en su propio hilo, que es lo que la API sync de Playwright exige.

        Es por panel a proposito: detener el Proceso 1 no puede tocar al 2.
        """

        normalized = str(slot_id or "").strip()
        if not normalized:
            return 0
        notified = 0
        with self._active_runs_lock:
            contexts = list(self._active_runs.values())
        for context in contexts:
            if str(getattr(context, "slot_id", "") or "").strip() != normalized:
                continue
            context.cancel_event.set()
            notified += 1
        return notified

    def is_cancel_requested(self, slot_id: str) -> bool:
        normalized = str(slot_id or "").strip()
        with self._active_runs_lock:
            contexts = list(self._active_runs.values())
        return any(
            str(getattr(context, "slot_id", "") or "").strip() == normalized
            and context.cancel_event.is_set()
            for context in contexts
        )

    def shutdown(self) -> None:
        """Last-resort teardown of anything still open.

        Call this only after the run threads have been joined: each run closes its
        own session in its finally block, and yanking Playwright out from under a
        live run makes that cleanup fail.
        """

        self._closing.set()
        BrowserManager.shutdown_all()

    def register_process_slot(self, process_id: str | None, slot_id: str | None) -> None:
        if not process_id or not slot_id:
            return
        with self._process_debug_lock:
            self._process_slot_map[process_id] = slot_id

    def get_process_debug_export(self, process_id: str | None, *, slot_id: str | None = None) -> dict:
        if not process_id and not slot_id:
            return {}
        with self._process_debug_lock:
            if process_id and process_id in self._process_debug_exports:
                return dict(self._process_debug_exports.get(process_id) or {})
            resolved_slot_id = slot_id or (self._process_slot_map.get(process_id) if process_id else None)
            if resolved_slot_id:
                return dict(self._slot_debug_exports.get(resolved_slot_id) or {})
            return {}

    def execute(
        self,
        request: ProcessExecutionRequest,
        *,
        progress_callback: Callable[[str, str], None] | None = None,
    ) -> ProcessExecutionResult:
        if self._closing.is_set():
            raise RuntimeError(
                "La aplicacion se esta cerrando: no se aceptan procesos nuevos."
            )
        # _execute_run genera un process_id de respaldo cuando la peticion no
        # trae uno, y TODO el flujo (incluido record_photo_source) usa ese. Hay
        # que purgar ese mismo id, no el original: purgar el original dejaba un
        # Counter huerfano por cada corrida sin process_id.
        resolved_process_id: list[str | None] = [getattr(request, "process_id", None)]
        try:
            return self._execute_run(
                request,
                progress_callback=progress_callback,
                resolved_process_id=resolved_process_id,
            )
        finally:
            with self._active_runs_lock:
                self._active_runs.pop(threading.get_ident(), None)
            clear_photo_source_counts(resolved_process_id[0])

    def _execute_run(
        self,
        request: ProcessExecutionRequest,
        *,
        progress_callback: Callable[[str, str], None] | None = None,
        resolved_process_id: list[str | None] | None = None,
    ) -> ProcessExecutionResult:
        sanitized_phone = sanitize_phone_number(request.phone_number)
        local_config = self._local_config_service.load()
        canonical_action_name = self._canonicalize_action_name(request.action_name)
        resolved_engine = self._resolve_execution_mode(request.execution_mode, local_config.flow_engine)
        normalized_request = request.model_copy(
            update={
                "process_id": request.process_id or f"fallback-{int(datetime.now().timestamp() * 1000)}",
                "phone_number": sanitized_phone,
                "action_name": canonical_action_name,
                "execution_mode": resolved_engine,
            }
        )
        if resolved_process_id is not None:
            # Se lo devolvemos a execute() para que su finally purgue este id.
            resolved_process_id[0] = normalized_request.process_id
        reset_photo_source_counts(normalized_request.process_id)
        initial_phase = "login"
        flow_engine = self._engine_router.resolve(resolved_engine)

        site_label = normalized_request.page_name.strip()
        automation_version = normalize_automation_version(
            getattr(local_config, "automation_version", "v1")
        )
        site_runner = self._build_site_runner(site_label, automation_version)
        if site_runner is None:
            return self._execute_stub(normalized_request)

        resolved_slot_id = self._resolve_slot_id_for_process(
            normalized_request.process_id,
            getattr(request, "slot_id", None),
        )
        run_context = ProcessRunContext(
            process_id=normalized_request.process_id or "unknown-process",
            page_name=normalized_request.page_name,
            action_name=normalized_request.action_name,
            phone_number=sanitized_phone,
            execution_mode=normalized_request.execution_mode,
            log_service=self._create_run_log_service(),
            slot_id=resolved_slot_id,
        )
        self._register_active_run(run_context)
        if self._closing.is_set():
            # begin_shutdown() ran while this run was being set up.
            run_context.cancel_event.set()
        run_context.run_stats.record(
            "process_started",
            {
                "site": site_runner.site_host,
                "execution_mode": normalized_request.execution_mode,
            },
        )
        attach_run_context = getattr(site_runner.runner, "attach_run_context", None)
        if callable(attach_run_context):
            attach_run_context(run_context)

        def emit_progress(phase: str, message: str) -> None:
            if progress_callback is not None:
                progress_callback(phase, message)

        def register_log_warning(message: str) -> None:
            run_context.add_warning(message)
            emit_progress("log_warning", message)

        def crear_registro_de_proceso(*, phase: str, message: str):
            return run_context.log_service.start_process(
                site=site_runner.site_host,
                action=normalized_request.action_name,
                phone=sanitized_phone,
                agent_name=normalized_request.agent_name,
                device_name=self._get_local_device_name(),
                phase=phase,
                message=message,
            )

        try:
            log_record = crear_registro_de_proceso(
                phase=initial_phase,
                message=f"Iniciando automatizacion real de {site_runner.site_host}.",
            )
            run_context.log_record_id = log_record.id
        except Exception as exc:
            register_log_warning(f"No se pudo crear process_logs inicial: {exc}")

        log_update_queue: queue.Queue[tuple[str, str] | None] = queue.Queue()
        log_worker_started = False
        log_worker_lock = threading.Lock()
        log_worker_thread: threading.Thread | None = None
        # Every call into log_service goes through this lock: the drain worker and the
        # run thread would otherwise use the same client concurrently.
        log_service_lock = threading.Lock()
        # Once set, no further update_process may run. Without it a late update that was
        # still in flight when finish_log_updates() timed out would land *after*
        # finish_process() and overwrite the final state of the run.
        log_updates_closed = threading.Event()

        def should_write_log_update(phase: str, message: str) -> bool:
            signature = (phase, message)
            now = monotonic()
            if signature == run_context.last_log_update_signature:
                return False
            # En v2, las fases "importantes" dejan de saltarse el limitador.
            #
            # Medido en v1: de las 113 emisiones de log de una corrida de
            # Paripe, ~84 pertenecen a fases exentas (photo_upload 34,
            # block_read 16, final_submit 11...), asi que el limitador de
            # 0,5 s practicamente no limitaba nada. Cada emision es un UPDATE
            # individual a Supabase, sin agrupar: con 300 ms de latencia son
            # 6-10 s por corrida, y ademas el cierre puede quedarse esperando
            # hasta 20 s a que se vacie la cola.
            #
            # En v2 se aplica a todas un intervalo propio, mas largo que el
            # general pero no cero, para no perder granularidad en las fases
            # que de verdad importan. v1 se comporta EXACTAMENTE igual que
            # siempre.
            if phase in self._IMPORTANT_LOG_PHASES and automation_version == "v2":
                last_important = run_context.last_log_update_at
                if last_important is not None and (
                    (now - last_important) < self._V2_IMPORTANT_LOG_MIN_INTERVAL_SECONDS
                ):
                    return False
                run_context.last_log_update_at = now
                run_context.last_log_update_signature = signature
                return True
            if phase in self._IMPORTANT_LOG_PHASES or run_context.last_log_update_at is None:
                run_context.last_log_update_at = now
                run_context.last_log_update_signature = signature
                return True
            if (now - run_context.last_log_update_at) >= self._LOG_UPDATE_MIN_INTERVAL_SECONDS:
                run_context.last_log_update_at = now
                run_context.last_log_update_signature = signature
                return True
            return False

        def drain_log_updates() -> None:
            while True:
                item = log_update_queue.get()
                try:
                    if item is None:
                        return
                    phase, message = item
                    if run_context.log_record_id is None or not run_context.log_updates_enabled:
                        continue
                    if log_updates_closed.is_set():
                        # The run already finished (or gave up waiting): a late update
                        # would overwrite the final state written by finish_process().
                        continue
                    with log_service_lock:
                        # Re-check under the lock: finish_log_updates() may have closed
                        # the window while this item was waiting for it.
                        if log_updates_closed.is_set():
                            continue
                        try:
                            run_context.log_service.update_process(
                                run_context.log_record_id, phase=phase, message=message
                            )
                        except Exception as exc:
                            run_context.log_updates_enabled = False
                            register_log_warning(
                                f"process_logs no disponible para updates en esta ejecucion: {exc}"
                            )
                finally:
                    log_update_queue.task_done()

        def ensure_log_worker_started() -> None:
            nonlocal log_worker_started, log_worker_thread
            with log_worker_lock:
                if log_worker_started:
                    return
                worker = threading.Thread(
                    target=drain_log_updates,
                    name=f"process-log-updates-{normalized_request.process_id}",
                    daemon=True,
                )
                # Only flag it as started once start() returned: if the thread
                # cannot be created, finish_log_updates() must not silently join a
                # thread that never ran and drop every queued update without a word.
                worker.start()
                log_worker_thread = worker
                log_worker_started = True

        def queue_log_update(phase: str, message: str) -> None:
            ensure_log_worker_started()
            log_update_queue.put((phase, message))

        def finish_log_updates() -> None:
            """Close the update window, bounded in time, and never reopen it.

            Returns once the worker has drained or the budget is spent. In both
            cases no further update_process can run, so a late write cannot
            overwrite what finish_process() is about to store.
            """

            if log_updates_closed.is_set():
                return
            worker = log_worker_thread
            if not log_worker_started or worker is None:
                log_updates_closed.set()
                return
            log_update_queue.put(None)
            # Bounded: an unbounded join() blocked the run thread for good when the
            # worker died inside its own except, or when a log write hung on the network.
            worker.join(timeout=self._LOG_DRAIN_TIMEOUT_SECONDS)
            log_updates_closed.set()
            if worker.is_alive():
                register_log_warning(
                    "No se pudieron enviar todos los updates de process_logs "
                    f"en {self._LOG_DRAIN_TIMEOUT_SECONDS:.0f}s; "
                    "se descartan los pendientes y la ejecucion continua."
                )

        def emit(phase: str, message: str) -> None:
            emit_progress(phase, message)
            run_context.run_stats.record(
                f"{phase}_event",
                {
                    "phase": phase,
                    "message": message,
                },
            )
            if (
                run_context.log_record_id is None
                or not run_context.log_updates_enabled
                or not should_write_log_update(phase, message)
            ):
                return
            queue_log_update(phase, message)

        try:
            emit(
                initial_phase,
                f"Preparando navegador limpio para {site_runner.site_host}... Motor: {flow_engine.label}.",
            )
            site_result = flow_engine.execute_site(
                site_runner,
                request=normalized_request,
                local_config=local_config,
                progress_callback=emit,
            )
        except Exception as exc:
            finish_log_updates()
            # Una cancelacion voluntaria no es un error de la automatizacion.
            # Se registraba igual que un fallo inesperado (failed/unexpected),
            # asi que cerrar la app con una corrida en vuelo ensuciaba las
            # estadisticas con fallos que nunca existieron.
            fue_cancelada = run_context.cancel_event.is_set()
            if fue_cancelada:
                fase_final = "cancelled"
                estado_final = "cancelled"
                message = (
                    f"Corrida cancelada en {site_runner.site_host} antes de terminar."
                )
            else:
                fase_final = "unexpected"
                estado_final = "failed"
                message = f"Error durante la automatizacion de {site_runner.site_host}: {exc}"
            run_context.run_stats.record(
                fase_final,
                {
                    "message": message,
                },
            )
            finished_log = self._cerrar_registro_remoto(
                run_context,
                log_service_lock,
                crear_registro=lambda: crear_registro_de_proceso(
                    phase=fase_final,
                    message=message,
                ),
                avisar=register_log_warning,
                phase=fase_final,
                final_status=estado_final,
                message=message,
                error_message=None if fue_cancelada else message,
            )
            self._store_process_debug_export(
                normalized_request.process_id,
                site_runner.runner,
                extras=self._build_run_context_debug_payload(run_context),
            )
            failed_result = ProcessExecutionResult(
                process_log_id=finished_log.id if finished_log is not None else None,
                process_id=normalized_request.process_id,
                page_name=normalized_request.page_name,
                action_name=normalized_request.action_name,
                phone_number=sanitized_phone,
                execution_mode=normalized_request.execution_mode,
                success=False,
                message=message,
                final_status=estado_final,
                phase=fase_final,
                agent_name=normalized_request.agent_name,
                completed_at=self._utcnow(),
            )
            # Persist the failure: otherwise the last-result panel keeps showing the
            # previous *successful* run as if nothing had gone wrong.
            try:
                self._last_result_service.save_result(
                    failed_result, slot_id=normalized_request.slot_id
                )
            except Exception as save_exc:  # noqa: BLE001
                register_log_warning(
                    f"No se pudo guardar el resultado fallido en disco: {save_exc}"
                )
            return failed_result

        completed_at = self._utcnow()
        finished_log = None
        run_context.run_stats.record(
            "process_finished",
            {
                "final_status": site_result.final_status,
                "success": site_result.success,
            },
        )
        finish_log_updates()
        mensaje_de_cierre = self._build_finish_message(
            site_result,
            run_context=run_context,
            runner=site_runner.runner,
            process_id=normalized_request.process_id,
        )
        finished_log = self._cerrar_registro_remoto(
            run_context,
            log_service_lock,
            crear_registro=lambda: crear_registro_de_proceso(
                phase=site_result.phase,
                message=mensaje_de_cierre,
            ),
            avisar=register_log_warning,
            phase=site_result.phase,
            final_status=site_result.final_status,
            message=mensaje_de_cierre,
            station_name=site_result.station_name,
            block_price=site_result.block_price,
            block_time=site_result.block_time,
            error_message=site_result.message if not site_result.success else None,
            finished_at=completed_at,
        )

        self._store_process_debug_export(
            normalized_request.process_id,
            site_runner.runner,
            extras=self._build_run_context_debug_payload(run_context),
        )
        result = ProcessExecutionResult(
            process_id=normalized_request.process_id,
            process_log_id=finished_log.id if finished_log is not None else None,
            page_name=normalized_request.page_name,
            action_name=normalized_request.action_name,
            phone_number=sanitized_phone,
            agent_name=normalized_request.agent_name,
            execution_mode=normalized_request.execution_mode,
            success=site_result.success,
            message=self._build_result_message(site_result, process_id=normalized_request.process_id),
            final_status=site_result.final_status,
            phase=site_result.phase,
            station_name=site_result.station_name,
            block_price=site_result.block_price,
            block_time=site_result.block_time,
            block_duration=site_result.block_duration,
            selfie_retry_count=site_result.selfie_retry_count,
            deepfakescore_retries=site_result.deepfakescore_retries or site_result.selfie_retry_count,
            deepfakescore_activated=site_result.deepfakescore_activated,
            completed_at=completed_at,
        )
        # Local persistence must not be able to fail the run: the remote log is
        # best-effort, and so is this.
        try:
            self._last_result_service.save_result(
                result, slot_id=normalized_request.slot_id
            )
        except Exception as save_exc:  # noqa: BLE001
            register_log_warning(f"No se pudo guardar el ultimo resultado en disco: {save_exc}")
        return result

    _LOG_FINISH_LOCK_TIMEOUT_SECONDS = 5.0

    def _cerrar_registro_remoto(
        self,
        run_context: ProcessRunContext,
        log_service_lock: threading.Lock,
        *,
        crear_registro,
        avisar,
        **campos,
    ):
        """Deja la corrida cerrada en process_logs, o dice por que no pudo.

        Cubre los dos caminos por los que lo que ve el agente y lo que queda en
        Supabase dejaban de coincidir:

        1. Si la fila inicial nunca se creo (Supabase caido en el arranque), la
           corrida entera terminaba sin dejar rastro: `log_record_id` era None y
           tanto los updates como el cierre se saltaban por el `is None`. Aqui se
           intenta crearla ahora, ya con el resultado en la mano. Tarde es mejor
           que nunca.
        2. Si el cierre fallaba -tipicamente porque el hilo de drenaje seguia
           dentro de un update con el candado tomado y los 5s se agotaban- la
           fila se quedaba en `started` y sin `finished_at` PARA SIEMPRE,
           mientras el resultado local decia exito. Cualquier informe por estado
           contaba esa corrida como colgada. Ahora se reintenta una vez con un
           LogService nuevo: cliente limpio y sin ese candado.

        Devuelve la fila cerrada, o None si no se pudo. Nunca lanza.
        """

        if run_context.log_record_id is None:
            try:
                registro = crear_registro()
            except Exception as exc:  # noqa: BLE001
                avisar(
                    "La corrida termino sin fila en process_logs y tampoco se "
                    f"pudo crear al cerrar: {exc}"
                )
                return None
            run_context.log_record_id = registro.id
            avisar(
                "La fila de process_logs no existia al empezar; se creo al "
                "terminar, asi que no tiene el detalle del proceso."
            )

        try:
            return self._finish_process_log(run_context, log_service_lock, **campos)
        except TimeoutError as sin_candado:
            # No se consiguio el candado: hay un update TODAVIA EN VUELO dentro
            # del cliente de logs. Escribir ahora por otro cliente seria peor
            # que no escribir: ese update aterrizaria despues del cierre y
            # pisaria el estado final con una fase intermedia. La fila se queda
            # abierta, que al menos es visiblemente incompleta en vez de
            # mentir.
            avisar(
                "No se pudo cerrar process_logs para esta ejecucion: "
                f"{sin_candado} La fila queda abierta en Supabase."
            )
            return None
        except Exception as primer_fallo:  # noqa: BLE001
            # Aqui el candado SI se tomo y se solto: el que fallo fue el
            # cliente. Un cliente nuevo -por la misma fabrica, no un
            # LogService a pelo, que ignoraria cualquier doble inyectado-
            # tiene una posibilidad real, y sigue pasando por el candado,
            # asi que el orden de escritura se respeta.
            try:
                return self._finish_process_log(
                    run_context,
                    log_service_lock,
                    log_service=self._create_run_log_service(),
                    **campos,
                )
            except Exception as segundo_fallo:  # noqa: BLE001
                avisar(
                    "No se pudo cerrar process_logs para esta ejecucion: "
                    f"{primer_fallo}. El reintento con un cliente nuevo tambien "
                    f"fallo: {segundo_fallo}. La fila queda abierta en Supabase."
                )
                return None

    def _finish_process_log(
        self,
        run_context: ProcessRunContext,
        log_service_lock: threading.Lock,
        *,
        log_service=None,
        **fields,
    ):
        """Write the final process_logs row, serialised against the drain worker.

        The lock is taken with a bound: if an update is still stuck inside the log
        client we give up on the remote row rather than block the run thread. The
        local result is persisted by the caller either way.
        """

        acquired = log_service_lock.acquire(timeout=self._LOG_FINISH_LOCK_TIMEOUT_SECONDS)
        if not acquired:
            raise TimeoutError(
                "El cliente de process_logs sigue ocupado con un update anterior "
                f"despues de {self._LOG_FINISH_LOCK_TIMEOUT_SECONDS:.0f}s."
            )
        try:
            servicio = log_service or run_context.log_service
            return servicio.finish_process(run_context.log_record_id, **fields)
        finally:
            log_service_lock.release()

    def _build_finish_message(
        self,
        site_result: SiteExecutionResult,
        *,
        run_context: ProcessRunContext | None = None,
        runner=None,
        process_id: str | None = None,
    ) -> str:
        retry_suffix = (
            f" Reintentos selfie: {site_result.selfie_retry_count}. "
            f"Deepfakescore: {'activado' if site_result.deepfakescore_activated else 'no activado'}."
        )
        source_suffix = self._build_photo_source_suffix(process_id)
        timing_summary = self._resolve_preferred_timing_summary_text(run_context=run_context, runner=runner)
        if timing_summary:
            return f"{site_result.message}{retry_suffix}{source_suffix} {timing_summary}"
        return f"{site_result.message}{retry_suffix}{source_suffix}"

    def _build_result_message(self, site_result: SiteExecutionResult, *, process_id: str | None) -> str:
        return f"{site_result.message}{self._build_photo_source_suffix(process_id)}"

    @staticmethod
    def _build_photo_source_suffix(process_id: str | None) -> str:
        source_summary = get_photo_source_summary(process_id)
        return f" Fotos usadas: {source_summary}." if source_summary else ""

    def _execute_stub(self, request: ProcessExecutionRequest) -> ProcessExecutionResult:
        log_record = self._log_service.log_info(
            site=request.page_name,
            action=request.action_name,
            phone=request.phone_number,
            agent_name=request.agent_name,
            device_name="LOCAL_UI",
            station_name="MAIN_APP",
            block_price="N/A",
            block_time="N/A",
            phase="stub_validation",
            message=(
                "Proceso registrado sin automatizacion web. "
                "El sitio seleccionado todavia no tiene integracion activa en esta fase."
            ),
            final_status="success",
        )
        return ProcessExecutionResult(
            process_id=request.process_id,
            process_log_id=log_record.id,
            page_name=request.page_name,
            action_name=request.action_name,
            phone_number=request.phone_number,
            agent_name=request.agent_name,
            execution_mode=request.execution_mode,
            success=True,
            message=(
                "Solicitud preparada correctamente. "
                "La automatizacion real todavia no esta implementada para este sitio."
            ),
            final_status="success",
            phase="stub_validation",
        )

    def _build_site_runner(
        self,
        site_label: str,
        automation_version: str = "v1",
    ) -> RegisteredSiteRunner | None:
        """Elige la automatizacion segun la version configurada.

        Cualquier valor que no sea exactamente v2 cae a v1: ante una config
        corrupta se usa la version estable, nunca la nueva.
        """

        registry = (
            self._site_runner_factories_v2
            if normalize_automation_version(automation_version) == "v2"
            else self._site_runner_factories
        )
        factory = registry.get(site_label)
        if factory is None:
            return None
        return factory()

    def _create_run_log_service(self) -> LogService:
        return self._run_log_service_factory()

    @staticmethod
    def _build_registered_site_runner_factory(
        *,
        site_label: str,
        site_host: str,
        runner_template,
        runner_factory: Callable[[], object],
    ) -> Callable[[], RegisteredSiteRunner]:
        def build_runner():
            runner = runner_factory() if runner_template is None else ProcessService._clone_runner_for_run(runner_template)
            return RegisteredSiteRunner(
                site_label=site_label,
                site_host=site_host,
                runner=runner,
            )

        return build_runner

    @staticmethod
    def _clone_runner_for_run(runner_template):
        clone_for_run = getattr(runner_template, "clone_for_run", None)
        if callable(clone_for_run):
            return clone_for_run()
        return runner_template

    @staticmethod
    def _build_run_context_debug_payload(run_context: ProcessRunContext) -> dict:
        return {
            "process_id": run_context.process_id,
            "page_name": run_context.page_name,
            "slot_id": run_context.slot_id,
            "action_name": run_context.action_name,
            "execution_mode": run_context.execution_mode,
            "log_warnings": list(run_context.warnings),
            "run_stats_timeline": run_context.run_stats.export_timeline(),
            "run_stats_summary": run_context.run_stats.build_summary(),
            "run_stats_summary_text": run_context.run_stats.build_common_timing_summary_text(),
            "process_log_id": run_context.log_record_id,
            "log_updates_enabled": run_context.log_updates_enabled,
        }

    @staticmethod
    def _resolve_preferred_timing_summary_text(
        *,
        run_context: ProcessRunContext | None = None,
        runner=None,
    ) -> str:
        if run_context is not None:
            run_stats_summary_text = str(
                run_context.run_stats.build_common_timing_summary_text() or ""
            ).strip()
            if run_stats_summary_text:
                return run_stats_summary_text
        export_debug = getattr(runner, "export_process_debug_state", None)
        if callable(export_debug):
            try:
                exported = export_debug()
            except Exception:
                exported = {}
            if isinstance(exported, dict):
                return str(exported.get("timing_summary_text") or "").strip()
        return ""

    def _resolve_slot_id_for_process(self, process_id: str | None, request_slot_id: str | None) -> str | None:
        if request_slot_id:
            return request_slot_id
        if not process_id:
            return None
        with self._process_debug_lock:
            return self._process_slot_map.get(process_id)

    def _store_process_debug_export(self, process_id: str | None, runner, *, extras: dict | None = None) -> None:
        if not process_id:
            return
        timestamp = self._utcnow().isoformat()
        with self._process_debug_lock:
            previous_payload = dict(self._process_debug_exports.get(process_id) or {})
            resolved_slot_id = self._process_slot_map.get(process_id)
        payload: dict = dict(previous_payload)
        export_debug = getattr(runner, "export_process_debug_state", None)
        if callable(export_debug):
            try:
                exported = export_debug()
            except Exception:
                exported = {}
            if isinstance(exported, dict):
                payload.update(exported)
        if isinstance(extras, dict):
            payload.update(extras)
        payload["process_id"] = process_id
        slot_id = str(payload.get("slot_id") or resolved_slot_id or "").strip() or None
        if slot_id is not None:
            payload["slot_id"] = slot_id
        payload["recorded_at"] = str(previous_payload.get("recorded_at") or timestamp)
        payload["updated_at"] = timestamp
        with self._process_debug_lock:
            if slot_id is not None:
                self._process_slot_map[process_id] = slot_id
            self._process_debug_exports[process_id] = payload
            self._process_debug_exports.move_to_end(process_id)
            if slot_id is not None:
                self._slot_debug_exports[slot_id] = dict(payload)
                self._slot_debug_exports.move_to_end(slot_id)
            self._evict_debug_exports_locked()
        self._registrar_huella_de_memoria(payload)

    def _registrar_huella_de_memoria(self, payload: dict) -> None:
        """Deja en el log cuanta memoria se lleva el historial de depuracion.

        Motivo: la app arranca en ~200 MB y sube corrida tras corrida. Se
        guardan hasta 50 exportaciones de depuracion con su linea de tiempo
        entera, y nadie habia medido nunca cuanto ocupa eso. Esta linea permite
        ver si el crecimiento va pegado a este historial o viene de otro sitio,
        en vez de adivinarlo.

        Nunca puede costar una corrida: todo va envuelto.
        """

        try:
            tamano = len(json.dumps(payload, default=str).encode("utf-8"))
        except Exception:  # noqa: BLE001
            tamano = -1
        try:
            eventos = len(payload.get("timeline") or [])
        except Exception:  # noqa: BLE001
            eventos = -1
        rss_mb = -1.0
        handles = -1
        conexiones = -1
        if psutil is not None:
            try:
                proceso = psutil.Process(os.getpid())
                rss_mb = proceso.memory_info().rss / (1024 * 1024)
                # Cada conexion abierta es un handle. Si suben corrida tras
                # corrida, hay pools de httpx que nadie cierra: cada corrida
                # construye su propio cliente de Supabase y su contexto SSL, y
                # esa memoria vive en OpenSSL, donde tracemalloc no mira.
                with suppress(Exception):
                    handles = proceso.num_handles()
                with suppress(Exception):
                    conexiones = len(proceso.net_connections(kind="tcp"))
            except Exception:  # noqa: BLE001
                pass
        with self._process_debug_lock:
            guardadas = len(self._process_debug_exports)
        _LOGGER.info(
            "Memoria: RSS=%.0f MB | handles=%s | conexiones TCP=%s | sesiones vivas=%s | "
            "exportaciones guardadas=%s (tope %s) | esta corrida=%s bytes, %s eventos",
            rss_mb,
            handles,
            conexiones,
            sesiones_vivas_en_memoria(),
            guardadas,
            self._MAX_PROCESS_DEBUG_EXPORTS,
            tamano,
            eventos,
        )
        try:
            from config.app_logging import registrar_top_de_memoria

            registrar_top_de_memoria()
        except Exception:  # noqa: BLE001
            pass

    def _evict_debug_exports_locked(self) -> None:
        while len(self._process_debug_exports) > self._MAX_PROCESS_DEBUG_EXPORTS:
            evicted_process_id, _payload = self._process_debug_exports.popitem(last=False)
            self._process_slot_map.pop(evicted_process_id, None)
        while len(self._slot_debug_exports) > self._MAX_SLOT_DEBUG_EXPORTS:
            evicted_slot_id, _payload = self._slot_debug_exports.popitem(last=False)
            stale_process_ids = [
                process_id
                for process_id, mapped_slot_id in self._process_slot_map.items()
                if mapped_slot_id == evicted_slot_id and process_id not in self._process_debug_exports
            ]
            for process_id in stale_process_ids:
                self._process_slot_map.pop(process_id, None)

    @staticmethod
    def _get_local_device_name() -> str:
        return os.getenv("COMPUTERNAME") or platform.node().strip() or "UNKNOWN_DEVICE"

    @staticmethod
    def _utcnow() -> datetime:
        return datetime.now(timezone.utc)

    @classmethod
    def _canonicalize_action_name(cls, action_name: str) -> str:
        normalized = unicodedata.normalize("NFKD", action_name)
        normalized = normalized.encode("ascii", "ignore").decode("ascii")
        normalized = " ".join(normalized.strip().lower().split())
        return cls._ACTION_CANONICAL_NAMES.get(normalized, action_name.strip())

    @staticmethod
    def _resolve_execution_mode(request_mode: str, config_mode: str) -> str:
        normalized_request = (request_mode or "").strip().lower()
        if normalized_request in {"traditional", "extension"}:
            return normalized_request
        normalized_config = (config_mode or "").strip().lower()
        if normalized_config in {"traditional", "extension"}:
            return normalized_config
        return "traditional"
