"""The render engine.

Turns a Template + RenderContext into PNG bytes. It is completely card-agnostic: it creates
the canvas, applies the template's background, then paints each component in order. It knows
nothing about profiles, builds, or any specific layout — so new templates and card types
require zero changes here.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from enkarender.exceptions import RenderError
from enkarender.logging import get_logger
from enkarender.render.canvas import Canvas

if TYPE_CHECKING:  # avoid a circular import: templates.base imports render.canvas
    from enkarender.templates.base import RenderContext, Template

logger = get_logger("render.engine")


class RenderEngine:
    """Renders any Template of Components. Stateless and reusable."""

    def render(self, template: "Template", ctx: "RenderContext") -> bytes:
        """Render ``template`` with ``ctx`` and return PNG bytes."""
        try:
            canvas = Canvas(template.size, template.background(ctx))
            for component in template.components(ctx):
                component.render(canvas, ctx)
            return canvas.to_png()
        except Exception as exc:  # noqa: BLE001 - surface a typed error to callers
            logger.exception("Render failed for template %s", getattr(template, "key", "?"))
            raise RenderError(f"failed to render {getattr(template, 'key', '?')}: {exc}") from exc


# A shared default engine (stateless, safe to reuse).
engine = RenderEngine()
