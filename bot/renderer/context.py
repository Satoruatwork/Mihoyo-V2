"""Render context bundles.

These dataclasses are the *only* input contract the renderer accepts. Commands/services
assemble a context from domain models + resolved language; a renderer backend turns it into
an image. This keeps business logic and rendering fully decoupled — swapping the Pillow
backend for an HTML/Playwright one later requires no changes to callers.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from bot.models.abyss import AbyssData
from bot.models.character import Character
from bot.models.player import PlayerInfo
from bot.models.theater import TheaterData


@dataclass(slots=True)
class RenderContext:
    """Base context: language + optional theme/asset hints shared by all cards."""

    language: str = "en"
    # Asset hint keys (resolved by the AssetLoader, not hardcoded paths).
    background: str | None = None
    frame: str | None = None
    theme: str | None = None
    extra: dict[str, object] = field(default_factory=dict)


@dataclass(slots=True)
class CharacterCardContext(RenderContext):
    """Everything needed to render a single character build card."""

    character: Character | None = None
    player: PlayerInfo | None = None
    # Pre-fetched character artwork (PIL.Image) or None to use the empty portrait frame.
    portrait: object | None = None
    # Pre-fetched icons keyed by their source URL: {url: PIL.Image}. Prefetched (async) in the
    # command layer so the synchronous renderer can composite them without doing I/O.
    icons: dict = field(default_factory=dict)


@dataclass(slots=True)
class AbyssCardContext(RenderContext):
    abyss: AbyssData | None = None
    player: PlayerInfo | None = None


@dataclass(slots=True)
class TheaterCardContext(RenderContext):
    theater: TheaterData | None = None
    player: PlayerInfo | None = None
