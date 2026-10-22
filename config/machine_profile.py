"""Deteccion de los recursos del equipo y perfil de configuracion.

La app la usan agentes con maquinas muy distintas: algunas con 4 GB de RAM y
dos nucleos, otras holgadas. Este modulo mide el equipo una sola vez y deriva
de esa medida los limites con los que la app deberia trabajar en el, para que
un equipo chico no intente dos procesos a la vez ni se quede corto de tiempo.

No decide nada por si mismo: solo describe. Quien aplica el perfil a la
configuracion guardada es `services/machine_tuning_service.py`.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import logging
import os
import platform

_LOGGER = logging.getLogger("auto_he_llegado.machine")

# Cuanta RAM pide una corrida completa: la app en si (200-300 MB en reposo,
# hasta 700 MB en una corrida larga) mas el Chrome que levanta Playwright.
# Medido en los equipos de los agentes, no estimado.
RAM_POR_CORRIDA_MB = 1400

# Limite duro de la interfaz: hay cuatro paneles, en una rejilla de 2x2.
MAX_PROCESOS_SOPORTADOS = 4


@dataclass(frozen=True)
class MachineResources:
    """Lo que se pudo medir del equipo."""

    total_ram_mb: int
    available_ram_mb: int
    logical_cpus: int
    physical_cpus: int
    sistema: str
    medicion_confiable: bool = True

    def firma(self) -> str:
        """Identifica al equipo para notar cuando cambia de maquina.

        Redondea la RAM a GB: un equipo no cambia de RAM entre arranques, pero
        la cifra exacta si baila unos MB segun lo que reserve el sistema.
        """

        gb = max(1, round(self.total_ram_mb / 1024))
        return f"{self.sistema}|{gb}GB|{self.logical_cpus}cpu"


@dataclass(frozen=True)
class MachineProfile:
    """Los limites con los que la app deberia trabajar en este equipo."""

    nombre: str
    max_concurrent_processes: int
    page_timeout_seconds: int
    action_timeout_seconds: int
    paripe_block_wait_seconds: int
    firma: str
    motivo: str
    # False cuando no se pudo medir la RAM de verdad. En ese caso los limites
    # son una suposicion prudente y NO deben guardarse: pisarian la medida
    # buena de un equipo holgado por un fallo puntual de psutil.
    medicion_confiable: bool = True

    def como_ajustes(self) -> dict[str, object]:
        """Los campos de LocalConfig que este perfil fija."""

        return {
            "max_concurrent_processes": self.max_concurrent_processes,
            "page_timeout_seconds": self.page_timeout_seconds,
            "action_timeout_seconds": self.action_timeout_seconds,
            "paripe_block_wait_seconds": self.paripe_block_wait_seconds,
        }


def _ram_total_mb_sin_psutil() -> int | None:
    """RAM total cuando psutil no esta disponible. None si no se puede saber."""

    try:
        if hasattr(os, "sysconf"):
            paginas = os.sysconf("SC_PHYS_PAGES")
            tamano = os.sysconf("SC_PAGE_SIZE")
            if paginas > 0 and tamano > 0:
                return int(paginas * tamano / (1024 * 1024))
    except (OSError, ValueError, AttributeError):
        pass
    return None


def detectar_recursos() -> MachineResources:
    """Mide el equipo. Nunca lanza: si no puede medir, devuelve algo prudente."""

    sistema = platform.system() or "desconocido"
    logicos = os.cpu_count() or 1
    fisicos = logicos
    total_mb: int | None = None
    disponible_mb: int | None = None

    try:
        import psutil

        memoria = psutil.virtual_memory()
        total_mb = int(memoria.total / (1024 * 1024))
        disponible_mb = int(memoria.available / (1024 * 1024))
        contados = psutil.cpu_count(logical=False)
        if contados:
            fisicos = int(contados)
    except Exception:  # noqa: BLE001 - medir nunca debe impedir arrancar
        _LOGGER.info("psutil no pudo medir el equipo; se usa la medida del sistema.")

    if total_mb is None:
        total_mb = _ram_total_mb_sin_psutil()

    confiable = total_mb is not None
    if total_mb is None:
        # Sin medida real se asume el caso chico: mas vale limitar de mas que
        # dejar que un equipo de 4 GB intente dos corridas en paralelo.
        total_mb = 4096
    if disponible_mb is None:
        disponible_mb = total_mb

    return MachineResources(
        total_ram_mb=int(total_mb),
        available_ram_mb=int(disponible_mb),
        logical_cpus=int(logicos),
        physical_cpus=int(fisicos),
        sistema=sistema,
        medicion_confiable=confiable,
    )


def _procesos_que_caben(recursos: MachineResources) -> int:
    """Cuantas corridas simultaneas aguanta el equipo.

    Reserva 2 GB para el sistema operativo y reparte el resto entre corridas.
    """

    reserva_so_mb = 2048
    util = recursos.total_ram_mb - reserva_so_mb
    por_ram = int(util // RAM_POR_CORRIDA_MB) if util > 0 else 0
    # Cada corrida ocupa su hilo y el Chrome que levanta, y Chrome por si solo
    # usa varios procesos. Dos nucleos por corrida es lo que evita que se
    # peleen y vayan todas lentas: con cuatro nucleos caben dos, con ocho
    # cuatro. Mas vale una corrida menos que cuatro arrastrandose.
    por_cpu = max(1, recursos.logical_cpus // 2)
    return max(1, min(MAX_PROCESOS_SOPORTADOS, por_ram, por_cpu))


@lru_cache(maxsize=1)
def perfil_del_equipo() -> MachineProfile:
    """El perfil de ESTE equipo, medido una sola vez por proceso.

    Lo piden el encabezado del log y el servicio de ajuste en el mismo
    arranque; sin la cache se mediria (e importaria psutil) dos veces.
    """

    return derivar_perfil()


def derivar_perfil(recursos: MachineResources | None = None) -> MachineProfile:
    """Traduce la medida del equipo a limites concretos."""

    recursos = recursos or detectar_recursos()
    procesos = _procesos_que_caben(recursos)
    gb = recursos.total_ram_mb / 1024

    if gb < 6 or recursos.logical_cpus <= 2:
        nombre = "ligero"
        # Un equipo chico tarda mas en cada paso: cortarle el tiempo de espera
        # convierte lentitud en fallo.
        page = 300
        accion = 300
        bloqueo = 420
    elif gb < 12 or recursos.logical_cpus <= 4:
        nombre = "medio"
        page = 240
        accion = 240
        bloqueo = 360
    else:
        nombre = "holgado"
        page = 180
        accion = 180
        bloqueo = 300

    motivo = (
        f"{round(gb, 1)} GB de RAM, {recursos.logical_cpus} nucleos logicos"
        f" ({recursos.physical_cpus} fisicos) en {recursos.sistema}"
    )
    if not recursos.medicion_confiable:
        motivo += " - no se pudo medir la RAM, se asume el caso chico"

    return MachineProfile(
        nombre=nombre,
        max_concurrent_processes=procesos,
        page_timeout_seconds=page,
        action_timeout_seconds=accion,
        paripe_block_wait_seconds=bloqueo,
        # Nota: `keep_browser_open` no lo toca ningun perfil. Es lo que llenaba
        # la RAM de los equipos, pero ya viene apagado de fabrica y es una
        # decision del agente, no del hardware: reaplicarlo aqui le borraria
        # su eleccion cada vez que cambie de maquina.
        firma=recursos.firma(),
        motivo=motivo,
        medicion_confiable=recursos.medicion_confiable,
    )


def describir_equipo(perfil: MachineProfile | None = None) -> str:
    """Una linea para el log y para la ventana de ajustes."""

    perfil = perfil or perfil_del_equipo()
    return (
        f"Perfil '{perfil.nombre}': {perfil.motivo}."
        f" Hasta {perfil.max_concurrent_processes} proceso(s) a la vez,"
        f" espera de pagina {perfil.page_timeout_seconds}s."
    )
