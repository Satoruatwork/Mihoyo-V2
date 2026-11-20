"""Folder-based asset location + caching, and low-level layer compositing helpers.

The :class:`LayeredAssetManager` resolves an asset by ``(category, name)`` against the
conventional folders (``backgrounds/``, ``frames/``, ``icons/``, ``weapons/``, ``artifacts/``,
``elements/``, ``fonts/``, ``effects/`` …), trying common image extensions, and keeps decoded
images in an in-memory LRU so repeated icons/frames/backgrounds are never re-read from disk.
A generated placeholder is always available, so a missing asset degrades gracefully.

The ``compose_*`` helpers implement the Photoshop-style per-layer transforms (scale-to-fit,
rotation, opacity) and alpha-composite a layer sprite onto the base canvas.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

from enkarender.assets.cache import CacheManager
from enkarender.config import Settings, default_settings
from enkarender.fonts.manager import FontManager
from enkarender.logging import get_logger

logger = get_logger("layered.assets")

_EXTENSIONS = (".png", ".webp", ".jpg", ".jpeg")

# Category -> folder name (identity mapping today, but centralized so it can diverge).
CATEGORIES = (
    "backgrounds", "frames", "panels", "icons", "weapons", "artifacts",
    "elements", "effects", "characters", "fonts", "footer", "overlays",
)


class LayeredAssetManager:
    """Locates, loads, and caches assets from the conventional asset folders."""

    def __init__(
        self,
        base_dir: str | Path,
        cache: CacheManager | None = None,
        fonts: FontManager | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._base = Path(base_dir)
        self._settings = settings or default_settings
        self._cache = cache or CacheManager(self._settings)
        self.fonts = fonts or FontManager(self._settings)
        self.register_fonts()

    # --- fonts ---
    def register_fonts(self) -> None:
        """Register every font file in ``fonts/`` with the font manager by its stem.

        The first discovered face also becomes the ``default`` family if none is set yet.
        """
        font_dir = self._base / "fonts"
        if not font_dir.is_dir():
            return
        discovered = sorted(font_dir.glob("*.tt[fc]")) + sorted(font_dir.glob("*.otf"))
        for path in discovered:
            self.fonts.register(path.stem, path)
        if discovered and "default" not in self.fonts.families:
            self.fonts.register("default", discovered[0])

    # --- images ---
    def locate(self, category: str, name: str) -> Path | None:
        """Return the path to an asset, trying known extensions; ``None`` if not found."""
        if not name:
            return None
        base = self._base / category
        candidate = base / name
        if candidate.suffix.lower() in _EXTENSIONS and candidate.exists():
            return candidate
        for ext in _EXTENSIONS:
            p = base / f"{name}{ext}"
            if p.exists():
                return p
        return candidate if candidate.exists() else None

    def load(self, category: str, name: str) -> Image.Image | None:
        """Load a decoded RGBA image (memory-cached), or ``None`` if unavailable."""
        key = f"{category}/{name}"
        cached = self._cache.get_image(key)
        if cached is not None:
            return cached
        path = self.locate(category, name)
        if path is None:
            return None
        try:
            image = Image.open(path).convert("RGBA")
        except Exception as exc:  # noqa: BLE001
            logger.debug("Failed to decode %s: %s", path, exc)
            return None
        self._cache.put_image(key, image)
        return image

    def load_or_placeholder(self, category: str, name: str, size: tuple[int, int]) -> Image.Image:
        img = self.load(category, name)
        return img if img is not None else placeholder(size, name or category)


def placeholder(size: tuple[int, int], label: str = "") -> Image.Image:
    """An obvious, never-blank placeholder sprite."""
    w, h = max(1, size[0]), max(1, size[1])
    img = Image.new("RGBA", (w, h), (48, 50, 66, 210))
    draw = ImageDraw.Draw(img)
    draw.rectangle([0, 0, w - 1, h - 1], outline=(120, 130, 170, 255), width=max(1, w // 60))
    if label:
        draw.text((5, 5), label[:20], fill=(200, 205, 225, 255))
    return img


# --------------------------------------------------------------------------- compositing
def contain_fit(image: Image.Image, box: tuple[int, int]) -> Image.Image:
    """Scale ``image`` to fit *inside* ``box`` preserving aspect ratio (no crop)."""
    bw, bh = box
    iw, ih = image.size
    if iw == 0 or ih == 0 or bw == 0 or bh == 0:
        return image
    scale = min(bw / iw, bh / ih)
    return image.resize((max(1, int(iw * scale)), max(1, int(ih * scale))))


def apply_opacity(image: Image.Image, opacity: float) -> Image.Image:
    """Return ``image`` with its alpha channel multiplied by ``opacity`` (0..1)."""
    if opacity >= 1.0:
        return image
    image = image.convert("RGBA")
    alpha = image.getchannel("A").point(lambda a: int(a * max(0.0, min(1.0, opacity))))
    image.putalpha(alpha)
    return image


def compose(
    base: Image.Image,
    sprite: Image.Image,
    x: int,
    y: int,
    *,
    rotation: float = 0.0,
    opacity: float = 1.0,
) -> None:
    """Composite ``sprite`` onto ``base`` at ``(x, y)`` with optional rotation + opacity.

    Rotation expands the sprite and re-centres it on the original box so a rotated layer
    stays anchored where it was authored.
    """
    sprite = sprite.convert("RGBA")
    if opacity < 1.0:
        sprite = apply_opacity(sprite, opacity)
    if rotation:
        w0, h0 = sprite.size
        sprite = sprite.rotate(rotation, expand=True, resample=Image.Resampling.BICUBIC)
        x -= (sprite.width - w0) // 2
        y -= (sprite.height - h0) // 2
    base.alpha_composite(sprite, dest=(int(x), int(y)))
