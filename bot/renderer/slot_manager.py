"""Machine-readable layout: parses ``templates/character_card.svg`` into typed slots.

This is what makes the card a *layout* rather than an image with things drawn on top. Every
position, size, anchor and fit rule lives in the SVG; the renderer looks slots up by name and
can never invent a coordinate. Changing the design means editing the SVG, not the code.

Two slot kinds:
    :class:`TextSlot`  — x/y anchor plus the type rules needed to fit text into a fixed box.
    :class:`ImageSlot` — a box plus how an image should be fitted and clipped into it.

The SVG's ``viewBox`` is the template's native pixel space, while ``width``/``height`` are the
output size. :attr:`Layout.scale` is the ratio between them, so a renderer working in native
coordinates can scale its result up to the required output resolution.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from bot.utils.logging import get_logger

logger = get_logger(__name__)

_SVG_NS = "{http://www.w3.org/2000/svg}"
TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"
TEMPLATE_FILE = TEMPLATE_DIR / "character_card.svg"


@dataclass(frozen=True, slots=True)
class TextSlot:
    """A text anchor with everything needed to fit a string into a fixed region."""

    id: str
    x: float
    y: float
    anchor: str = "start"        # start | middle | end
    size: int = 16
    max_width: float = 200.0
    min_size: int = 10
    weight: int = 400

    @property
    def pil_anchor(self) -> str:
        """Pillow anchor for this slot (horizontal from anchor, vertical always middle)."""
        return {"start": "lm", "middle": "mm", "end": "rm"}.get(self.anchor, "lm")


@dataclass(frozen=True, slots=True)
class ImageSlot:
    """A box an image is fitted into, plus how it should be clipped."""

    id: str
    x: float
    y: float
    width: float
    height: float
    fit: str = "contain"         # contain (whole image visible) | cover (fills, crops)
    clip: str = "rect"           # rect | circle | stadium

    @property
    def box(self) -> tuple[int, int, int, int]:
        """(left, top, right, bottom) in template pixels."""
        return (int(self.x), int(self.y), int(self.x + self.width), int(self.y + self.height))

    @property
    def center(self) -> tuple[int, int]:
        return (int(self.x + self.width / 2), int(self.y + self.height / 2))


@dataclass(frozen=True, slots=True)
class Layout:
    """The parsed template: named slots plus the canvas geometry."""

    view_width: int
    view_height: int
    out_width: int
    out_height: int
    text: dict[str, TextSlot]
    images: dict[str, ImageSlot]

    @property
    def scale(self) -> float:
        """Output pixels per template pixel (e.g. 1536/1280 == 1.2)."""
        return self.out_width / self.view_width

    def text_slot(self, slot_id: str) -> TextSlot | None:
        slot = self.text.get(slot_id)
        if slot is None:
            logger.warning("[LAYOUT] Unknown text slot: %s", slot_id)
        return slot

    def image_slot(self, slot_id: str) -> ImageSlot | None:
        slot = self.images.get(slot_id)
        if slot is None:
            logger.warning("[LAYOUT] Unknown image slot: %s", slot_id)
        return slot

    def artifact_slots(self, slot: str) -> dict[str, object]:
        """All slots belonging to one artifact position, keyed by their short role."""
        prefix = f"artifact-{slot}-"
        out: dict[str, object] = {}
        for key, value in {**self.text, **self.images}.items():
            if key.startswith(prefix):
                out[key[len(prefix):]] = value
        return out


def _f(el: ET.Element, name: str, default: float) -> float:
    try:
        return float(el.get(name, default))
    except (TypeError, ValueError):
        return default


def _i(el: ET.Element, name: str, default: int) -> int:
    return int(_f(el, name, default))


def _parse_size(value: str | None, default: int) -> int:
    """Read a length that may carry a unit suffix (e.g. '1536', '1536px')."""
    if not value:
        return default
    text = value.strip().removesuffix("px").strip()
    try:
        return int(float(text))
    except ValueError:
        return default


def load_layout(path: Path | None = None) -> Layout:
    """Parse the SVG template into a :class:`Layout`. Raises if it is missing/invalid."""
    path = path or TEMPLATE_FILE
    root = ET.parse(path).getroot()

    view = (root.get("viewBox") or "0 0 1280 720").split()
    view_w, view_h = int(float(view[2])), int(float(view[3]))
    out_w = _parse_size(root.get("width"), view_w)
    out_h = _parse_size(root.get("height"), view_h)

    text: dict[str, TextSlot] = {}
    images: dict[str, ImageSlot] = {}
    for el in root.iter():
        slot_id = el.get("id")
        # Only elements inside the dynamic layer carry slot metadata; the static layer's
        # image has no data-* attributes and is skipped by these checks.
        if not slot_id:
            continue
        if el.tag == f"{_SVG_NS}text":
            text[slot_id] = TextSlot(
                id=slot_id, x=_f(el, "x", 0), y=_f(el, "y", 0),
                anchor=el.get("data-anchor", "start"),
                size=_i(el, "data-size", 16),
                max_width=_f(el, "data-max-width", 200),
                min_size=_i(el, "data-min-size", 10),
                weight=_i(el, "data-weight", 400),
            )
        elif el.tag == f"{_SVG_NS}rect" and el.get("data-fit"):
            images[slot_id] = ImageSlot(
                id=slot_id, x=_f(el, "x", 0), y=_f(el, "y", 0),
                width=_f(el, "width", 0), height=_f(el, "height", 0),
                fit=el.get("data-fit", "contain"),
                clip=el.get("data-clip", "rect"),
            )

    logger.info(
        "[LAYOUT] Loaded %s: %dx%d -> %dx%d, %d text slots, %d image slots",
        path.name, view_w, view_h, out_w, out_h, len(text), len(images),
    )
    return Layout(view_w, view_h, out_w, out_h, text, images)


@lru_cache(maxsize=1)
def get_layout() -> Layout:
    """Cached layout — the template is static, so it is parsed once per process."""
    return load_layout()
