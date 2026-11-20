"""Card builder base class + registry.

The builder is the single place where the layers meet: it takes a domain model, uses the
asset layer to resolve images (concurrently), the font manager for typography, and a theme
for colour, assembles a :class:`RenderContext`, and calls the engine in a worker thread so
rendering never blocks the event loop. Subclasses implement three small hooks; the build
flow is shared.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from PIL import Image

from enkarender.assets.manager import AssetManager
from enkarender.exceptions import CardTypeNotFound
from enkarender.fonts.manager import FontManager
from enkarender.logging import get_logger
from enkarender.render.draw import Theme
from enkarender.render.engine import RenderEngine, engine as default_engine
from enkarender.templates.base import RenderContext, TemplateRegistry
from enkarender.templates.base import registry as template_registry
from enkarender.utils.async_tools import run_in_thread

logger = get_logger("cards.base")


class CardBuilder(ABC):
    """Base async card builder. Subclasses set ``key``/``template_key`` and 3 hooks."""

    key: str = "base"
    template_key: str = "base"

    def __init__(
        self,
        assets: AssetManager,
        fonts: FontManager,
        engine: RenderEngine | None = None,
        templates: TemplateRegistry | None = None,
    ) -> None:
        self._assets = assets
        self._fonts = fonts
        self._engine = engine or default_engine
        self._templates = templates or template_registry

    async def build(self, data: Any) -> bytes:
        """Resolve resources, assemble the context, and render to PNG bytes."""
        view_model = self._view_model(data)
        theme = self._theme(data)
        images = await self._load_images(data)
        ctx = RenderContext(data=view_model, fonts=self._fonts, theme=theme, images=images)
        template = self._templates.get(self.template_key)
        # Render off the event loop — Pillow compositing is CPU-bound.
        return await run_in_thread(self._engine.render, template, ctx)

    # --- hooks subclasses implement ---
    @abstractmethod
    def _view_model(self, data: Any) -> dict[str, Any]:
        """Flatten the domain model into the plain dict the template reads."""

    @abstractmethod
    def _theme(self, data: Any) -> Theme:
        """Choose the colour theme for this card (usually element-derived)."""

    @abstractmethod
    async def _load_images(self, data: Any) -> dict[str, Image.Image]:
        """Resolve every image the template needs, keyed by its slot name."""


class CardRegistry:
    """Maps a card key to a builder *class*, and instantiates on demand.

    Classes (not instances) are registered so builders can self-register at import time
    without needing runtime dependencies (assets/fonts) yet. :meth:`create` wires those in.
    """

    def __init__(self) -> None:
        self._builders: dict[str, type[CardBuilder]] = {}

    def register(self, builder_cls: type[CardBuilder]) -> type[CardBuilder]:
        self._builders[builder_cls.key] = builder_cls
        return builder_cls

    def create(self, key: str, assets: AssetManager, fonts: FontManager, **kwargs) -> CardBuilder:
        return self._builder_cls(key)(assets, fonts, **kwargs)

    def _builder_cls(self, key: str) -> type[CardBuilder]:
        try:
            return self._builders[key]
        except KeyError:
            raise CardTypeNotFound(f"No card builder registered under {key!r}") from None

    def keys(self) -> list[str]:
        return sorted(self._builders)


registry = CardRegistry()
