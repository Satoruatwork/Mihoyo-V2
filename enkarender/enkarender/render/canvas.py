"""The compositing canvas (image composer).

A thin, ergonomic wrapper around a single RGBA ``PIL.Image`` and its ``ImageDraw`` context.
Components paint through the canvas rather than touching Pillow directly, so the drawing
vocabulary is small, consistent, and centralized. All heavy pixel work delegates to
:class:`~enkarender.render.draw.DrawingUtils`.
"""

from __future__ import annotations

from io import BytesIO

from PIL import Image, ImageDraw

from enkarender.enums import Anchor
from enkarender.render.draw import RGBA, DrawingUtils, Theme


class Canvas:
    """A drawable surface with high-level composition helpers."""

    def __init__(self, size: tuple[int, int], background: RGBA | Image.Image | None = None) -> None:
        self._size = size
        if isinstance(background, Image.Image):
            self._image = DrawingUtils.cover_fit(background.convert("RGBA"), size)
        else:
            self._image = Image.new("RGBA", size, background or (0, 0, 0, 0))
        self._draw = ImageDraw.Draw(self._image)

    @property
    def image(self) -> Image.Image:
        return self._image

    @property
    def draw(self) -> ImageDraw.ImageDraw:
        return self._draw

    @property
    def size(self) -> tuple[int, int]:
        return self._size

    # --- fills / shapes ---
    def fill_gradient(self, top: RGBA, bottom: RGBA) -> None:
        self._image.alpha_composite(DrawingUtils.vertical_gradient(self._size, top, bottom))

    def tint(self, color: RGBA) -> None:
        self._image.alpha_composite(Image.new("RGBA", self._size, color))

    def panel(self, box: tuple[int, int, int, int], theme: Theme, radius: int = 18) -> None:
        DrawingUtils.rounded_rectangle(self._draw, box, radius, fill=theme.panel, outline=theme.accent, width=2)

    def bar(self, box: tuple[int, int, int, int], fraction: float, theme: Theme, radius: int = 6) -> None:
        """Draw a track + filled portion (fraction 0..1)."""
        x0, y0, x1, y1 = box
        DrawingUtils.rounded_rectangle(self._draw, box, radius, fill=(0, 0, 0, 90))
        fill_x1 = x0 + int((x1 - x0) * max(0.0, min(1.0, fraction)))
        if fill_x1 > x0:
            DrawingUtils.rounded_rectangle(self._draw, (x0, y0, fill_x1, y1), radius, fill=theme.accent)

    # --- images ---
    def paste(self, image: Image.Image, position: tuple[int, int]) -> None:
        self._image.alpha_composite(image.convert("RGBA"), dest=position)

    def paste_cover(self, image: Image.Image, box: tuple[int, int, int, int]) -> None:
        x0, y0, x1, y1 = box
        fitted = DrawingUtils.cover_fit(image.convert("RGBA"), (x1 - x0, y1 - y0))
        self._image.alpha_composite(fitted, dest=(x0, y0))

    def paste_circle(self, image: Image.Image, position: tuple[int, int], diameter: int) -> None:
        circ = DrawingUtils.circular(image.convert("RGBA")).resize((diameter, diameter))
        self._image.alpha_composite(circ, dest=position)

    # --- text ---
    def text(self, xy, text: str, font, fill: RGBA, anchor: Anchor = Anchor.LEFT,
             shadow: RGBA | None = None) -> None:
        DrawingUtils.text(self._draw, xy, text, font, fill, anchor, shadow)

    # --- export ---
    def to_png(self) -> bytes:
        buf = BytesIO()
        self._image.save(buf, format="PNG")
        return buf.getvalue()
