"""Loads the static base template, cached in-process.

The template is bundled in the repo (``assets/templates/character_card_base.jpg``) so
rendering never depends on an external URL at request time.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from PIL import Image

from bot.config import ROOT_DIR
from bot.utils.logging import get_logger

logger = get_logger(__name__)

BASE_TEMPLATE = ROOT_DIR / "assets" / "templates" / "character_card_base.jpg"
_FALLBACK = ROOT_DIR / "assets" / "ui" / "character_card_template.jpg"


@lru_cache(maxsize=1)
def load_base_template(path: Path | None = None) -> Image.Image:
    """Return the static template. Falls back to a flat panel if the asset is missing."""
    for candidate in (path, BASE_TEMPLATE, _FALLBACK):
        if candidate is None or not candidate.exists():
            continue
        try:
            return Image.open(candidate).convert("RGBA")
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not load template %s: %s", candidate, exc)
    logger.error("No card template available — rendering on a plain background")
    return Image.new("RGBA", (1280, 720), (32, 30, 40, 255))
