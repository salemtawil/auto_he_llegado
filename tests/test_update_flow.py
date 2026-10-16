"""El flujo de "Actualizar app": descargar, aplicar, reiniciar.

Lo que estas pruebas fijan, y por que:

- Sin registro de la revision instalada, pulsar el boton se bajaba y reaplicaba
  la misma version una y otra vez. Ahora se compara antes de descargar.
- El registro lo escribe el helper, y SOLO si la actualizacion se aplico. Si
  revierte, el archivo tiene que seguir diciendo la verdad.
- El paquete ligero no puede incluir dependencias nuevas sin dejar al agente
  con codigo que pide librerias que no tiene.
"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from scripts.build_update_package import (
    ErrorDeEmpaquetado,
    construir_paquete,
    escribir_linea_base,
)
from updater.apply_update_helper import apply_staged_update
from updater.installed_revision import (
    read_installed_revision,
    revision_file_path,
    write_installed_revision,
)
from updater.release_update_client import prepare_release_update


# ---------------------------------------------------------------------------
# Registro de la revision instalada
# ---------------------------------------------------------------------------


def test_sin_archivo_no_se_sabe_la_revision(tmp_path: Path) -> None:
    assert read_installed_revision(tmp_path) is None


def test_se_escribe_y_se_lee(tmp_path: Path) -> None:
    assert write_installed_revision(tmp_path, "2026.10.16.1") is True
    assert read_installed_revision(tmp_path) == "2026.10.16.1"


@pytest.mark.parametrize(
    "contenido",
    ['{"revision": 7}', "no es json", "[]", '{"revision": "   "}', ""],
)
def test_ante_la_duda_devuelve_none(tmp_path: Path, contenido: str) -> None:
    """None significa "actualiza igualmente": cuesta una descarga de mas.

    Devolver una revision falsa dejaria al agente sin actualizar y sin saberlo.
    """

    destino = revision_file_path(tmp_path)
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(contenido, encoding="utf-8")
    assert read_installed_revision(tmp_path) is None


def test_una_revision_vacia_no_se_guarda(tmp_path: Path) -> None:
    assert write_installed_revision(tmp_path, "  ") is False
    assert read_installed_revision(tmp_path) is None


def test_el_archivo_vive_en_una_ruta_protegida() -> None:
    """local_data/ esta en PROTECTED_PATH_PATTERNS: sobrevive a la actualizacion."""

    from updater.apply_update_helper import PROTECTED_PATH_PATTERNS

    relativo = revision_file_path(Path("/cualquier/sitio")).parts[-2]
    assert f"{relativo}/" in PROTECTED_PATH_PATTERNS


# ---------------------------------------------------------------------------
# No descargar si ya se esta al dia
# ---------------------------------------------------------------------------


def _manifiesto_falso(revision: str):
    payload = json.dumps(
        {
            "revision": revision,
            "assets": {
                "windows": {
                    "url": "https://ejemplo/paquete.zip",
                    "sha256": "0" * 64,
                    "file_name": "paquete.zip",
                }
            },
        }
    ).encode("utf-8")

    class _Respuesta:
        def read(self):
            return payload

        def __enter__(self):
            return self

        def __exit__(self, *_a):
            return False

    return lambda *_a, **_k: _Respuesta()


def _config(tmp_path: Path) -> Path:
    destino = tmp_path / "update_config.json"
    destino.write_text(json.dumps({"latest_url": "https://ejemplo/latest.json"}))
    return destino


def test_si_ya_estas_en_la_ultima_no_descarga(tmp_path: Path) -> None:
    resultado = prepare_release_update(
        config_path=_config(tmp_path),
        staging_dir=tmp_path / "staging",
        urlopen_func=_manifiesto_falso("2026.10.16.1"),
        sys_platform="win32",
        machine="amd64",
        current_revision="2026.10.16.1",
    )
    assert resultado is None


def test_espacios_alrededor_no_cuentan_como_version_distinta(tmp_path: Path) -> None:
    resultado = prepare_release_update(
        config_path=_config(tmp_path),
        staging_dir=tmp_path / "staging",
        urlopen_func=_manifiesto_falso("2026.10.16.1"),
        sys_platform="win32",
        machine="amd64",
        current_revision="  2026.10.16.1  ",
    )
    assert resultado is None


def test_sin_revision_conocida_se_actualiza_igual(tmp_path: Path) -> None:
    """Preferimos una descarga de mas a un agente sin actualizar."""

    with pytest.raises(Exception):
        # Intenta descargar de verdad (url falsa), que es justo lo que se quiere
        # comprobar: que NO corta antes por creerse al dia.
        prepare_release_update(
            config_path=_config(tmp_path),
            staging_dir=tmp_path / "staging",
            urlopen_func=_manifiesto_falso("2026.10.16.1"),
            current_revision=None,
        )


# ---------------------------------------------------------------------------
# El helper solo registra la revision si de verdad aplico
# ---------------------------------------------------------------------------


def _instalacion(tmp_path: Path) -> tuple[Path, Path]:
    install = tmp_path / "install"
    install.mkdir()
    (install / "AutoHeLlegado.exe").write_text("viejo")
    paquete = tmp_path / "paquete"
    paquete.mkdir()
    (paquete / "AutoHeLlegado.exe").write_text("nuevo")
    return install, paquete


def test_tras_aplicar_queda_registrada_la_revision(tmp_path: Path) -> None:
    install, paquete = _instalacion(tmp_path)
    resultado = apply_staged_update(
        install_dir=install,
        package_dir=paquete,
        app_exe="AutoHeLlegado.exe",
        revision="2026.10.16.1",
    )
    assert resultado.applied is True
    assert read_installed_revision(install) == "2026.10.16.1"
    assert (install / "AutoHeLlegado.exe").read_text() == "nuevo"


def test_si_revierte_no_registra_nada(tmp_path: Path) -> None:
    """El archivo nunca puede mentir sobre lo que hay instalado."""

    install, paquete = _instalacion(tmp_path)

    def _copia_que_falla(source: Path, target: Path) -> None:
        raise OSError("disco lleno")

    resultado = apply_staged_update(
        install_dir=install,
        package_dir=paquete,
        app_exe="AutoHeLlegado.exe",
        revision="2026.10.16.1",
        copy_file=_copia_que_falla,
    )
    assert resultado.applied is False
    assert resultado.rolled_back is True
    assert read_installed_revision(install) is None
    assert (install / "AutoHeLlegado.exe").read_text() == "viejo"


def test_sin_revision_el_helper_sigue_funcionando(tmp_path: Path) -> None:
    install, paquete = _instalacion(tmp_path)
    resultado = apply_staged_update(
        install_dir=install, package_dir=paquete, app_exe="AutoHeLlegado.exe"
    )
    assert resultado.applied is True
    assert read_installed_revision(install) is None


# ---------------------------------------------------------------------------
# El paquete ligero
# ---------------------------------------------------------------------------


def _build_falso(tmp_path: Path) -> Path:
    build = tmp_path / "build"
    (build / "_internal" / "cv2").mkdir(parents=True)
    (build / "AutoHeLlegado.exe").write_text("v1")
    (build / "_internal" / "cv2" / "cv2.pyd").write_text("pesado")
    (build / "local_data").mkdir()
    (build / "local_data" / "privado.json").write_text("datos del agente")
    return build


def test_los_datos_del_agente_no_entran_en_el_paquete(tmp_path: Path) -> None:
    build = _build_falso(tmp_path)
    base = tmp_path / "baseline.json"
    escribir_linea_base(build_dir=build, baseline_file=base)
    assert "local_data/privado.json" not in json.loads(base.read_text())["files"]


def test_solo_entra_lo_que_cambio(tmp_path: Path) -> None:
    build = _build_falso(tmp_path)
    base = tmp_path / "baseline.json"
    escribir_linea_base(build_dir=build, baseline_file=base)

    (build / "AutoHeLlegado.exe").write_text("v2")
    zip_path, manifiesto = construir_paquete(
        revision="1.0.1",
        build_dir=build,
        baseline_file=base,
        output_dir=tmp_path / "out",
    )
    with zipfile.ZipFile(zip_path) as archivo:
        assert archivo.namelist() == ["AutoHeLlegado.exe"]

    payload = json.loads(manifiesto.read_text())
    assert payload["revision"] == "1.0.1"
    assert len(payload["assets"]["windows"]["sha256"]) == 64


def test_se_niega_si_cambian_dependencias(tmp_path: Path) -> None:
    """Un paquete ligero con dependencias nuevas rompe la instalacion del agente."""

    build = _build_falso(tmp_path)
    base = tmp_path / "baseline.json"
    escribir_linea_base(build_dir=build, baseline_file=base)

    (build / "_internal" / "cv2" / "cv2.pyd").write_text("version nueva")
    with pytest.raises(ErrorDeEmpaquetado, match="instalador completo"):
        construir_paquete(
            revision="1.0.2",
            build_dir=build,
            baseline_file=base,
            output_dir=tmp_path / "out",
        )


def test_se_puede_forzar_a_sabiendas(tmp_path: Path) -> None:
    build = _build_falso(tmp_path)
    base = tmp_path / "baseline.json"
    escribir_linea_base(build_dir=build, baseline_file=base)
    (build / "_internal" / "cv2" / "cv2.pyd").write_text("version nueva")

    zip_path, _ = construir_paquete(
        revision="1.0.2",
        build_dir=build,
        baseline_file=base,
        output_dir=tmp_path / "out",
        permitir_dependencias=True,
    )
    with zipfile.ZipFile(zip_path) as archivo:
        assert "_internal/cv2/cv2.pyd" in archivo.namelist()


def test_sin_linea_base_no_adivina(tmp_path: Path) -> None:
    with pytest.raises(ErrorDeEmpaquetado, match="linea base"):
        construir_paquete(
            revision="1.0.1",
            build_dir=_build_falso(tmp_path),
            baseline_file=tmp_path / "no_existe.json",
            output_dir=tmp_path / "out",
        )


def test_sin_cambios_no_hay_nada_que_publicar(tmp_path: Path) -> None:
    build = _build_falso(tmp_path)
    base = tmp_path / "baseline.json"
    escribir_linea_base(build_dir=build, baseline_file=base)
    with pytest.raises(ErrorDeEmpaquetado, match="nada que publicar"):
        construir_paquete(
            revision="1.0.1",
            build_dir=build,
            baseline_file=base,
            output_dir=tmp_path / "out",
        )


# ---------------------------------------------------------------------------
# Fallos: el agente nunca se queda con la app cerrada y sin explicacion
# ---------------------------------------------------------------------------


def _relanzador() -> tuple[list, object]:
    lanzados: list = []

    def starter(cmd, cwd=None):
        lanzados.append(cmd)
        return object()

    return lanzados, starter


def test_un_zip_malicioso_no_tumba_el_helper(tmp_path: Path) -> None:
    """Antes salia por excepcion: sin log, sin reinicio, app cerrada para siempre.

    La app ya se cerro cuando el helper corre. Un traceback aqui deja al agente
    mirando una ventana que no vuelve.
    """

    install, _ = _instalacion(tmp_path)
    malicioso = tmp_path / "malicioso.zip"
    with zipfile.ZipFile(malicioso, "w") as archivo:
        archivo.writestr("../../../fuera.txt", "me escape")
        archivo.writestr("AutoHeLlegado.exe", "v2")

    lanzados, starter = _relanzador()
    resultado = apply_staged_update(
        install_dir=install,
        package_zip=malicioso,
        app_exe="AutoHeLlegado.exe",
        restart=True,
        revision="2026.10.16.1",
        popen_factory=starter,
    )

    assert resultado.applied is False
    assert "No se pudo extraer el paquete" in (resultado.error or "")
    assert resultado.log_path.exists(), "tiene que quedar rastro de lo que paso"
    assert resultado.restarted is True, "la app tiene que volver a abrirse"
    assert len(lanzados) == 1
    assert (install / "AutoHeLlegado.exe").read_text() == "viejo"
    assert read_installed_revision(install) is None
    assert not (tmp_path.parent / "fuera.txt").exists()


def test_tras_revertir_la_app_vuelve_a_abrirse(tmp_path: Path) -> None:
    """La instalacion quedo intacta: dejarla cerrada es peor que el fallo."""

    install, paquete = _instalacion(tmp_path)
    lanzados, starter = _relanzador()

    def _copia_que_falla(source: Path, target: Path) -> None:
        raise OSError("disco lleno")

    resultado = apply_staged_update(
        install_dir=install,
        package_dir=paquete,
        app_exe="AutoHeLlegado.exe",
        restart=True,
        revision="2026.10.16.1",
        copy_file=_copia_que_falla,
        popen_factory=starter,
    )

    assert resultado.rolled_back is True
    assert resultado.restarted is True
    assert len(lanzados) == 1
    assert (install / "AutoHeLlegado.exe").read_text() == "viejo"
    assert read_installed_revision(install) is None


def test_si_no_se_puede_relanzar_tampoco_revienta(tmp_path: Path) -> None:
    install, paquete = _instalacion(tmp_path)

    def _starter_roto(cmd, cwd=None):
        raise OSError("no se pudo lanzar")

    resultado = apply_staged_update(
        install_dir=install,
        package_dir=paquete,
        app_exe="AutoHeLlegado.exe",
        restart=True,
        popen_factory=_starter_roto,
    )
    assert resultado.applied is True
    assert resultado.restarted is False


def test_sin_restart_no_se_relanza_nada(tmp_path: Path) -> None:
    install, paquete = _instalacion(tmp_path)
    lanzados, starter = _relanzador()
    resultado = apply_staged_update(
        install_dir=install,
        package_dir=paquete,
        app_exe="AutoHeLlegado.exe",
        popen_factory=starter,
    )
    assert resultado.applied is True
    assert resultado.restarted is False
    assert lanzados == []


def test_el_paquete_no_puede_pisar_el_env(tmp_path: Path) -> None:
    """Aunque el paquete traiga un .env, el del agente manda."""

    install, paquete = _instalacion(tmp_path)
    (install / ".env").write_text("CREDENCIALES=del agente")
    (paquete / ".env").write_text("CREDENCIALES=de otro sitio")

    apply_staged_update(
        install_dir=install, package_dir=paquete, app_exe="AutoHeLlegado.exe"
    )
    assert (install / ".env").read_text() == "CREDENCIALES=del agente"


def test_si_un_archivo_no_se_puede_restaurar_se_sigue_con_los_demas(tmp_path: Path) -> None:
    """Revertir a medias es malo; abandonar en el primer tropiezo es peor."""

    install = tmp_path / "install"
    install.mkdir()
    (install / "a.txt").write_text("a viejo")
    (install / "b.txt").write_text("b viejo")
    paquete = tmp_path / "paquete"
    paquete.mkdir()
    (paquete / "a.txt").write_text("a nuevo")
    (paquete / "b.txt").write_text("b nuevo")

    copias = {"n": 0}

    def _copia(source: Path, target: Path) -> None:
        copias["n"] += 1
        if copias["n"] == 2:
            raise OSError("archivo bloqueado")
        import shutil as _shutil

        _shutil.copy2(source, target)

    resultado = apply_staged_update(
        install_dir=install,
        package_dir=paquete,
        app_exe="a.txt",
        copy_file=_copia,
    )

    assert resultado.rolled_back is True
    # Lo que se alcanzo a tocar vuelve a su sitio; nada queda a medias en silencio.
    assert (install / "a.txt").read_text() == "a viejo"
    assert (install / "b.txt").read_text() == "b viejo"


def test_el_helper_arranca_aunque_no_encuentre_el_registro_de_revision() -> None:
    """Para cuando el helper corre, la app ya se cerro sola.

    Un ImportError al cargar el modulo dejaria al agente sin actualizacion, sin
    log y sin app abierta. Perder el registro de revision solo cuesta una
    descarga de mas.
    """

    import updater.apply_update_helper as helper

    cargar = helper._cargar_registro_de_revision  # noqa: SLF001

    # Con los dos imports rotos, tiene que devolver un sustituto, no reventar.
    import builtins

    real_import = builtins.__import__

    def _import_roto(nombre, *args, **kwargs):
        if "installed_revision" in nombre:
            raise ImportError("simulado: no esta empaquetado")
        return real_import(nombre, *args, **kwargs)

    builtins.__import__ = _import_roto
    try:
        sustituto = cargar()
    finally:
        builtins.__import__ = real_import

    assert callable(sustituto)
    assert sustituto(Path("/cualquier/sitio"), "2026.10.15.1") is False


def test_cuando_el_modulo_esta_se_usa_el_de_verdad(tmp_path: Path) -> None:
    import updater.apply_update_helper as helper

    escribir = helper._cargar_registro_de_revision()  # noqa: SLF001
    assert escribir(tmp_path, "2026.10.15.1") is True
    assert read_installed_revision(tmp_path) == "2026.10.15.1"
