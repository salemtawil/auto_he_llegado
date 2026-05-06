from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import re
from typing import Any, Iterable

from playwright.sync_api import ElementHandle, Error, Frame, Page


KEY_TEXTS = [
    "Cuenta prestada",
    "Cuenta propia",
    "Continuar",
    "He llegado",
    "He llegado Instantaneas",
    "He llegado Instantáneas",
    "Selfie en ruta",
    "Selfie on route",
    "Borrowed account",
    "Own account",
]

_TEXT_SCRIPT = """
() => {
  const text = (document.body?.innerText || "").replace(/\\u00a0/g, " ");
  return text
    .split(/\\r?\\n/)
    .map((line) => line.trim())
    .filter(Boolean)
    .slice(0, 600);
}
"""

_ELEMENTS_SCRIPT = """
({ selectors, limit }) => {
  const describe = (node) => {
    const text = (node.innerText || node.textContent || "").replace(/\\s+/g, " ").trim();
    const attrs = {};
    for (const name of ["id", "name", "type", "role", "title", "placeholder", "aria-label", "href", "src"]) {
      const value = node.getAttribute?.(name);
      if (value) attrs[name] = value;
    }
    return {
      tag: node.tagName?.toLowerCase() || "",
      text,
      attrs,
    };
  };
  const results = {};
  for (const [name, selector] of Object.entries(selectors)) {
    results[name] = Array.from(document.querySelectorAll(selector))
      .slice(0, limit)
      .map(describe);
  }
  return results;
}
"""


def _normalize_text(value: str) -> str:
    text = value.lower().strip()
    replacements = str.maketrans(
        {
            "á": "a",
            "é": "e",
            "í": "i",
            "ó": "o",
            "ú": "u",
            "ñ": "n",
            "ç": "c",
        }
    )
    return re.sub(r"\s+", " ", text.translate(replacements))


@dataclass(slots=True)
class ElementInfo:
    tag: str
    text: str
    attrs: dict[str, str]


@dataclass(slots=True)
class IframeInfo:
    index: int
    name: str
    title: str
    src: str
    url: str
    accessible: bool
    inspect_error: str


@dataclass(slots=True)
class RootSnapshot:
    html: str
    visible_lines: list[str]
    buttons: list[ElementInfo]
    switches: list[ElementInfo]
    radios: list[ElementInfo]
    checkboxes: list[ElementInfo]
    inputs: list[ElementInfo]
    file_inputs: list[ElementInfo]
    clickables: list[ElementInfo]
    matched_terms: dict[str, list[str]]


