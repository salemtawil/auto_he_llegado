"""Errores cuyo texto SI puede leer el agente.

`ui/shared/errors.py` tapa a proposito el texto de las excepciones: el de
Supabase, Storage, Playwright o pydantic arrastra rutas, contenidos de fila,
URLs con claves y lo que la persona acababa de teclear -un telefono, una
contrasena-. Nada de eso debe acabar en una captura de pantalla ni en un
ticket de soporte.

Pero esa misma regla dejaba mudos los mensajes que escribimos nosotros para
que los lea una persona. El agente veia "No se pudo enviar el video. Revisa
tu conexion y vuelve a intentar. (RuntimeError)" cuando lo que pasaba era que
el video duraba 6 segundos, o que estaba repetido, o que faltaba configurar
la carpeta de Drive. Tres problemas distintos, tres soluciones distintas, y
el mismo texto inutil para los tres.

Lo que se marca con esta clase se muestra entero. Por eso su mensaje tiene
que estar escrito como se le habla a una persona y NO debe llevar dentro
rutas, identificadores internos ni nada que venga de la base de datos.
"""

from __future__ import annotations


class ErrorParaElAgente(RuntimeError):
    """Un fallo que el agente puede entender y, casi siempre, resolver."""
