"""Drawing utilities and theming.

``DrawingUtils`` is a stateless collection of low-level Pillow helpers (rounded rectangles,
gradients, cover-fit pasting, circular masks, shadowed text, text measurement). ``Theme``
plus :func:`theme_for` provide a per-element colour palette so cards are recoloured by data
without any template change.

Colours are RGBA tuples throughout.
"""

from __future__ import annotations

from dataclasses import dataclass

from PIL import Image, ImageDraw, ImageFont

from enkarender.enums import Anchor, Element

RGBA = tuple[int, int, int, int]


@dataclass(frozen=True, slots=True)
class Theme:
    """A card colour palette. Element themes only change the accent/tint/glow."""

    bg: RGBA = (26, 27, 38, 255)
    panel: RGBA = (36, 38, 52, 235)
    accent: RGBA = (110, 120, 170, 255)
    text: RGBA = (240, 242, 250, 255)
    muted: RGBA = (150, 156, 184, 255)
    tint: RGBA = (110, 120, 170, 40)
    glow: RGBA = (110, 120, 170, 120)


_ELEMENT_ACCENT: dict[Element, RGBA] = {
    Element.PYRO: (236, 110, 90, 255),
    Element.HYDRO: (80, 170, 230, 255),
    Element.ELECTRO: (180, 130, 220, 255),
    Element.CRYO: (140, 210, 225, 255),
    Element.ANEMO: (110, 205, 175, 255),
    Element.GEO: (225, 180, 90, 255),
    Element.DENDRO: (140, 195, 90, 255),
    Element.UNKNOWN: (110, 120, 170, 255),
}


def theme_for(element: Element) -> Theme:
    """Return a Theme whose accent/tint/glow match ``element`` (base colours unchanged)."""
    accent = _ELEMENT_ACCENT.get(element, _ELEMENT_ACCENT[Element.UNKNOWN])
    r, g, b, _ = accent
    return Theme(accent=accent, tint=(r, g, b, 38), glow=(r, g, b, 130))


class DrawingUtils:
    """Stateless Pillow helpers. All methods are static."""

    @staticmethod
    def rounded_rectangle(
        draw: ImageDraw.ImageDraw,
        box: tuple[int, int, int, int],
        radius: int,
        fill: RGBA | None = None,
        outline: RGBA | None = None,
        width: int = 1,
    ) -> None:
        draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)

    @staticmethod
    def vertical_gradient(size: tuple[int, int], top: RGBA, bottom: RGBA) -> Image.Image:
        """Create a top->bottom linear gradient image."""
        w, h = size
        base = Image.new("RGBA", size, top)
        top_r, top_g, top_b, top_a = top
        bot_r, bot_g, bot_b, bot_a = bottom
        grad = Image.new("RGBA", (1, h))
        for y in range(h):
            t = y / max(1, h - 1)
            grad.putpixel((0, y), (
                int(top_r + (bot_r - top_r) * t),
                int(top_g + (bot_g - top_g) * t),
                int(top_b + (bot_b - top_b) * t),
                int(top_a + (bot_a - top_a) * t),
            ))
        base.alpha_composite(grad.resize(size))
        return base

    @staticmethod
    def cover_fit(image: Image.Image, box_size: tuple[int, int]) -> Image.Image:
        """Scale+crop ``image`` to fully cover ``box_size`` while preserving aspect ratio."""
        bw, bh = box_size
        iw, ih = image.size
        if iw == 0 or ih == 0:
            return image.resize(box_size)
        scale = max(bw / iw, bh / ih)
        resized = image.resize((max(1, int(iw * scale)), max(1, int(ih * scale))))
        left = (resized.width - bw) // 2
        top = (resized.height - bh) // 2
        return resized.crop((left, top, left + bw, top + bh))

    @staticmethod
    def circular(image: Image.Image) -> Image.Image:
        """Return ``image`` with a circular alpha mask applied."""
        size = min(image.size)
        square = DrawingUtils.cover_fit(image, (size, size))
        mask = Image.new("L", (size, size), 0)
        ImageDraw.Draw(mask).ellipse((0, 0, size, size), fill=255)
        out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        out.paste(square, (0, 0), mask)
        return out

    @staticmethod
    def text_size(draw: ImageDraw.ImageDraw, text: str, font) -> tuple[int, int]:
        left, top, right, bottom = draw.textbbox((0, 0), text, font=font)
        return right - left, bottom - top

    @staticmethod
    def text(
        draw: ImageDraw.ImageDraw,
        xy: tuple[int, int],
        text: str,
        font,
        fill: RGBA,
        anchor: Anchor = Anchor.LEFT,
        shadow: RGBA | None = None,
    ) -> None:
        x, y = xy
        if anchor is not Anchor.LEFT:
            w, _ = DrawingUtils.text_size(draw, text, font)
            x = x - w if anchor is Anchor.RIGHT else x - w // 2
        if shadow is not None:
            draw.text((x + 2, y + 2), text, font=font, fill=shadow)
        draw.text((x, y), text, font=font, fill=fill)

    @staticmethod
    def fit_font(font_manager, draw, text, max_width, base_size, weight=400, family="default"):
        """Shrink a font until ``text`` fits ``max_width`` (min size 10)."""
        size = base_size
        while size > 10:
            font = font_manager.get(size, weight, family)
            if DrawingUtils.text_size(draw, text, font)[0] <= max_width:
                return font
            size -= 2
        return font_manager.get(10, weight, family)
