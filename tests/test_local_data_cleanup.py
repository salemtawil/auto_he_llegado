"""Purga automatica de local_data al arrancar (2026-10-14).

MaintenanceService ya sabia limpiar por antiguedad, pero NADIE lo llamaba desde
la app: solo existia scripts/run_maintenance.py, que nadie ejecuta. En la maquina
del responsable del proyecto se habian acumulado 157 MB (1.706 archivos en
failed_uploads y 959 miniaturas), en una app pensada para equipos modestos.

Estas pruebas usan archivos de verdad en tmp_path y comprueban lo que de verdad
importa: que borra lo viejo, que NO borra lo reciente, y que nunca sale de
local_data.
"""

from __future__ import annotations

import os
import time
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from services.maintenance_service import MaintenanceService


def _envejecer(path: Path, dias: float) -> None:
    viejo = time.time() - dias * 86400
    os.utime(path, (viejo, viejo))


def _servicio(tmp_path: Path) -> MaintenanceService:
    service = MaintenanceService.__new__(MaintenanceService)
    service._settings = SimpleNamespace(local_data_dir=tmp_path)  # noqa: SLF001
    service._local_data_dir = tmp_path.resolve()  # noqa: SLF001
    return service


@pytest.fixture()
def local_data(tmp_path: Path) -> Path:
    for carpeta in ("temp_photos", "failed_uploads", "review_thumbnails", "debug"):
        (tmp_path / carpeta).mkdir()
    return tmp_path


def test_borra_lo_viejo_y_conserva_lo_reciente(local_data: Path) -> None:
    viejo = local_data / "failed_uploads" / "viejo.jpg"
    viejo.write_bytes(b"x" * 1000)
    _envejecer(viejo, 60)

    reciente = local_data / "failed_uploads" / "reciente.jpg"
    reciente.write_bytes(b"x" * 1000)

    reporte = _servicio(local_data).cleanup_local_data(dry_run=False, collect_items=False)

    assert not viejo.exists(), "un fallo de hace 60 dias debe purgarse"
    assert reciente.exists(), "lo reciente NO se toca"
    assert reporte["failed_uploads"]["removed"] == 1
    assert reporte["failed_uploads"]["bytes_freed"] == 1000


def test_las_miniaturas_tambien_se_purgan(local_data: Path) -> None:
    """Eran 41 MB que no limpiaba nadie. Son cache: se vuelven a descargar."""

    vieja = local_data / "review_thumbnails" / "abc.png"
    vieja.write_bytes(b"y" * 500)
    _envejecer(vieja, 45)

    reporte = _servicio(local_data).cleanup_local_data(dry_run=False, collect_items=False)

    assert not vieja.exists()
    assert reporte["review_thumbnails"]["removed"] == 1


def test_una_corrida_larga_conserva_sus_temporales(local_data: Path) -> None:
    """temp_photos usa 24 h en la purga automatica, no las 8 h del script.

    Una corrida que lleva horas abierta sigue necesitando sus archivos.
    """

    de_hace_10_horas = local_data / "temp_photos" / "en_uso.jpg"
    de_hace_10_horas.write_bytes(b"z" * 100)
    _envejecer(de_hace_10_horas, 10 / 24)

    reporte = _servicio(local_data).cleanup_local_data(
        dry_run=False, collect_items=False, temp_photos_hours=24
    )

    assert de_hace_10_horas.exists(), "no se le pueden quitar los temporales a una corrida viva"
    assert reporte["temp_photos"]["removed"] == 0


def test_dry_run_no_borra_nada(local_data: Path) -> None:
    viejo = local_data / "failed_uploads" / "viejo.jpg"
    viejo.write_bytes(b"x" * 10)
    _envejecer(viejo, 60)

    reporte = _servicio(local_data).cleanup_local_data(dry_run=True, collect_items=False)

    assert viejo.exists()
    assert reporte["failed_uploads"]["removed"] == 0


def test_el_modo_compacto_no_construye_el_detalle(local_data: Path) -> None:
    """Con miles de archivos, el detalle solo gasta memoria."""

    for indice in range(5):
        archivo = local_data / "failed_uploads" / f"f{indice}.jpg"
        archivo.write_bytes(b"x" * 10)
        _envejecer(archivo, 60)

    compacto = _servicio(local_data).cleanup_local_data(dry_run=True, collect_items=False)
    assert compacto["failed_uploads"]["items"] == []

    detallado = _servicio(local_data).cleanup_local_data(dry_run=True, collect_items=True)
    assert len(detallado["failed_uploads"]["items"]) == 5


def test_nunca_sale_de_local_data(local_data: Path, tmp_path: Path) -> None:
    """Guarda de seguridad: un enlace hacia fuera no debe hacer que borre ahi."""

    fuera = tmp_path.parent / "no_tocar.txt"
    fuera.write_text("intacto", encoding="utf-8")
    _envejecer(fuera, 90)

    service = _servicio(local_data)
    assert service._is_safe_local_target(local_data / "failed_uploads" / "a.jpg") is True
    assert service._is_safe_local_target(fuera) is False

    service.cleanup_local_data(dry_run=False, collect_items=False)
    assert fuera.exists(), "jamas debe borrar fuera de local_data"


def test_la_app_lanza_la_purga_en_segundo_plano() -> None:
    """Debe ir en un hilo: es I/O sobre miles de archivos."""

    texto = (
        Path(__file__).resolve().parents[1] / "ui" / "main_app" / "window.py"
    ).read_text(encoding="utf-8")

    assert "_start_local_data_cleanup" in texto
    arranque = texto.split("def _start_local_data_cleanup(")[1].split("\n    def ")[0]
    assert "threading.Thread" in arranque
    assert "daemon=True" in arranque

    worker = texto.split("def _local_data_cleanup_worker(")[1].split("\n    def ")[0]
    assert "dry_run=False" in worker, "la purga automatica debe borrar de verdad"
    assert "temp_photos_hours=24" in worker, "mas conservador que el script manual"
