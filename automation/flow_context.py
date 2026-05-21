from __future__ import annotations

from dataclasses import dataclass, field
from time import monotonic
from typing import TYPE_CHECKING

from playwright.sync_api import Locator

if TYPE_CHECKING:
    from playwright.sync_api import Frame, Page


FlowRoot = "Page | Frame | Locator"

_IRRELEVANT_FRAME_MARKERS = (
    "chatwoot",
    "stripe",
    "m.stripe.network",
    "widget",
    "intercom",
)


def is_root_live(root: Page | Frame | Locator | None) -> bool:
    if root is None:
        return False
    try:
        if isinstance(root, Locator):
            root.count()
            return True
        root.locator("body").count()
        return True
    except Exception:
        return False


def safe_root_text(root: Page | Frame | Locator | None, *, max_chars: int = 800) -> str:
    if root is None:
        return ""
    try:
        if isinstance(root, Locator):
            return (root.inner_text(timeout=250) or "").strip()[:max_chars]
        return (root.locator("body").inner_text(timeout=250) or "").strip()[:max_chars]
    except Exception:
        return ""


def describe_root(root: Page | Frame | Locator | None) -> str:
    if root is None:
        return "sin contexto"
    try:
        if isinstance(root, Locator):
            tag_name = root.evaluate("node => (node.tagName || '').toLowerCase()")
            role = root.get_attribute("role") or ""
            classes = root.get_attribute("class") or ""
            return f"locator tag={tag_name or '-'} role={role or '-'} class={classes[:80] or '-'}".strip()
        url = str(getattr(root, "url", "") or "").strip()
        return f"frame/page url={url or '-'}"
    except Exception:
        return root.__class__.__name__


def should_ignore_frame(frame: Frame | None) -> bool:
    if frame is None:
        return True
    url = str(getattr(frame, "url", "") or "").strip().lower()
    try:
        title = str(frame.page.title() or "").strip().lower()
    except Exception:
        title = ""
    return any(marker in url or marker in title for marker in _IRRELEVANT_FRAME_MARKERS)


def resolve_live_flow_context(
    page: Page,
    *,
    candidates: list[tuple[Page | Frame | Locator | None, str]],
    stage: str,
) -> ActiveFlowContext | None:
    for root, source in candidates:
        if root is None:
            continue
        if not is_root_live(root):
            continue
        if not isinstance(root, Locator) and should_ignore_frame(root if root is not page else None):
            continue
        snapshot = safe_root_text(root)
        return ActiveFlowContext(
            page=page,
            root=root,
            source=source,
            stage=stage,
            text_snapshot=snapshot or None,
        )
    return None


@dataclass
class ActiveFlowContext:
    page: Page
    root: Page | Frame | Locator
    source: str
    stage: str
    detected_at: float = field(default_factory=monotonic)
    last_seen_at: float = field(default_factory=monotonic)
    text_snapshot: str | None = None

    def touch(self) -> None:
        self.last_seen_at = monotonic()

    def is_valid(self) -> bool:
        valid = is_root_live(self.root)
        if valid:
            self.touch()
        return valid

    def is_detached_safe(self) -> bool:
        return not is_root_live(self.root)

    def describe(self) -> str:
        return f"{self.source} | {self.stage} | {describe_root(self.root)}"
