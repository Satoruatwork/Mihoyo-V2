"""Font management: one central registry for all typefaces, cached by (family, size, weight)."""

from __future__ import annotations

from enkarender.fonts.manager import FontManager

__all__ = ["FontManager"]
