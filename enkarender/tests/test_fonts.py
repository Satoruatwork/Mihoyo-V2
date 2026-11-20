"""FontManager: caching and graceful fallback."""

from __future__ import annotations

from enkarender.config import Settings
from enkarender.fonts.manager import FontManager


def test_get_is_cached(tmp_path):
    fonts = FontManager(Settings(home=tmp_path))
    a = fonts.get(24)
    b = fonts.get(24)
    assert a is b  # same (family,size,weight) -> identical cached object


def test_different_sizes_are_distinct(tmp_path):
    fonts = FontManager(Settings(home=tmp_path))
    assert fonts.get(24) is not fonts.get(32)


def test_missing_font_falls_back(tmp_path):
    fonts = FontManager(Settings(home=tmp_path))
    # No font files present -> default font, never an exception.
    assert fonts.get(28) is not None
