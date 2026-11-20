"""Fit images into fixed slots without ever distorting them.

Every image on the card goes through here, so scaling/clipping rules live in one place
instead of being re-invented per call site. Aspect ratio is always preserved: a slot decides
the *box*, never the proportions of what goes in it.

Character splash art needs one extra step. Enka's artwork is a 2048x1024 sheet where the
character occupies an arbitrary sub-region surrounded by transparency, and that padding
differs per character — so scaling the raw file into the frame makes some characters tiny
and others huge. Trimming to the visible pixels first is what lets a single automatic rule
place every character consistently, including ones released after this code was written.
"""

from __future__ import annotations

from dataclasses import dataclass

from PIL import Image, ImageDraw

from bot.utils.logging import get_logger

logger = get_logger(__name__)

# Alpha at or below this counts as transparent when locating the visible artwork.
_ALPHA_THRESHOLD = 8


@dataclass(frozen=True, slots=True)
class Adjustment:
    """Optional per-character correction applied on top of automatic fitting."""

    scale: float = 1.0
    x_offset: int = 0
    y_offset: int = 0


DEFAULT_ADJUSTMENT = Adjustment()


def trim_transparent(img: Image.Image) -> Image.Image:
    """Crop away fully transparent padding, keeping the visible artwork only."""
    if img.mode != "RGBA":
        return img
    alpha = img.getchannel("A")
    bbox = alpha.point(lambda a: 255 if a > _ALPHA_THRESHOLD else 0).getbbox()
    if bbox is None or bbox == (0, 0, img.width, img.height):
        return img
    return img.crop(bbox)


def fit(
    img: Image.Image,
    width: int,
    height: int,
    *,
    mode: str = "contain",
    adjustment: Adjustment = DEFAULT_ADJUSTMENT,
) -> Image.Image:
    """Scale ``img`` into a ``width`` x ``height`` box, preserving aspect ratio.

    ``contain`` fits the whole image inside the box; ``cover`` fills the box and lets the
    clip crop the overflow. Never stretches — one ratio is applied to both axes.
    """
    if img.width <= 0 or img.height <= 0 or width <= 0 or height <= 0:
        return img
    ratio_w, ratio_h = width / img.width, height / img.height
    ratio = min(ratio_w, ratio_h) if mode == "contain" else max(ratio_w, ratio_h)
    ratio *= max(0.05, adjustment.scale)
    size = (max(1, round(img.width * ratio)), max(1, round(img.height * ratio)))
    return img.resize(size, Image.LANCZOS)


def _clip_mask(size: tuple[int, int], shape: str) -> Image.Image | None:
    """Alpha mask for a clip shape, or None when no clipping is needed."""
    if shape == "rect":
        return None
    mask = Image.new("L", size, 0)
    draw = ImageDraw.Draw(mask)
    if shape == "circle":
        draw.ellipse((0, 0, size[0] - 1, size[1] - 1), fill=255)
    elif shape == "stadium":
        # A rounded rectangle whose radius is half its width — the frame's pill window.
        draw.rounded_rectangle((0, 0, size[0] - 1, size[1] - 1), radius=size[0] // 2, fill=255)
    else:
        return None
    return mask


def paste_into(
    base: Image.Image,
    img: Image.Image | None,
    box: tuple[int, int, int, int],
    *,
    mode: str = "contain",
    clip: str = "rect",
    align: str = "center",
    adjustment: Adjustment = DEFAULT_ADJUSTMENT,
) -> bool:
    """Fit ``img`` into ``box`` on ``base``. Returns whether anything was drawn.

    ``align`` controls vertical placement inside the box: ``center`` or ``bottom``. A missing
    image is a no-op, never an error — the slot simply stays empty.
    """
    if img is None:
        return False
    x0, y0, x1, y1 = box
    width, height = x1 - x0, y1 - y0
    if width <= 0 or height <= 0:
        return False

    art = trim_transparent(img.convert("RGBA"))
    art = fit(art, width, height, mode=mode, adjustment=adjustment)

    # Centre horizontally; vertically centre or sit on the box's floor.
    px = x0 + (width - art.width) // 2 + adjustment.x_offset
    py = (y1 - art.height if align == "bottom" else y0 + (height - art.height) // 2)
    py += adjustment.y_offset

    mask = _clip_mask((width, height), clip)
    if mask is None:
        base.alpha_composite(art, (px, py))
        return True

    # Compose into a box-sized layer first so the clip shape applies to the slot, not the
    # artwork — that way overflow from a "cover" fit is cropped by the frame as intended.
    layer = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    layer.alpha_composite(art, (px - x0, py - y0))
    layer.putalpha(Image.composite(layer.getchannel("A"), Image.new("L", (width, height), 0), mask))
    base.alpha_composite(layer, (x0, y0))
    return True
