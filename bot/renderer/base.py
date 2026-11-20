"""Renderer abstraction.

A ``Renderer`` turns a render context into PNG image bytes. The concrete backend
(:class:`~bot.renderer.pillow_renderer.PillowRenderer` today) is chosen via
:func:`get_renderer`, so command code never imports a specific backend.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from bot.renderer.context import (
    AbyssCardContext,
    CharacterCardContext,
    TheaterCardContext,
)


class Renderer(ABC):
    """Abstract image renderer. Backends return PNG bytes ready to send to Telegram."""

    @abstractmethod
    def render_character_card(self, ctx: CharacterCardContext) -> bytes:
        ...

    @abstractmethod
    def render_profile_card(self, ctx: CharacterCardContext) -> bytes:
        ...

    @abstractmethod
    def render_abyss_card(self, ctx: AbyssCardContext) -> bytes:
        ...

    @abstractmethod
    def render_theater_card(self, ctx: TheaterCardContext) -> bytes:
        ...

    def warmup(self) -> None:
        """Pre-load static rendering resources into memory at startup. Default: no-op.

        Backends may override to decode the card template and common fonts once, so the
        first real render is not slowed by cold caches and concurrent renders never race
        to populate them.
        """
        return None


_default_renderer: Renderer | None = None


def get_renderer() -> Renderer:
    """Return the shared default renderer backend."""
    global _default_renderer
    if _default_renderer is None:
        # Imported here to avoid a hard import cycle and to keep backend choice in one place.
        from bot.renderer.pillow_renderer import PillowRenderer

        _default_renderer = PillowRenderer()
    return _default_renderer
