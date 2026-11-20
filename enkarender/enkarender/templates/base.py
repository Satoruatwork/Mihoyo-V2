"""Template engine primitives: RenderContext, Component, Template, and the registry.

Design contract:
  * A **RenderContext** is the *only* thing a template/component reads. It carries the plain
    view-model data, pre-loaded images, the font manager, and the theme — never a live API
    client or asset downloader. This is what makes rendering independent of I/O.
  * A **Component** paints one visual unit onto a Canvas. Components are reusable across
    templates and know nothing about card types.
  * A **Template** is layout only: it lists the components and their positions for a fixed
    canvas size. Templates self-register in the :data:`registry` so the engine can look one
    up by key and new templates drop in without touching engine code.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from PIL import Image

from enkarender.exceptions import TemplateNotFound
from enkarender.fonts.manager import FontManager
from enkarender.render.canvas import Canvas
from enkarender.render.draw import RGBA, Theme


@dataclass(slots=True)
class RenderContext:
    """Everything a template needs to render — and nothing that does I/O."""

    data: dict[str, Any]
    fonts: FontManager
    theme: Theme
    images: dict[str, Image.Image] = field(default_factory=dict)

    def get(self, key: str, default: Any = None) -> Any:
        return self.data.get(key, default)

    def image(self, key: str) -> Image.Image | None:
        return self.images.get(key)


class Component(ABC):
    """A single reusable visual unit."""

    @abstractmethod
    def render(self, canvas: Canvas, ctx: RenderContext) -> None:
        """Paint this component onto ``canvas`` using data/resources from ``ctx``."""


class Template(ABC):
    """A layout: fixed canvas size + an ordered list of components. Layout only."""

    key: str = "base"
    size: tuple[int, int] = (900, 1200)

    def background(self, ctx: RenderContext) -> RGBA | Image.Image | None:
        """Optional base fill/image for the canvas. Default: opaque themed background."""
        return ctx.theme.bg

    @abstractmethod
    def components(self, ctx: RenderContext) -> list[Component]:
        """Return the ordered components to paint (back-to-front)."""


class TemplateRegistry:
    """Maps a template key to a template instance. Enables drop-in templates."""

    def __init__(self) -> None:
        self._templates: dict[str, Template] = {}

    def register(self, template: Template) -> Template:
        self._templates[template.key] = template
        return template

    def get(self, key: str) -> Template:
        try:
            return self._templates[key]
        except KeyError:
            raise TemplateNotFound(f"No template registered under {key!r}") from None

    def keys(self) -> list[str]:
        return sorted(self._templates)


# Process-wide registry templates register into at import time.
registry = TemplateRegistry()
