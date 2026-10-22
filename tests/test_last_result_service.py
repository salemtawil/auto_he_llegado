"""El ultimo resultado se guarda entero o no se toca, y siempre se guarda.

`_write_snapshot` era un `write_text` directo: si la app se cerraba a mitad de
la escritura, el JSON quedaba truncado, `load_latest` se tragaba la excepcion y
el panel de "ultimo resultado" se quedaba vacio sin decir por que. Ahora se
escribe a un temporal y se reemplaza de forma atomica.
"""

from __future__ import annotations

from pathlib import Path

from core.models import ProcessExecutionResult
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
