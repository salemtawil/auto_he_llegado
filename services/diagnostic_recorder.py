"""Graba lo que aparece en pantalla durante una corrida, para poder leerlo despues.

Sin esto, cuando el sitio cambia -un dialogo nuevo, un boton con otro
nombre, una opcion que antes no estaba- la unica informacion disponible es
una captura de pantalla, y de una captura no sale un selector. Con el
inventario de elementos y el HTML del dialogo si: se ve el rol, el
aria-checked, las clases y el texto exacto de cada cosa.

Esta apagado salvo que el agente marque "Diagnostico" en su panel, porque
cada captura cuesta un evaluate y un `content()` en la pagina real.

El archivo que sale de aqui ES CONFIDENCIAL: lleva el HTML tal cual, con el
telefono de la cuenta y lo que el sitio muestre en ese momento.
"""

from __future__ import annotations

from contextlib import suppress
from datetime import datetime, timezone
from hashlib import sha1
from time import monotonic
from typing import Any

# Lo que se busca en la pagina. Las claves son las que apareceran en el
# archivo, en castellano, porque el archivo es para leerlo.
SELECTORES = {
    "botones": "button, [role='button'], input[type='button'], input[type='submit']",
    "opciones": "[role='radio'], input[type='radio'], [role='option']",
    "interruptores": "[role='switch'], [aria-checked], [data-state], [data-checked]",
    "casillas": "input[type='checkbox'], [role='checkbox']",
    "campos": "input, textarea, select",
    "enlaces": "a[href]",
    "pulsables": "label, [tabindex], [onclick]",
}

# Textos que siempre interesan: de cada uno se guarda el elemento MAS
# INTERNO que lo contiene, con todos sus atributos, pase lo que pase con su
# etiqueta. Es lo que resuelve el caso que motivo todo esto: una opcion
# dibujada como un <div> suelto no cae en ningun selector de arriba, asi que
# sin esto no aparece en el archivo y desde fuera parece que no existe.
TERMINOS_DE_INTERES = (
    "Omitir verificacion",
    "Omitir verificación",
    "Enviar enlace",
    "Verificacion automatica de video",
    "Verificación automática de video",
    "Cuenta prestada",
    "Cuenta propia",
    "Continuar",
    "Continue",
    "Iniciar verificacion",
    "Iniciar verificación",
    "He llegado",
    "selfie",
)

# Topes. Un diagnostico que llena el disco o se come la memoria de la
# corrida deja de ser una ayuda.
MAX_CAPTURAS = 150
MAX_HTML = 120_000
MAX_ELEMENTOS_POR_TIPO = 60
MAX_LINEAS_DE_TEXTO = 120

