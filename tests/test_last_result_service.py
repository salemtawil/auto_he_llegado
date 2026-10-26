"""El ultimo resultado se guarda entero o no se toca, y siempre se guarda.

`_write_snapshot` era un `write_text` directo: si la app se cerraba a mitad de
la escritura, el JSON quedaba truncado, `load_latest` se tragaba la excepcion y
el panel de "ultimo resultado" se quedaba vacio sin decir por que. Ahora se
escribe a un temporal y se reemplaza de forma atomica.
"""

from __future__ import annotations

from pathlib import Path

from core.models import LastResultSnapshot, ProcessExecutionResult
from services.last_result_service import LastResultService


def _result(*, success: bool = True) -> ProcessExecutionResult:
    return ProcessExecutionResult(
        page_name="Compinche",
        action_name="He llegado",
        phone_number="8095551234",
        agent_name="Agente Local",
        success=success,
        message="Proceso completado.",
        final_status="success" if success else "failed",
        phase="final_result",
    )


def test_guarda_y_recupera_el_ultimo_resultado(tmp_path: Path) -> None:
    service = LastResultService(root_dir=tmp_path)

    guardado = service.save_result(_result())
    recuperado = service.load_latest()

    assert recuperado is not None
    assert recuperado.final_status == guardado.final_status
    assert [p.name for p in tmp_path.rglob("*.tmp")] == []


def test_el_filtro_de_solo_exitosos_no_ve_la_corrida_fallida(tmp_path: Path) -> None:
    service = LastResultService(root_dir=tmp_path)

    service.save_result(_result(success=True))
    service.save_result(_result(success=False))

    assert service.load_latest().success is False
    assert service.load_latest(only_successful=True).success is True


def test_el_resultado_se_guarda_aunque_el_reemplazo_atomico_falle(
    tmp_path: Path, monkeypatch
) -> None:
    """En Windows, con la carpeta dentro de OneDrive, `os.replace` sobre un
    fichero que el sincronizador tiene abierto devuelve WinError 5. Perder la
    atomicidad en ese caso concreto es mucho menos grave que no guardar la
    corrida: paso de verdad, en la suite del 22/10."""

    import os as _os

    from services import last_result_service as modulo

    service = LastResultService(root_dir=tmp_path)
    monkeypatch.setattr(modulo, "sleep", lambda _s: None)

    def replace_siempre_denegado(_origen, _destino):
        raise PermissionError(5, "Acceso denegado")

    monkeypatch.setattr(_os, "replace", replace_siempre_denegado)

    guardado = service.save_result(_result())

    recuperado = service.load_latest()
    assert recuperado is not None, "el resultado tiene que quedar guardado igual"
    assert recuperado.final_status == guardado.final_status
    sobrantes = [p.name for p in tmp_path.rglob("*.tmp")]
    assert sobrantes == [], f"no debe dejar temporales tirados: {sobrantes}"


def _con_mensaje(mensaje: str, *, success: bool = True) -> ProcessExecutionResult:
    return _result(success=success).model_copy(update={"message": mensaje})


def test_cada_panel_guarda_lo_suyo_y_no_pisa_a_los_demas(tmp_path: Path) -> None:
    """Cuatro corridas a la vez: la ultima en terminar pisaba a las otras tres.

    Al reabrir la app, tres paneles mostraban una corrida que no era la suya.
    """

    servicio = LastResultService(tmp_path)
    for numero in (1, 2, 3, 4):
        servicio.save_result(_con_mensaje(f"corrida {numero}"), slot_id=f"slot_{numero}")

    for numero in (1, 2, 3, 4):
        guardado = servicio.load_latest(slot_id=f"slot_{numero}")
        assert guardado is not None
        assert guardado.message == f"corrida {numero}"


def test_un_panel_sin_corridas_no_hereda_la_de_otro(tmp_path: Path) -> None:
    servicio = LastResultService(tmp_path)
    servicio.save_result(_con_mensaje("solo el primero"), slot_id="slot_1")

    assert servicio.load_latest(slot_id="slot_2") is None
    assert servicio.load_latest(slot_id="slot_3") is None


def test_el_filtro_de_solo_exitosos_tambien_es_por_panel(tmp_path: Path) -> None:
    servicio = LastResultService(tmp_path)
    servicio.save_result(_con_mensaje("exito del 1"), slot_id="slot_1")
    servicio.save_result(_con_mensaje("fallo del 2", success=False), slot_id="slot_2")

    assert servicio.load_latest(slot_id="slot_1", only_successful=True).message == "exito del 1"
    assert servicio.load_latest(slot_id="slot_2", only_successful=True) is None
    assert servicio.load_latest(slot_id="slot_2").message == "fallo del 2"


def test_el_fichero_viejo_sin_panel_se_sigue_leyendo_una_vez(tmp_path: Path) -> None:
    """Al actualizar, lo guardado antes no puede desaparecer de la vista.

    Se muestra solo en el primer panel: repartirlo a los cuatro seria
    inventarse tres corridas que nunca ocurrieron.
    """

    servicio = LastResultService(tmp_path)
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "latest_general.json").write_text(
        LastResultSnapshot(
            phone_number="8095551234",
            action_name="He llegado",
            site_name="Compinche",
            success=True,
            message="corrida de antes de actualizar",
        ).model_dump_json(),
        encoding="utf-8",
    )

    heredado = servicio.load_latest(slot_id="slot_1")
    assert heredado is not None
    assert heredado.message == "corrida de antes de actualizar"
    assert servicio.load_latest(slot_id="slot_2") is None

    # Y en cuanto ese panel tiene corrida propia, el fichero viejo deja de
    # asomar: lo suyo manda.
    servicio.save_result(_con_mensaje("corrida nueva"), slot_id="slot_1")
    assert servicio.load_latest(slot_id="slot_1").message == "corrida nueva"


def test_un_slot_id_raro_no_escribe_fuera_de_la_carpeta(tmp_path: Path) -> None:
    servicio = LastResultService(tmp_path)
    servicio.save_result(_con_mensaje("intento"), slot_id="../../fuera")

    assert not (tmp_path.parent / "fuera").exists()
    escritos = [r for r in tmp_path.rglob("latest_general.json")]
    assert escritos, "tiene que haber guardado en algun sitio dentro de la carpeta"
    for ruta in escritos:
        assert tmp_path.resolve() in ruta.resolve().parents
