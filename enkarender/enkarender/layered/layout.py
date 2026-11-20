"""Layout model + JSON loader + resolution scaling.

A layout is pure data: a base canvas resolution plus an ordered list of layer specs. Each
:class:`LayerSpec` carries the generic visual properties every layer understands (position,
size, alignment, font, colour, rotation, scale, opacity, z-index) and a free-form ``props``
bag for type-specific fields (asset name, text template, repeat config, …). Nothing here
draws anything or knows about Pillow — this is the declarative side of the engine.

Automatic scaling: coordinates are authored once against ``base_width``/``base_height``. To
render at another resolution the engine multiplies every geometric value by a single scale
factor via :meth:`LayerSpec.scaled` — the JSON never changes.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

RGBA = tuple[int, int, int, int]

# Keys consumed as first-class LayerSpec fields; everything else in a layer object
# falls through into ``props`` (type-specific configuration).
_FIELD_KEYS = {
    "id", "type", "z", "x", "y", "width", "height", "align",
    "font", "font_size", "color", "rotation", "scale", "opacity",
}


def parse_color(value: str | list | tuple | None, default: RGBA = (0, 0, 0, 0)) -> RGBA:
    """Parse ``#RRGGBB`` / ``#RRGGBBAA`` / ``[r,g,b,a]`` into an RGBA tuple."""
    if value is None:
        return default
    if isinstance(value, (list, tuple)):
        vals = list(value) + [255] * (4 - len(value))
        try:
            # Clamp to 0..255 so out-of-range JSON (e.g. [300, -5, 0]) can't make Pillow raise
            # later and silently drop the whole layer; tolerate non-int elements.
            return tuple(max(0, min(255, int(v))) for v in vals[:4])  # type: ignore[return-value]
        except (TypeError, ValueError):
            return default
    text = str(value).lstrip("#")
    if len(text) == 6:
        text += "ff"
    if len(text) != 8:
        return default
    try:
        return (int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16), int(text[6:8], 16))
    except ValueError:
        return default


@dataclass(slots=True)
class LayerSpec:
    """One layer's declarative configuration."""

    id: str
    type: str
    z: int = 0
    x: float = 0.0
    y: float = 0.0
    width: float = 0.0
    height: float = 0.0
    align: str = "left"           # left / center / right
    font: str = "default"
    font_size: float = 28.0
    color: str = "#FFFFFFFF"
    rotation: float = 0.0         # degrees, counter-clockwise
    scale: float = 1.0
    opacity: float = 1.0          # 0..1
    props: dict[str, Any] = field(default_factory=dict)

    @property
    def rgba(self) -> RGBA:
        return parse_color(self.color, (255, 255, 255, 255))

    def scaled(self, s: float) -> "ScaledGeom":
        """Return pixel geometry for a canvas scale factor ``s``."""
        return ScaledGeom(
            x=int(round(self.x * s)),
            y=int(round(self.y * s)),
            width=int(round(self.width * s * self.scale)),
            height=int(round(self.height * s * self.scale)),
            font_size=max(6, int(round(self.font_size * s))),
        )


@dataclass(slots=True)
class ScaledGeom:
    x: int
    y: int
    width: int
    height: int
    font_size: int


@dataclass(slots=True)
class Layout:
    """A full layout: base resolution + ordered layers + canvas background."""

    base_width: int
    base_height: int
    layers: list[LayerSpec]
    background: str = "#00000000"

    def scale_for(self, target_width: int | None) -> float:
        return 1.0 if not target_width else target_width / self.base_width

    def canvas_size(self, scale: float) -> tuple[int, int]:
        return (int(round(self.base_width * scale)), int(round(self.base_height * scale)))


def parse_layout(raw: dict[str, Any]) -> Layout:
    """Build a :class:`Layout` from a parsed JSON object."""
    layers: list[LayerSpec] = []
    for obj in raw.get("layers", []):
        known = {k: obj[k] for k in _FIELD_KEYS if k in obj}
        props = {k: v for k, v in obj.items() if k not in _FIELD_KEYS}
        layers.append(LayerSpec(**known, props=props))
    return Layout(
        base_width=int(raw.get("base_width", 1000)),
        base_height=int(raw.get("base_height", 1500)),
        background=raw.get("background", "#00000000"),
        layers=layers,
    )


def load_layout(path: str | Path) -> Layout:
    """Load and parse a layout JSON file."""
    with Path(path).open(encoding="utf-8") as fh:
        return parse_layout(json.load(fh))