_JS_CUERPO = r"""
(doc, opciones) => {
    const limite = opciones.limite;
    const corta = (valor, n) => {
        const texto = (valor === null || valor === undefined) ? '' : String(valor);
        return texto.length > n ? texto.slice(0, n) + '...' : texto;
    };
    const limpio = (valor) => corta((valor || '').replace(/\s+/g, ' ').trim(), 160);
    const visible = (e) => {
        try {
            const caja = e.getBoundingClientRect();
            const estilo = e.ownerDocument.defaultView.getComputedStyle(e);
            return caja.width > 1 && caja.height > 1
                && estilo.visibility !== 'hidden' && estilo.display !== 'none'
                && estilo.opacity !== '0';
        } catch (_) { return false; }
    };
    // Una ruta corta para poder volver a encontrar el elemento desde fuera.
    const ruta = (e) => {
        const partes = [];
        let actual = e;
        while (actual && actual.nodeType === 1 && partes.length < 5) {
            let parte = actual.tagName.toLowerCase();
            if (actual.id) { partes.unshift(parte + '#' + actual.id); break; }
            const padre = actual.parentElement;
            if (padre) {
                const iguales = [...padre.children].filter((h) => h.tagName === actual.tagName);
                if (iguales.length > 1) parte += ':nth-of-type(' + (iguales.indexOf(actual) + 1) + ')';
            }
            partes.unshift(parte);
            actual = actual.parentElement;
        }
        return partes.join(' > ');
    };
    const describe = (e) => ({
        tag: e.tagName,
        rol: e.getAttribute('role'),
        texto: limpio(e.innerText || e.textContent),
        aria_label: e.getAttribute('aria-label'),
        aria_checked: e.getAttribute('aria-checked'),
        aria_disabled: e.getAttribute('aria-disabled'),
        data_checked: e.hasAttribute('data-checked') ? (e.getAttribute('data-checked') || '') : null,
        data_state: e.getAttribute('data-state'),
        marcado: (e.checked === true) || null,
        deshabilitado: Boolean(e.disabled) || e.getAttribute('aria-disabled') === 'true',
        tipo: e.getAttribute('type'),
        nombre: e.getAttribute('name'),
        id: e.id || null,
        clases: corta(typeof e.className === 'string' ? e.className : '', 200),
        visible: visible(e),
        ruta: ruta(e),
    });
    // Lo mismo que hace una persona: mirar si el elemento responde al raton.
    const pulsable = (e) => {
        try {
            const estilo = e.ownerDocument.defaultView.getComputedStyle(e);
            return estilo.cursor === 'pointer';
        } catch (_) { return false; }
    };
    const normaliza = (valor) => (valor || '')
        .normalize('NFD').replace(/[\u0300-\u036f]/g, '')
        .replace(/\s+/g, ' ').trim().toLowerCase();
    const elementos = {};
    for (const [nombre, selector] of Object.entries(opciones.selectores)) {
        let encontrados = [];
        try { encontrados = [...doc.querySelectorAll(selector)]; } catch (_) { encontrados = []; }
        elementos[nombre] = encontrados.slice(0, limite).map(describe);
    }
    // Para cada texto que interesa, el elemento mas interno que lo contiene
    // y la cadena de padres por encima, marcando cual responde al raton. Ahi
    // esta lo que hay que pulsar cuando la opcion no es un radio de verdad.
    const coincidencias = {};
    let todos = [];
    try { todos = [...doc.querySelectorAll('*')]; } catch (_) { todos = []; }
    for (const termino of (opciones.terminos || [])) {
        const buscado = normaliza(termino);
        if (!buscado) continue;
        const contienen = todos.filter((e) => normaliza(e.textContent).includes(buscado));
        if (!contienen.length) continue;
        // El mas interno: el que menos descendientes tiene sigue conteniendo
        // el texto, sin arrastrar media pagina.
        contienen.sort((a, b) => a.querySelectorAll('*').length - b.querySelectorAll('*').length);
        let actual = contienen[0];
        const cadena = [];
        while (actual && actual.nodeType === 1 && cadena.length < 6) {
            const ficha = describe(actual);
            ficha.pulsable = pulsable(actual);
            cadena.push(ficha);
            actual = actual.parentElement;
        }
        coincidencias[termino] = cadena;
    }
    let lineas = [];
    try {
        const cuerpo = doc.body || doc.documentElement;
        lineas = ((cuerpo && cuerpo.innerText) || '')
            .split('\n').map((l) => l.trim()).filter(Boolean).slice(0, opciones.lineas);
    } catch (_) { lineas = []; }
    let html = '';
    try {
        // Si hay un dialogo abierto, interesa SU html, no el de media pagina.
        const dialogo = doc.querySelector('[role="dialog"], dialog, [aria-modal="true"]');
        html = (dialogo || doc.body || doc.documentElement || {}).outerHTML || '';
    } catch (_) { html = ''; }
    return {
        url: (doc.defaultView && doc.defaultView.location) ? String(doc.defaultView.location.href) : '',
        titulo: doc.title || '',
        elementos: elementos,
        coincidencias: coincidencias,
        texto_visible: lineas,
        html: corta(html, opciones.max_html),
        hay_dialogo: Boolean(doc.querySelector('[role="dialog"], dialog, [aria-modal="true"]')),
    };
}
"""

