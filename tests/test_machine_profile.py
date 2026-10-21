from __future__ import annotations

import pytest

from config.machine_profile import (
    MachineResources,
    _procesos_que_caben,
    derivar_perfil,
    describir_equipo,
    detectar_recursos,
)
from core.models import LocalConfig
from services.machine_tuning_service import MachineTuningService


def equipo(ram_mb: int, cpus: int, *, fisicos: int | None = None, confiable: bool = True) -> MachineResources:
    return MachineResources(
        total_ram_mb=ram_mb,
        available_ram_mb=ram_mb,
        logical_cpus=cpus,
        physical_cpus=fisicos if fisicos is not None else cpus,
        sistema="Windows",
        medicion_confiable=confiable,
    )


class ConfigServiceFalso:
    def __init__(self, config: LocalConfig) -> None:
        self.config = config
        self.guardados: list[LocalConfig] = []

    def load(self) -> LocalConfig:
        return self.config

    def save(self, config: LocalConfig) -> LocalConfig:
        self.guardados.append(config)
        self.config = config
        return config


def test_la_firma_redondea_la_ram_a_gigas():
    # El sistema reserva unos MB distintos en cada arranque: si la firma
    # dependiera del dato exacto, la app se reconfiguraria cada vez.
    assert equipo(8100, 4).firma() == equipo(8290, 4).firma()


def test_la_firma_distingue_equipos_distintos():
    assert equipo(8192, 4).firma() != equipo(16384, 4).firma()
    assert equipo(8192, 4).firma() != equipo(8192, 8).firma()


@pytest.mark.parametrize(
    ("ram_mb", "cpus", "esperado"),
    [
        (4096, 4, 1),   # 2 GB utiles: solo cabe una corrida
        (8192, 4, 2),   # 6 GB utiles y cuatro nucleos
        (16384, 2, 1),  # RAM de sobra, pero dos nucleos no dan para dos Chrome
        (16384, 8, 2),
        (2048, 8, 1),   # nunca por debajo de una
    ],
)
def test_cuantas_corridas_caben(ram_mb, cpus, esperado):
    assert _procesos_que_caben(equipo(ram_mb, cpus)) == esperado


def test_nunca_propone_mas_de_dos_porque_la_interfaz_solo_tiene_dos_paneles():
    assert _procesos_que_caben(equipo(131072, 64)) == 2


@pytest.mark.parametrize(
    ("ram_mb", "cpus", "nombre"),
    [
        (4096, 4, "ligero"),
        (16384, 2, "ligero"),
        (8192, 4, "medio"),
        (16384, 8, "holgado"),
    ],
)
def test_el_nombre_del_perfil_sigue_al_equipo(ram_mb, cpus, nombre):
    assert derivar_perfil(equipo(ram_mb, cpus)).nombre == nombre


def test_un_equipo_chico_recibe_mas_tiempo_de_espera_no_menos():
    chico = derivar_perfil(equipo(4096, 4))
    holgado = derivar_perfil(equipo(32768, 12))
    assert chico.page_timeout_seconds > holgado.page_timeout_seconds
    assert chico.action_timeout_seconds > holgado.action_timeout_seconds
    assert chico.paripe_block_wait_seconds > holgado.paripe_block_wait_seconds


def test_si_no_se_pudo_medir_la_ram_se_asume_el_caso_chico():
    perfil = derivar_perfil(equipo(4096, 8, confiable=False))
    assert perfil.max_concurrent_processes == 1
    assert "no se pudo medir" in perfil.motivo


def test_el_perfil_no_decide_sobre_el_navegador_abierto():
    # Es una eleccion del agente, no del hardware: si el perfil la fijara, se
    # la borraria cada vez que cambiara de equipo.
    assert "keep_browser_open" not in derivar_perfil(equipo(8192, 4)).como_ajustes()


def test_detectar_recursos_no_lanza_y_devuelve_algo_usable():
    recursos = detectar_recursos()
    assert recursos.total_ram_mb > 0
    assert recursos.logical_cpus >= 1
    assert describir_equipo()


def test_la_primera_vez_mide_el_equipo_y_guarda_los_limites():
    servicio_config = ConfigServiceFalso(LocalConfig())
    perfil = derivar_perfil(equipo(4096, 4))
    resultado = MachineTuningService(servicio_config, perfil=perfil).ajustar()

    assert resultado.aplicado is True
    assert resultado.config.max_concurrent_processes == 1
    assert resultado.config.page_timeout_seconds == perfil.page_timeout_seconds
    assert resultado.config.hardware_signature == perfil.firma
    assert resultado.config.hardware_profile == "ligero"
    assert servicio_config.guardados, "los limites deben quedar guardados en disco"


def test_en_el_mismo_equipo_no_vuelve_a_tocar_nada():
    perfil = derivar_perfil(equipo(8192, 4))
    guardada = LocalConfig(
        hardware_signature=perfil.firma,
        hardware_profile=perfil.nombre,
        max_concurrent_processes=1,
        # El agente bajo el tiempo de espera a mano:
        page_timeout_seconds=90,
    )
    servicio_config = ConfigServiceFalso(guardada)
    resultado = MachineTuningService(servicio_config, perfil=perfil).ajustar()

    assert resultado.aplicado is False
    assert resultado.config.page_timeout_seconds == 90
    assert resultado.config.max_concurrent_processes == 1
    assert servicio_config.guardados == []


def test_una_configuracion_copiada_de_otra_maquina_se_recalcula():
    # Un config traido de un equipo holgado no debe imponerle dos procesos a
    # un equipo de 4 GB.
    ajeno = LocalConfig(
        hardware_signature="Windows|32GB|12cpu",
        hardware_profile="holgado",
        max_concurrent_processes=2,
        page_timeout_seconds=180,
    )
    servicio_config = ConfigServiceFalso(ajeno)
    resultado = MachineTuningService(
        servicio_config, perfil=derivar_perfil(equipo(4096, 4))
    ).ajustar()

    assert resultado.aplicado is True
    assert resultado.config.max_concurrent_processes == 1
    assert resultado.config.hardware_profile == "ligero"


def test_ajustar_respeta_el_resto_de_la_configuracion():
    servicio_config = ConfigServiceFalso(
        LocalConfig(agent_name="Marta", agent_name_confirmed=True, theme_mode="dark")
    )
    resultado = MachineTuningService(
        servicio_config, perfil=derivar_perfil(equipo(16384, 8))
    ).ajustar()

    assert resultado.config.agent_name == "Marta"
    assert resultado.config.agent_name_confirmed is True
    assert resultado.config.theme_mode == "dark"
