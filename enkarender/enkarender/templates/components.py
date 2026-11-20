"""Reusable layout components.

Each component is a pure visual unit: given a Canvas and a RenderContext, it paints itself.
Components take their *layout* (positions/sizes) plus either literal values or a key into
``ctx.data`` / ``ctx.images`` — so a Template binds view-model fields to components in one
place, and the same components compose any card. None of them do I/O or know a card type.
"""

from __future__ import annotations

from PIL import Image

from enkarender.enums import Anchor
from enkarender.render.canvas import Canvas
from enkarender.render.draw import RGBA
from enkarender.templates.base import Component, RenderContext

Box = tuple[int, int, int, int]
Point = tuple[int, int]


class Gradient(Component):
    """A full-canvas vertical gradient from the theme background to a darker shade."""

    def render(self, canvas: Canvas, ctx: RenderContext) -> None:
        r, g, b, a = ctx.theme.bg
        darker = (max(0, r - 14), max(0, g - 14), max(0, b - 14), a)
        canvas.fill_gradient(ctx.theme.bg, darker)


class TintOverlay(Component):
    """Wash the whole canvas in the theme tint (element recolouring)."""

    def render(self, canvas: Canvas, ctx: RenderContext) -> None:
        canvas.tint(ctx.theme.tint)


class Panel(Component):
    """A rounded, themed background panel."""

    def __init__(self, box: Box, radius: int = 18) -> None:
        self._box = box
        self._radius = radius

    def render(self, canvas: Canvas, ctx: RenderContext) -> None:
        canvas.panel(self._box, ctx.theme, self._radius)


class Divider(Component):
    def __init__(self, xy: Point, width: int) -> None:
        self._xy = xy
        self._width = width

    def render(self, canvas: Canvas, ctx: RenderContext) -> None:
        x, y = self._xy
        canvas.draw.line((x, y, x + self._width, y), fill=ctx.theme.accent, width=2)


class Label(Component):
    """A single line of text, optionally shrink-to-fit within ``max_width``."""

    def __init__(
        self,
        xy: Point,
        text: str,
        *,
        size: int = 28,
        weight: int = 400,
        anchor: Anchor = Anchor.LEFT,
        color: RGBA | None = None,
        muted: bool = False,
        shadow: bool = False,
        max_width: int | None = None,
        family: str = "default",
    ) -> None:
        self._xy = xy
        self._text = text
        self._size = size
        self._weight = weight
        self._anchor = anchor
        self._color = color
        self._muted = muted
        self._shadow = shadow
        self._max_width = max_width
        self._family = family

    def render(self, canvas: Canvas, ctx: RenderContext) -> None:
        from enkarender.render.draw import DrawingUtils

        if self._max_width:
            font = DrawingUtils.fit_font(
                ctx.fonts, canvas.draw, self._text, self._max_width, self._size,
                self._weight, self._family,
            )
        else:
            font = ctx.fonts.get(self._size, self._weight, self._family)
        color = self._color or (ctx.theme.muted if self._muted else ctx.theme.text)
        shadow = (0, 0, 0, 140) if self._shadow else None
        canvas.text(self._xy, self._text, font, color, self._anchor, shadow)


class Icon(Component):
    """Paste an image (cover-fit) from ``ctx.images[key]``; themed fallback if absent."""

    def __init__(self, box: Box, image_key: str, *, fallback: str = "") -> None:
        self._box = box
        self._key = image_key
        self._fallback = fallback

    def render(self, canvas: Canvas, ctx: RenderContext) -> None:
        image = ctx.image(self._key)
        if isinstance(image, Image.Image):
            canvas.paste_cover(image, self._box)
        else:
            canvas.panel(self._box, ctx.theme, radius=10)
            if self._fallback:
                x0, y0, x1, y1 = self._box
                Label(((x0 + x1) // 2, (y0 + y1) // 2 - 8), self._fallback,
                      size=16, anchor=Anchor.CENTER, muted=True).render(canvas, ctx)


class CircleImage(Component):
    """A circular portrait/avatar from ``ctx.images[key]`` with a glow backdrop."""

    def __init__(self, position: Point, diameter: int, image_key: str) -> None:
        self._pos = position
        self._d = diameter
        self._key = image_key

    def render(self, canvas: Canvas, ctx: RenderContext) -> None:
        x, y = self._pos
        # glow backdrop
        canvas.draw.ellipse((x - 4, y - 4, x + self._d + 4, y + self._d + 4), fill=ctx.theme.glow)
        image = ctx.image(self._key)
        if isinstance(image, Image.Image):
            canvas.paste_circle(image, self._pos, self._d)
        else:
            canvas.draw.ellipse((x, y, x + self._d, y + self._d), fill=ctx.theme.panel,
                                outline=ctx.theme.accent, width=2)


class StatRow(Component):
    """A label on the left and a value right-aligned within ``width``."""

    def __init__(self, xy: Point, label: str, value: str, width: int, *, size: int = 24) -> None:
        self._xy = xy
        self._label = label
        self._value = value
        self._width = width
        self._size = size

    def render(self, canvas: Canvas, ctx: RenderContext) -> None:
        x, y = self._xy
        font = ctx.fonts.get(self._size)
        canvas.text((x, y), self._label, font, ctx.theme.muted, Anchor.LEFT)
        canvas.text((x + self._width, y), self._value, ctx.fonts.get(self._size, 600),
                    ctx.theme.text, Anchor.RIGHT)


class ProgressBar(Component):
    """A labelled progress/level bar (fraction 0..1)."""

    def __init__(self, box: Box, fraction: float, *, label: str | None = None) -> None:
        self._box = box
        self._fraction = fraction
        self._label = label

    def render(self, canvas: Canvas, ctx: RenderContext) -> None:
        canvas.bar(self._box, self._fraction, ctx.theme)
        if self._label:
            x0, y0, x1, y1 = self._box
            canvas.text(((x0 + x1) // 2, y0 - 2), self._label, ctx.fonts.get(16),
                        ctx.theme.text, Anchor.CENTER)
