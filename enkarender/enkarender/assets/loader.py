"""Resource loader: turn asset URLs into decoded, memory-cached ``PIL.Image`` objects.

Sits between the byte layer (Downloader + disk cache) and the render layer. Decoded images
are kept in the in-memory LRU so repeat renders never re-decode. A generated placeholder is
always available, so the renderer can rely on receiving *some* image.
"""

from __future__ import annotations

from PIL import Image, ImageDraw

from enkarender.assets.cache import CacheManager
from enkarender.assets.downloader import Downloader
from enkarender.logging import get_logger

logger = get_logger("assets.loader")


class ResourceLoader:
    """Load and cache decoded images, with a guaranteed placeholder fallback."""

    def __init__(self, downloader: Downloader, cache: CacheManager) -> None:
        self._downloader = downloader
        self._cache = cache

    async def load_image(self, url: str | None) -> Image.Image | None:
        """Return a decoded RGBA image for ``url`` (memory-cached), or ``None``."""
        if not url:
            return None
        cached = self._cache.get_image(url)
        if cached is not None:
            return cached

        data = await self._downloader.fetch(url)
        if not data:
            return None
        try:
            from io import BytesIO

            image = Image.open(BytesIO(data)).convert("RGBA")
        except Exception as exc:  # noqa: BLE001 - corrupt/unsupported asset
            logger.debug("Decode failed for %s: %s", url, exc)
            return None
        self._cache.put_image(url, image)
        return image

    @staticmethod
    def placeholder(size: tuple[int, int], label: str = "") -> Image.Image:
        """Generate an obvious in-memory placeholder (never a hidden blank)."""
        w, h = size
        img = Image.new("RGBA", size, (44, 46, 60, 255))
        draw = ImageDraw.Draw(img)
        draw.rectangle([0, 0, w - 1, h - 1], outline=(110, 120, 160, 255), width=2)
        draw.line([0, 0, w, h], fill=(110, 120, 160, 120), width=1)
        if label:
            draw.text((6, 6), label[:18], fill=(210, 214, 230, 255))
        return img
