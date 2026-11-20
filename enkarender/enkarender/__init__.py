"""enkarender — a modular, original Enka-to-image rendering engine.

Public facade tying the layers together::

    Enka API  ->  raw payload  ->  parser  ->  domain model
                                                   |
                        assets/fonts (resolved concurrently, cached)
                                                   |
                              card builder  ->  RenderContext
                                                   |
                        template (layout) + engine (compositing)  ->  PNG bytes

The layers are independently usable; :class:`EnkaRenderer` is the batteries-included entry
point. Importing this package registers the bundled templates and card builders.
"""

from __future__ import annotations

from typing import Any

from enkarender.api.client import EnkaClient
from enkarender.api.http import HttpTransport
from enkarender.assets.cache import CacheManager
from enkarender.assets.downloader import Downloader
from enkarender.assets.loader import ResourceLoader
from enkarender.assets.manager import AssetManager
from enkarender.config import Settings, default_settings
from enkarender.fonts.manager import FontManager
from enkarender.models.parser import parse_showcase
from enkarender.models.domain import Character, Showcase

# Import side-effect: populate the template + card registries.
from enkarender import templates as _templates  # noqa: F401
from enkarender.cards.base import registry as card_registry
from enkarender import cards as _cards  # noqa: F401

__version__ = "1.0.0"

__all__ = [
    "EnkaRenderer",
    "Settings",
    "Showcase",
    "Character",
    "parse_showcase",
    "card_registry",
]


class EnkaRenderer:
    """Batteries-included facade: UID in, rendered card bytes out.

    Constructs and shares a single HTTP transport, cache, asset manager, and font manager
    across all renders. Use as an async context manager to release the pooled session.
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or default_settings
        self._transport = HttpTransport(self.settings)
        self._cache = CacheManager(self.settings)
        self.client = EnkaClient(self._transport, self._cache, self.settings)
        loader = ResourceLoader(Downloader(self._transport, self._cache, self.settings), self._cache)
        self.assets = AssetManager(loader, self._cache, self.settings)
        self.fonts = FontManager(self.settings)
        self._cards = card_registry

    async def fetch_showcase(self, uid: str) -> Showcase:
        """Fetch + parse a UID's showcase into the domain model (localized if maps exist)."""
        raw = await self.client.fetch_showcase(uid)
        return parse_showcase(
            raw,
            resolve_name=self.assets.resolve_name,
            resolve_character=self.assets.resolve_character,
        )

    async def render_profile(self, uid: str) -> bytes:
        """Render a player profile card for ``uid``."""
        showcase = await self.fetch_showcase(uid)
        return await self.render_card("profile", showcase)

    async def render_build(self, uid: str, character_id: str | None = None) -> bytes:
        """Render a build card for a character in ``uid``'s showcase (first if unspecified)."""
        showcase = await self.fetch_showcase(uid)
        character = showcase.character(character_id) if character_id else None
        character = character or (showcase.characters[0] if showcase.characters else None)
        if character is None:
            from enkarender.exceptions import EmptyShowcase

            raise EmptyShowcase(f"No characters to render for UID {uid}")
        return await self.render_card("build", character)

    async def render_card(self, card_key: str, data: Any) -> bytes:
        """Render any registered card type from an already-loaded domain object."""
        builder = self._cards.create(card_key, self.assets, self.fonts)
        return await builder.build(data)

    async def aclose(self) -> None:
        await self._transport.aclose()

    async def __aenter__(self) -> "EnkaRenderer":
        return self

    async def __aexit__(self, *exc) -> None:
        await self.aclose()
