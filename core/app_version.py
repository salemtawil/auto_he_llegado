"""Que version de la app es esta, y si le basta al minimo que exige el servidor.

Vive en `core/` a proposito. `config/` es una de las rutas protegidas del
actualizador, asi que una version puesta ahi no cambiaria nunca al actualizar.

El formato es el mismo que ya usa el manifiesto del actualizador -AAAA.MM.DD.N-
para no inventar un segundo lenguaje de versiones en el mismo proyecto.
"""

from __future__ import annotations

APP_VERSION = "2026.11.16.1"

#: Cabecera con la que la app se identifica ante Supabase. El servidor la lee
#: en las politicas: quien no la manda es una version vieja.
CABECERA_DE_VERSION = "x-app-version"


def partes_de_version(valor: str | None) -> tuple[int, ...] | None:
    """La version como numeros comparables, o None si no se entiende.

    None no es "version cero": es "no se sabe". Quien llama decide que hacer
    con la duda, y en el unico sitio donde importa -el minimo- la duda cuenta
    como insuficiente, porque una version ilegible es tan desconocida como una
    ausente.
    """

    if valor is None:
        return None
    texto = str(valor).strip()
    if not texto:
        return None
    partes: list[int] = []
    for trozo in texto.split("."):
        trozo = trozo.strip()
        if not trozo or not trozo.isdigit():
            return None
        partes.append(int(trozo))
    return tuple(partes) if partes else None


def version_es_suficiente(instalada: str | None, minima: str | None) -> bool:
    """Si `instalada` llega al minimo exigido.

    Sin minimo legible no se exige nada: un valor mal escrito en la tabla de
    ajustes no puede dejar a todo el mundo fuera.
    """

    exigido = partes_de_version(minima)
    if exigido is None:
        return True
    tengo = partes_de_version(instalada)
    if tengo is None:
        return False
    # Se comparan rellenando con ceros: "2026.11.16" y "2026.11.16.0" son la
    # misma version, y "2026.11.16.1" es posterior a las dos.
    largo = max(len(tengo), len(exigido))
    tengo = tengo + (0,) * (largo - len(tengo))
    exigido = exigido + (0,) * (largo - len(exigido))
    return tengo >= exigido
