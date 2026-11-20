"""Dynamic asset loading with placeholder fallback.

Artwork/icons/frames are added manually later. Nothing hardcodes an image path — the
renderer asks the loader for an asset by ``(category, name)`` and always gets *something*
back: the real file if present, otherwise a placeholder. A missing asset must never crash
the bot.

If even the placeholder file is absent, a simple placeholder image is generated in memory,
so the renderer can rely on always receiving a valid ``PIL.Image``.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

from bot.config import get_settings
from bot.utils.logging import get_logger

logger = get_logger(__name__)

# Known asset categories (mirror the assets/ directory layout).
CATEGORIES = (
    "backgrounds",
    "characters",
    "frames",
    "icons",
    "buttons",
    "ui",
    "placeholders",
)

# Extensions tried (in order) when a name is given without one.
_EXTENSIONS = (".png", ".webp", ".jpg", ".jpeg")

_PLACEHOLDER_NAME = "default.png"


class AssetLoader:
    """Resolves and loads assets from the configured assets directory."""

    def __init__(self, root: Path | None = None) -> None:
        self._root = root or get_settings().assets_path

    @property
    def root(self) -> Path:
        return self._root

    def resolve(self, category: str, name: str) -> Path | None:
        """Return the path to an asset, or ``None`` if it can't be found.

        ``name`` may include an extension or not. If not, common image extensions are
        tried in order.
        """
        base = self._root / category
        candidate = base / name
        # Only treat a trailing ``.xxx`` as an extension if it's a known image
        # extension; otherwise it's part of the stem (e.g. ``char_1.2``) and must
        # not be stripped, or the asset can never be resolved.
        known_suffix = candidate.suffix.lower() in _EXTENSIONS
        if known_suffix and candidate.exists():
            return candidate
        # No/unknown extension: try known image extensions on the full name.
        stem = name
        if known_suffix:
            stem = name[: -len(candidate.suffix)]
        for ext in _EXTENSIONS:
            p = base / f"{stem}{ext}"
            if p.exists():
                return p
        return None

    def placeholder_path(self) -> Path | None:
        """Return the placeholder asset path if it exists on disk."""
        p = self._root / "placeholders" / _PLACEHOLDER_NAME
        return p if p.exists() else None

    def load(self, category: str, name: str, *, size: tuple[int, int] | None = None) -> Image.Image:
        """Load an asset as a ``PIL.Image``.

        Falls back to the on-disk placeholder, then to a generated placeholder, so the
        return value is always a valid image. Optionally resizes to ``size``.
        """
        path = self.resolve(category, name)
        img: Image.Image | None = None
        if path is not None:
            try:
                img = Image.open(path).convert("RGBA")
            except (OSError, ValueError) as exc:
                logger.warning("Failed to open asset %s: %s", path, exc)
                img = None
        if img is None:
            logger.debug("Asset missing (%s/%s); using placeholder", category, name)
            img = self._load_placeholder(size or (256, 256))
        if size is not None:
            img = img.resize(size)
        return img

    def _load_placeholder(self, size: tuple[int, int]) -> Image.Image:
        path = self.placeholder_path()
        if path is not None:
            try:
                return Image.open(path).convert("RGBA")
            except (OSError, ValueError) as exc:
                logger.warning("Failed to open placeholder %s: %s", path, exc)
        return self._generate_placeholder(size)

    @staticmethod
    def _generate_placeholder(size: tuple[int, int]) -> Image.Image:
        """Create a simple checker/labelled placeholder image in memory."""
        w, h = size
        img = Image.new("RGBA", size, (40, 42, 54, 255))
        draw = ImageDraw.Draw(img)
        # Border + diagonal to make it obviously a placeholder.
        draw.rectangle([0, 0, w - 1, h - 1], outline=(98, 114, 164, 255), width=3)
        draw.line([0, 0, w, h], fill=(98, 114, 164, 255), width=2)
        draw.line([0, h, w, 0], fill=(98, 114, 164, 255), width=2)
        draw.text((8, 8), "placeholder", fill=(248, 248, 242, 255))
        return img


# Module-level default loader for convenience.
_default_loader: AssetLoader | None = None


def get_asset_loader() -> AssetLoader:
    """Return a shared default :class:`AssetLoader`."""
    global _default_loader
    if _default_loader is None:
        _default_loader = AssetLoader()
    return _default_loader
