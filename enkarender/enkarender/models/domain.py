"""Domain model dataclasses.

Plain data with no behavior beyond trivial derived helpers. These are what the rest of the
engine renders from; nothing here imports PIL, aiohttp, or the asset layer.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from enkarender.enums import Element


@dataclass(slots=True)
class Stat:
    """A single named stat value; ``percent`` marks it for ``%`` formatting."""

    name: str
    value: float
    percent: bool = False

    def formatted(self) -> str:
        if self.percent:
            return f"{self.value:.1f}%"
        return f"{self.value:,.0f}"


@dataclass(slots=True)
class Weapon:
    name: str
    level: int = 1
    refinement: int = 1
    rarity: int | None = None
    icon: str | None = None            # asset key or URL, resolved lazily by the asset layer
    main_stat: Stat | None = None
    sub_stat: Stat | None = None


@dataclass(slots=True)
class Artifact:
    slot: str                          # Flower / Plume / Sands / Goblet / Circlet
    level: int = 0
    rarity: int | None = None
    set_name: str | None = None
    icon: str | None = None
    main_stat: Stat | None = None
    sub_stats: list[Stat] = field(default_factory=list)


@dataclass(slots=True)
class Character:
    id: str
    name: str
    element: Element = Element.UNKNOWN
    rarity: int | None = None
    level: int = 1
    friendship: int | None = None
    constellation: int = 0
    portrait: str | None = None        # asset key/URL for splash art
    weapon: Weapon | None = None
    artifacts: list[Artifact] = field(default_factory=list)
    stats: list[Stat] = field(default_factory=list)


@dataclass(slots=True)
class Player:
    uid: str
    nickname: str = ""
    level: int = 0
    world_level: int = 0
    signature: str = ""
    achievements: int | None = None
    namecard: str | None = None


@dataclass(slots=True)
class Showcase:
    """A player's profile header plus their showcased characters."""

    player: Player
    characters: list[Character] = field(default_factory=list)

    def character(self, char_id: str) -> Character | None:
        return next((c for c in self.characters if c.id == char_id), None)