_JS_DESDE_DOCUMENTO = "(opciones) => (" + _JS_CUERPO + ")(document, opciones)"
_JS_DESDE_ELEMENTO = "(elemento, opciones) => (" + _JS_CUERPO + ")(elemento.ownerDocument, opciones)"


class DiagnosticRecorder:
    """Guarda una foto del DOM en cada momento interesante de la corrida."""

    def __init__(self, *, max_capturas: int = MAX_CAPTURAS) -> None:
        self._capturas: list[dict[str, Any]] = []
        self._max_capturas = max_capturas
        self._inicio = monotonic()
        self._ultima_firma: str | None = None
        self._descartadas_por_repetidas = 0
        self._fallos: list[dict[str, str]] = []

    # -- captura ---------------------------------------------------------

    def capturar(self, root, momento: str, **contexto) -> None:
        """Toma una foto. NUNCA lanza: el diagnostico no puede tumbar nada."""

        try:
            datos = self._leer(root)
        except Exception as exc:  # noqa: BLE001
            self._fallos.append({"momento": momento, "error": f"{type(exc).__name__}: {exc}"})
            return
        if datos is None:
            self._fallos.append({"momento": momento, "error": "la raiz no se pudo leer"})
            return

        firma = self._firma(momento, datos)
        if firma == self._ultima_firma:
            # Misma pantalla y mismo momento: no aporta nada y pesa igual.
            self._descartadas_por_repetidas += 1
            return
        self._ultima_firma = firma

        datos["momento"] = momento
        datos["instante"] = datetime.now(timezone.utc).isoformat()
        datos["ms_desde_el_inicio"] = int((monotonic() - self._inicio) * 1000)
        datos["raiz"] = type(root).__name__
        if contexto:
            datos["contexto"] = contexto
        self._capturas.append(datos)
        if len(self._capturas) > self._max_capturas:
            # Se tira por el medio, no por el principio: el arranque y el
            # final son los dos trozos que siempre hacen falta.
            del self._capturas[self._max_capturas // 2]

    def _leer(self, root) -> dict[str, Any] | None:
        opciones = {
            "selectores": SELECTORES,
            "limite": MAX_ELEMENTOS_POR_TIPO,
            "lineas": MAX_LINEAS_DE_TEXTO,
            "terminos": list(TERMINOS_DE_INTERES),
            "max_html": MAX_HTML,
        }
        # Un Locator recibe su elemento como primer argumento; una Page o un
        # Frame reciben el argumento directamente. Son dos firmas distintas y
        # no hay una sola que valga para los dos.
        if self._es_locator(root):
            return root.evaluate(_JS_DESDE_ELEMENTO, opciones)
        return root.evaluate(_JS_DESDE_DOCUMENTO, opciones)

    @staticmethod
    def _es_locator(root) -> bool:
        with suppress(Exception):
            from playwright.sync_api import Locator

            return isinstance(root, Locator)
        return type(root).__name__ == "Locator"

    @staticmethod
    def _firma(momento: str, datos: dict[str, Any]) -> str:
        material = "|".join(
            [
                momento,
                str(datos.get("url", "")),
                str(len(datos.get("html", "") or "")),
                "\n".join(datos.get("texto_visible", [])[:40]),
            ]
        )
        return sha1(material.encode("utf-8", "ignore")).hexdigest()

    # -- salida ----------------------------------------------------------

    def exportar(self) -> dict[str, Any]:
        return {
            "capturas": list(self._capturas),
            "total_capturas": len(self._capturas),
            "descartadas_por_repetidas": self._descartadas_por_repetidas,
            "fallos_de_captura": list(self._fallos),
            "topes": {
                "max_capturas": self._max_capturas,
                "max_html": MAX_HTML,
                "max_elementos_por_tipo": MAX_ELEMENTOS_POR_TIPO,
            },
        }

    def __len__(self) -> int:
        return len(self._capturas)
