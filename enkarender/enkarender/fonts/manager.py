"""Central font manager.

Every piece of text in the engine asks the :class:`FontManager` for a font — no module loads
``ImageFont`` itself. Fonts are registered by *family* (a logical name mapping to a ``.ttf``
file) and cached by ``(family, size, weight)`` so a given face+size is only opened once.
Missing font files degrade to Pillow's default font, so rendering never fails on typography.
"""

from __future__ import annotations

from pathlib import Path

from PIL import ImageFont

from enkarender.config import Settings, default_settings
from enkarender.logging import get_logger

logger = get_logger("fonts.manager")

FontLike = ImageFont.FreeTypeFont | ImageFont.ImageFont

DEFAULT_FAMILY = "default"


class FontManager:
    """Registers font families and hands out cached, sized font objects."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or default_settings
        self._families: dict[str, Path] = {}
        self._cache: dict[tuple[str, int, int], FontLike] = {}
        self._autodiscover()

    def _autodiscover(self) -> None:
        """Register any ``*.ttf``/``*.otf`` in the font dir; ``default.*`` becomes DEFAULT."""
        font_dir = self._settings.font_dir
        if not font_dir.exists():
            return
        for path in sorted(font_dir.glob("*.tt[fc]")) + sorted(font_dir.glob("*.otf")):
            self._families.setdefault(path.stem.lower(), path)
        if "default" not in self._families and self._families:
            # Promote the first discovered face to the default family.
            first = next(iter(self._families.values()))
            self._families[DEFAULT_FAMILY] = first

    def register(self, family: str, path: str | Path) -> None:
        """Register (or override) a font family with a file path."""
        self._families[family.lower()] = Path(path)

    def get(self, size: int, weight: int = 400, family: str = DEFAULT_FAMILY) -> FontLike:
        """Return a cached font for ``family`` at ``size`` (weight applied to variable fonts)."""
        family = family.lower()
        key = (family, size, weight)
        cached = self._cache.get(key)
        if cached is not None:
            return cached

        font = self._load(family, size, weight)
        self._cache[key] = font
        return font

    def _load(self, family: str, size: int, weight: int) -> FontLike:
        path = self._families.get(family) or self._families.get(DEFAULT_FAMILY)
        if path is None:
            return ImageFont.load_default()
        try:
            font = ImageFont.truetype(str(path), size)
            try:
                font.set_variation_by_axes([weight])  # no-op for non-variable fonts
            except Exception:  # noqa: BLE001
                pass
            return font
        except (OSError, ValueError) as exc:
            logger.debug("Font load failed (%s @ %d): %s; using default", family, size, exc)
            return ImageFont.load_default()

    @property
    def families(self) -> list[str]:
        return sorted(self._families)
