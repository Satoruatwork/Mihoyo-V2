"""Fit dynamic text into fixed slots.

Names vary wildly in length — "Mavuika" against "Crimson Moon's Semblance" against
"Fragment of Harmonic Whimsy" — but the panels they sit in never move. So the text adapts,
never the layout: shrink toward the slot's ``min_size``, and only if it still doesn't fit,
truncate with an ellipsis. The result always stays inside ``max_width``, so a long name can
never overlap its neighbour or push a panel out of place.
"""

from __future__ import annotations

from PIL import ImageDraw, ImageFont

from bot.renderer.slot_manager import TextSlot
from bot.utils.logging import get_logger

logger = get_logger(__name__)

_ELLIPSIS = "…"


def _width(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont) -> float:
    return draw.textlength(text, font=font)


def fit_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    slot: TextSlot,
    font_for,
    *,
    scale: float = 1.0,
) -> tuple[str, ImageFont.FreeTypeFont]:
    """Return the string and font that fit ``slot``.

    ``font_for(size, weight)`` supplies fonts. ``scale`` converts slot units into output
    pixels, so a slot measured on the 1280-wide template renders correctly on a 1536-wide
    canvas without changing the recorded coordinates.
    """
    max_width = slot.max_width * scale
    size = max(1, round(slot.size * scale))
    min_size = max(1, round(slot.min_size * scale))

    font = font_for(size, slot.weight)
    if _width(draw, text, font) <= max_width:
        return text, font

    # Step 1: shrink toward the slot's floor.
    while size > min_size:
        size -= 1
        font = font_for(size, slot.weight)
        if _width(draw, text, font) <= max_width:
            return text, font

    # Step 2: still too wide at the minimum size — truncate.
    font = font_for(min_size, slot.weight)
    truncated = text
    while truncated and _width(draw, truncated + _ELLIPSIS, font) > max_width:
        truncated = truncated[:-1]
    result = (truncated + _ELLIPSIS) if truncated else ""
    logger.info("[LAYOUT] Truncated %s: %r -> %r", slot.id, text, result)
    return result, font


def draw_text(
    draw: ImageDraw.ImageDraw,
    text: str | None,
    slot: TextSlot,
    font_for,
    color: tuple[int, int, int],
    *,
    scale: float = 1.0,
) -> None:
    """Draw ``text`` at ``slot``'s anchor, auto-fitted. Empty/None draws nothing."""
    if text is None or text == "":
        return
    fitted, font = fit_text(draw, str(text), slot, font_for, scale=scale)
    if not fitted:
        return
    draw.text(
        (slot.x * scale, slot.y * scale), fitted,
        font=font, fill=color, anchor=slot.pil_anchor,
    )
