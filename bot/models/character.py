"""Character domain model.

This is the framework-agnostic shape the whole app uses. The Enka client maps raw library
objects into this; services enrich it (e.g. with Akasha rankings); the renderer and command
layer read from it. Keeping this decoupled means an upstream API change only touches the
mapping in ``bot/api/enka_client.py``.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from bot.models.artifact import Artifact
from bot.models.ranking import Ranking
from bot.models.weapon import Weapon


@dataclass(slots=True)
class Talent:
    """A single talent (skill) and its level."""

    name: str
    level: int
    icon: str | None = None          # full icon URL for dynamic fetch


@dataclass(slots=True)
class ConstellationNode:
    """One constellation node and whether the player has unlocked it."""

    name: str
    unlocked: bool
    icon: str | None = None          # full icon URL for dynamic fetch


@dataclass(slots=True)
class CharacterStats:
    """The full stat block. Values are raw numbers; formatting happens at render time.

    Percent-based stats (crit rate/dmg, ER) are stored as percentages (e.g. 72.5 == 72.5%).
    ``extra`` holds any additional stats the API exposes that we don't model explicitly, so
    nothing is lost for future rendering.
    """

    hp: float = 0.0
    atk: float = 0.0
    defense: float = 0.0
    crit_rate: float = 0.0
    crit_dmg: float = 0.0
    energy_recharge: float = 0.0
    elemental_mastery: float = 0.0
    extra: dict[str, float] = field(default_factory=dict)


@dataclass(slots=True)
class Character:
    """A fully-described showcased character."""

    id: str                                   # avatar id (used in callback_data)
    name: str
    element: str | None = None
    rarity: int | None = None
    level: int = 1
    ascension: int = 0
    constellation: int = 0                    # 0..6
    friendship: int | None = None
    icon: str | None = None                   # icon key for asset lookup
    art: str | None = None                    # splash-art key for asset lookup

    weapon: Weapon | None = None
    talents: list[Talent] = field(default_factory=list)
    constellations: list[ConstellationNode] = field(default_factory=list)
    artifacts: list[Artifact] = field(default_factory=list)
    stats: CharacterStats = field(default_factory=CharacterStats)

    # Best-effort ranking (Akasha). None until enriched / if unavailable.
    ranking: Ranking | None = None
