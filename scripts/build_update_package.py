"""Arma el paquete de actualizacion ligero y su manifiesto.

Por que existe
--------------
Reinstalar hoy son ~365 MB. De esos, ~305 MB son `_internal` (cv2, playwright,
numpy): dependencias que casi nunca cambian. El codigo propio va compilado
DENTRO de los .exe, asi que un cambio de codigo normal solo altera esos .exe:
unos 15 MB, o 60 si cambian los cuatro.

Este script empaqueta solo lo que de verdad cambio respecto a la ultima linea
base publicada, y escribe el `update_latest.json` que la app busca.

La trampa, y el guard
---------------------
Si una actualizacion necesita una dependencia nueva de pip, `_internal` cambia
y un paquete de solo-exes dejaria la instalacion del agente rota: codigo nuevo
pidiendo librerias que no estan. Ahi el script SE NIEGA a construir el paquete
ligero y te dice que publiques un instalador completo.

Nunca adivina. Si no puede comparar contra una linea base, se niega.

Uso
---
    python scripts/build_update_package.py --revision 2026.10.16.1

    # La primera vez, o tras un instalador completo:
    python scripts/build_update_package.py --write-baseline
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BUILD_DIR = PROJECT_ROOT / "dist" / "AutoHeLlegado"
BASELINE_FILE = PROJECT_ROOT / "updater" / "baseline_manifest.json"
OUTPUT_DIR = PROJECT_ROOT / "releases"

#: Lo que el agente descarga tiene que poder aplicarse sobre SU instalacion.
#: Estas rutas son suyas, no nuestras: el helper ya las protege, y meterlas en
#: el paquete solo serviria para que las ignorase.
EXCLUIR = (
    ".env",
    "local_data/",
    "logs/",
    "exports/",
    "chrome_profiles/",
    "updates/",
    "updater/updater_config.json",
)


class ErrorDeEmpaquetado(RuntimeError):
    pass


def sha256_de(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for bloque in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(bloque)
    return digest.hexdigest()


def _excluido(relativo: str) -> bool:
    normalizado = relativo.replace("\\", "/")
    return any(
        normalizado == patron or normalizado.startswith(patron)
        for patron in EXCLUIR
    )


def huellas_del_build(build_dir: Path) -> dict[str, str]:
    """sha256 de cada archivo del build, por ruta relativa."""

    if not build_dir.is_dir():
        raise ErrorDeEmpaquetado(
            f"No se encontro el build en {build_dir}. Construyelo antes de empaquetar."
        )
    huellas: dict[str, str] = {}
    for path in sorted(build_dir.rglob("*")):
        if not path.is_file():
            continue
        relativo = path.relative_to(build_dir).as_posix()
        if _excluido(relativo):
            continue
        huellas[relativo] = sha256_de(path)
    if not huellas:
        raise ErrorDeEmpaquetado(f"El build en {build_dir} esta vacio.")
    return huellas


def cambios_contra_linea_base(
    huellas: dict[str, str], linea_base: dict[str, str]
) -> list[str]:
    return sorted(
        relativo
        for relativo, huella in huellas.items()
        if linea_base.get(relativo) != huella
    )


def _es_dependencia(relativo: str) -> bool:
    """`_internal/` son las librerias; todo lo demas es nuestro."""

    return relativo.replace("\\", "/").startswith("_internal/")


def construir_paquete(
    *,
    revision: str,
    build_dir: Path = BUILD_DIR,
    baseline_file: Path = BASELINE_FILE,
    output_dir: Path = OUTPUT_DIR,
    permitir_dependencias: bool = False,
) -> tuple[Path, Path]:
    if not baseline_file.is_file():
        raise ErrorDeEmpaquetado(
            f"No hay linea base en {baseline_file}.\n"
            "Publica un instalador completo y corre este script con --write-baseline."
        )
    linea_base = json.loads(baseline_file.read_text(encoding="utf-8-sig"))
    if not isinstance(linea_base, dict) or not linea_base.get("files"):
        raise ErrorDeEmpaquetado(f"La linea base {baseline_file} no tiene 'files'.")

    huellas = huellas_del_build(build_dir)
    cambios = cambios_contra_linea_base(huellas, linea_base["files"])
    if not cambios:
        raise ErrorDeEmpaquetado(
            "No hay ningun archivo distinto de la linea base: no hay nada que publicar."
        )

    dependencias = [relativo for relativo in cambios if _es_dependencia(relativo)]
    if dependencias and not permitir_dependencias:
        muestra = "\n  ".join(dependencias[:10])
        extra = f"\n  ... y {len(dependencias) - 10} mas" if len(dependencias) > 10 else ""
        raise ErrorDeEmpaquetado(
            "Cambiaron dependencias dentro de _internal/, asi que un paquete ligero\n"
            "dejaria al agente con codigo nuevo pidiendo librerias que no tiene.\n"
            "Publica un instalador completo y vuelve a fijar la linea base.\n\n"
            f"Archivos de dependencias que cambiaron ({len(dependencias)}):\n  {muestra}{extra}"
        )

    staging = output_dir / f"update_{revision}"
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True, exist_ok=True)
    for relativo in cambios:
        destino = staging / relativo
        destino.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(build_dir / relativo, destino)

    zip_base = output_dir / f"AutoHeLlegado_Windows_Update_{revision}"
    if zip_base.with_suffix(".zip").exists():
        zip_base.with_suffix(".zip").unlink()
    zip_path = Path(
        shutil.make_archive(str(zip_base), "zip", root_dir=staging)
    )
    shutil.rmtree(staging)

    manifiesto = {
        "revision": revision,
        "assets": {
            "windows": {
                "url": (
                    "https://github.com/salemtawil/auto_he_llegado/releases/download/"
                    f"{revision}/{zip_path.name}"
                ),
                "sha256": sha256_de(zip_path),
                "file_name": zip_path.name,
            }
        },
        "notes": [f"{len(cambios)} archivo(s) actualizados"],
    }
    manifiesto_path = output_dir / "update_latest.json"
    manifiesto_path.write_text(
        json.dumps(manifiesto, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return zip_path, manifiesto_path


def escribir_linea_base(
    *, build_dir: Path = BUILD_DIR, baseline_file: Path = BASELINE_FILE, revision: str = ""
) -> Path:
    huellas = huellas_del_build(build_dir)
    baseline_file.parent.mkdir(parents=True, exist_ok=True)
    baseline_file.write_text(
        json.dumps({"revision": revision, "files": huellas}, indent=2) + "\n",
        encoding="utf-8",
    )
    return baseline_file


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--revision", default="")
    parser.add_argument("--build-dir", default=str(BUILD_DIR))
    parser.add_argument("--write-baseline", action="store_true")
    parser.add_argument(
        "--allow-dependency-changes",
        action="store_true",
        help="Empaqueta aunque cambien dependencias. Solo si sabes lo que haces.",
    )
    args = parser.parse_args(argv)
    build_dir = Path(args.build_dir)

    try:
        if args.write_baseline:
            destino = escribir_linea_base(
                build_dir=build_dir, revision=args.revision
            )
            print(f"Linea base escrita en: {destino}")
            return 0
        if not args.revision:
            raise ErrorDeEmpaquetado("Falta --revision (por ejemplo 2026.10.16.1).")
        zip_path, manifiesto = construir_paquete(
            revision=args.revision,
            build_dir=build_dir,
            permitir_dependencias=args.allow_dependency_changes,
        )
    except ErrorDeEmpaquetado as error:
        print(f"\n{error}\n", file=sys.stderr)
        return 1

    print(f"Paquete:     {zip_path}  ({zip_path.stat().st_size / 1_048_576:.1f} MB)")
    print(f"Manifiesto:  {manifiesto}")
    print("\nSiguiente paso: crear el Release en GitHub con la etiqueta")
    print(f"  {args.revision}")
    print(f"subir {zip_path.name}, y publicar el manifiesto como update_latest.json")
    print("en la raiz de la rama main.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