@dataclass(slots=True)
class PageSnapshot:
    captured_at: str
    url: str
    title: str
    iframes: list[IframeInfo]
    main: RootSnapshot
    iframe_roots: dict[str, RootSnapshot]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class DomSnapshotService:
    def __init__(self, extra_terms: Iterable[str] | None = None) -> None:
        self._terms = [term for term in KEY_TEXTS]
        if extra_terms:
            for term in extra_terms:
                clean = term.strip()
                if clean and clean not in self._terms:
                    self._terms.append(clean)

    def capture(self, page: Page) -> PageSnapshot:
        iframes = self._list_iframes(page)
        main = self._capture_root(page)
        iframe_roots: dict[str, RootSnapshot] = {}

        for iframe in iframes:
            frame = self._frame_by_index(page, iframe.index)
            if frame is None:
                continue
            try:
                iframe_roots[str(iframe.index)] = self._capture_root(frame)
            except Error:
                continue

        return PageSnapshot(
            captured_at=page.evaluate("() => new Date().toISOString()"),
            url=page.url,
            title=page.title(),
            iframes=iframes,
            main=main,
            iframe_roots=iframe_roots,
        )

    def build_signature(self, snapshot: PageSnapshot) -> str:
        payload = {
            "url": snapshot.url,
            "title": snapshot.title,
            "iframes": [
                {"title": iframe.title, "src": iframe.src, "url": iframe.url}
                for iframe in snapshot.iframes
            ],
            "main_terms": sorted(snapshot.main.matched_terms),
            "main_files": len(snapshot.main.file_inputs),
            "main_buttons": [item.text for item in snapshot.main.buttons[:20]],
            "iframe_terms": {
                key: sorted(root.matched_terms)
                for key, root in snapshot.iframe_roots.items()
            },
            "iframe_files": {
                key: len(root.file_inputs)
                for key, root in snapshot.iframe_roots.items()
            },
        }
        digest = hashlib.sha1(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8"))
        return digest.hexdigest()

    def detect_events(
        self,
        previous: PageSnapshot | None,
        current: PageSnapshot,
        previous_signature: str | None,
        current_signature: str,
    ) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        if previous is None:
            events.append({"kind": "initial_snapshot", "message": "Primer snapshot de la sesión."})
            return events

        if previous.url != current.url:
            events.append({"kind": "url_changed", "message": f"URL cambió: {previous.url} -> {current.url}"})
        if previous.title != current.title:
            events.append(
                {"kind": "title_changed", "message": f"Título cambió: {previous.title!r} -> {current.title!r}"}
            )

        previous_iframes = {(item.title, item.src) for item in previous.iframes}
        current_iframes = {(item.title, item.src) for item in current.iframes}
        added_iframes = current_iframes - previous_iframes
        removed_iframes = previous_iframes - current_iframes
        if added_iframes or removed_iframes:
            events.append(
                {
                    "kind": "iframe_changed",
                    "message": f"Iframes detectados: {len(current.iframes)} (nuevos: {len(added_iframes)}, removidos: {len(removed_iframes)})",
                }
            )

        previous_terms = self._collect_terms(previous)
        current_terms = self._collect_terms(current)
        new_terms = sorted(current_terms - previous_terms)
        if new_terms:
            events.append(
                {
                    "kind": "key_text_detected",
                    "message": f"Textos clave nuevos: {', '.join(new_terms)}",
                    "terms": new_terms,
                }
            )

        if self._count_file_inputs(current) > self._count_file_inputs(previous):
            events.append(
                {
                    "kind": "file_input_detected",
                    "message": f"Inputs de archivo detectados: {self._count_file_inputs(current)}",
                }
            )

        if previous_signature and previous_signature != current_signature:
            events.append({"kind": "dom_changed", "message": "Cambio estructural relevante en el DOM."})
        return events

    def _list_iframes(self, page: Page) -> list[IframeInfo]:
        results: list[IframeInfo] = []
        iframe_locator = page.locator("iframe")
        for index in range(iframe_locator.count()):
            locator = iframe_locator.nth(index)
            frame: Frame | None = None
            inspect_error = ""
            try:
                handle = locator.element_handle()
                if handle is not None:
                    frame = handle.content_frame()
            except Error as exc:
                inspect_error = str(exc)

            try:
                results.append(
                    IframeInfo(
                        index=index,
                        name=locator.get_attribute("name") or "",
                        title=locator.get_attribute("title") or "",
                        src=locator.get_attribute("src") or "",
                        url=frame.url if frame else "",
                        accessible=frame is not None,
                        inspect_error=inspect_error,
                    )
                )
            except Error:
                continue
        return results

    def _frame_by_index(self, page: Page, index: int) -> Frame | None:
        try:
            handle = page.locator("iframe").nth(index).element_handle()
            if handle is None:
                return None
            return handle.content_frame()
        except Error:
            return None

    def _capture_root(self, root: Page | Frame) -> RootSnapshot:
        visible_lines = self._safe_evaluate(root, _TEXT_SCRIPT, [])
        elements = self._safe_evaluate(
            root,
            _ELEMENTS_SCRIPT,
            {
                "selectors": {
                    "buttons": "button, [role='button'], input[type='button'], input[type='submit']",
                    "switches": "[role='switch'], [aria-checked], [data-state]",
                    "radios": "[role='radio'], input[type='radio']",
                    "checkboxes": "input[type='checkbox'], [role='checkbox']",
                    "inputs": "input, textarea, select",
                    "file_inputs": "input[type='file'], input[accept*='image']",
                    "clickables": "a, button, [role='button'], label, [tabindex], [onclick]",
                },
                "limit": 80,
            },
        )
        buttons = [self._element_from_payload(item) for item in elements.get("buttons", [])]
        switches = [self._element_from_payload(item) for item in elements.get("switches", [])]
        radios = [self._element_from_payload(item) for item in elements.get("radios", [])]
        checkboxes = [self._element_from_payload(item) for item in elements.get("checkboxes", [])]
        inputs = [self._element_from_payload(item) for item in elements.get("inputs", [])]
        file_inputs = [self._element_from_payload(item) for item in elements.get("file_inputs", [])]
        clickables = [self._element_from_payload(item) for item in elements.get("clickables", [])]
        matched_terms: dict[str, list[str]] = {}
        for term in self._terms:
            pattern = _normalize_text(term)
            matches = [line for line in visible_lines if pattern in _normalize_text(line)]
            if matches:
                matched_terms[term] = matches[:10]

        return RootSnapshot(
            html=self._safe_content(root),
            visible_lines=visible_lines,
            buttons=buttons,
            switches=switches,
            radios=radios,
            checkboxes=checkboxes,
            inputs=inputs,
            file_inputs=file_inputs,
            clickables=clickables,
            matched_terms=matched_terms,
        )

    def _collect_terms(self, snapshot: PageSnapshot) -> set[str]:
        terms = set(snapshot.main.matched_terms)
        for root in snapshot.iframe_roots.values():
            terms.update(root.matched_terms)
        return terms

    def _count_file_inputs(self, snapshot: PageSnapshot) -> int:
        count = len(snapshot.main.file_inputs)
        for root in snapshot.iframe_roots.values():
            count += len(root.file_inputs)
        return count

    def _safe_content(self, root: Page | Frame) -> str:
        try:
            return root.content()
        except Error:
            return ""

    def _safe_evaluate(self, root: Page | Frame, script: str, arg: Any) -> Any:
        try:
            return root.evaluate(script, arg)
        except Error:
            return arg if isinstance(arg, (list, dict)) else []

    def _element_from_payload(self, payload: dict[str, Any]) -> ElementInfo:
        return ElementInfo(
            tag=str(payload.get("tag", "")),
            text=str(payload.get("text", "")),
            attrs={str(key): str(value) for key, value in dict(payload.get("attrs", {})).items()},
        )
