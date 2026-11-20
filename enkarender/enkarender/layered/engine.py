"""The layered rendering engine.

Builds the canvas at any target resolution, then stacks each layer in z-index order by
delegating to the per-type renderer. It contains **no** coordinates, asset names, or layout
knowledge — all of that lives in the JSON layout and the asset folders, so an entirely new
card is "new JSON + new assets", never new code.
"""

from __future__ import annotations

from io import BytesIO
from typing import Any

from PIL import Image

from enkarender.layered.assets import LayeredAssetManager
from enkarender.layered.layers import REGISTRY, RenderScope
from enkarender.layered.layout import Layout, parse_color
from enkarender.logging import get_logger

logger = get_logger("layered.engine")


class LayeredRenderer:
    """Stacks configurable layers into a composited card. Stateless across renders."""

    def __init__(self, assets: LayeredAssetManager, registry: dict | None = None) -> None:
        self._assets = assets
        self._registry = registry or REGISTRY

    def render(self, layout: Layout, data: dict[str, Any], *, target_width: int | None = None) -> Image.Image:
        """Render ``layout`` with ``data`` and return the composited RGBA image.

        ``target_width`` renders at an arbitrary resolution; every coordinate/size/font is
        scaled by one factor so the same layout works at any resolution unchanged.
        """
        scale = layout.scale_for(target_width)
        canvas_size = layout.canvas_size(scale)
        base = Image.new("RGBA", canvas_size, parse_color(layout.background, (0, 0, 0, 0)))
        scope = RenderScope(scale=scale, assets=self._assets, data=data)

        for spec in sorted(layout.layers, key=lambda s: s.z):
            renderer = self._registry.get(spec.type)
            if renderer is None:
                logger.debug("No renderer for layer type %r (id=%s); skipping", spec.type, spec.id)
                continue
            try:
                renderer.render(base, spec, scope)
            except Exception as exc:  # noqa: BLE001 - one bad layer must not sink the card
                logger.warning("Layer %s (%s) failed: %s", spec.id, spec.type, exc)
        return base

    def render_png(self, layout: Layout, data: dict[str, Any], *, target_width: int | None = None) -> bytes:
        """Render and encode to PNG bytes."""
        buf = BytesIO()
        self.render(layout, data, target_width=target_width).save(buf, format="PNG")
        return buf.getvalue()
