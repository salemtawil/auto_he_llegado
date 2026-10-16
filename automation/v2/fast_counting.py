"""Contar botones finales con un solo `evaluate` en vez de elemento por elemento.

La v1 recorre todos los `button, [role=button], a` del contexto y por cada uno
pregunta al navegador visible + bounding_box + innerText + 4 atributos: ~7 idas
y vueltas por elemento, a ~1,85 ms cada una. Medido contra Chromium real, eso
son ~211 ms por llamada, y `_resolve_block_context` la llama una vez por
candidato (~2.700 ms por vuelta del poll).

Aqui se hace lo mismo dentro del navegador, en una sola llamada.

La logica se replica literalmente de `_count_final_submit_buttons` de la v1
(compinche_site.py:4174, identico en ready4drive_site.py):

    visible y con caja de >= 2x2  ->  candidato
    texto = innerText + aria-label + title + alt + data-testid, normalizados
    +100 si algun final_submit_text aparece en el texto
    -80  si el texto contiene "continuar" o "continue"
    cuenta si el score queda > 0

Solo vale para Compinche y Ready4Drive. En Paripe NO se puede usar: alli
`_count_final_submit_buttons` delega en `_find_final_submit_button`, que ademas
de buscar recuerda el candidato (`_remember_final_button_candidate`) para la
ruta del click final. Sustituirlo por un conteo puro le quitaria ese efecto.
"""

from __future__ import annotations

_CUERPO_JS = """
    const normalize = (value) =>
        (value || "")
            .normalize("NFKD")
            .replace(/[\\u0300-\\u036f]/g, "")
            .replace(/\\s+/g, " ")
            .trim()
            .toLowerCase();
    const isVisible = (element) => {
        if (!element) {
            return false;
        }
        const style = window.getComputedStyle(element);
        if (!style || style.visibility === "hidden" || style.display === "none") {
            return false;
        }
        const rect = element.getBoundingClientRect();
        return rect.width >= 2 && rect.height >= 2;
    };
    const etiquetas = labels.map(normalize).filter(Boolean);
    const candidatos = Array.from(
        raiz.querySelectorAll("button, [role='button'], a")
    );
    let total = 0;
    for (const elemento of candidatos) {
        if (!isVisible(elemento)) {
            continue;
        }
        const partes = [normalize(elemento.innerText)];
        for (const atributo of ["aria-label", "title", "alt", "data-testid"]) {
            const valor = elemento.getAttribute(atributo);
            if (valor) {
                partes.push(normalize(valor));
            }
        }
        const texto = partes.filter(Boolean).join(" ").trim();
        let score = 0;
        if (etiquetas.some((etiqueta) => texto.includes(etiqueta))) {
            score += 100;
        }
        if (texto.includes("continuar") || texto.includes("continue")) {
            score -= 80;
        }
        if (score > 0) {
            total += 1;
        }
    }
    return total;
"""

#: Para Page o Frame: `evaluate` recibe solo el argumento, y la raiz es el documento.
_JS_DESDE_DOCUMENTO = "(labels) => { const raiz = document;" + _CUERPO_JS + "}"

#: Para Locator: `evaluate` recibe PRIMERO el elemento y despues el argumento.
#: Ademas la v1 acota la busqueda a ese elemento (`root.locator(...)`), asi que
#: la raiz aqui tiene que ser el elemento, no el documento.
_JS_DESDE_ELEMENTO = "(elemento, labels) => { const raiz = elemento;" + _CUERPO_JS + "}"


def _es_locator(root: object) -> bool:
    """Un Locator acota la busqueda; una Page o Frame, no."""

    return type(root).__name__ == "Locator"


class ConteoRapidoDeBotonesFinales:
    """Mixin: `_count_final_submit_buttons` en una sola llamada al navegador.

    Si el `evaluate` falla por lo que sea (contexto muerto, navegacion a medias,
    un root que no expone evaluate), cae a la implementacion de la v1. Mas lento,
    pero nunca un conteo inventado.
    """

    def _count_final_submit_buttons(self, root) -> int:
        evaluate = getattr(root, "evaluate", None)
        if not callable(evaluate):
            return super()._count_final_submit_buttons(root)
        js = _JS_DESDE_ELEMENTO if _es_locator(root) else _JS_DESDE_DOCUMENTO
        try:
            total = evaluate(js, list(self._selectors.final_submit_texts))
        except Exception:
            return super()._count_final_submit_buttons(root)
        if isinstance(total, bool) or not isinstance(total, (int, float)):
            return super()._count_final_submit_buttons(root)
        return int(total)
