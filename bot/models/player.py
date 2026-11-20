"""Player / profile domain model."""

from __future__ import annotations

from dataclasses import dataclass, field

from bot.models.character import Character


@dataclass(slots=True)
class PlayerInfo:
    """Public profile header information for a Genshin account."""

    uid: str
    nickname: str = ""
    level: int = 0                       # Adventure Rank
    world_level: int = 0
    signature: str = ""
    namecard: str | None = None          # namecard/background key for asset lookup
    profile_icon: str | None = None
    achievements: int | None = None
    abyss_floor: int | None = None
    abyss_chamber: int | None = None
    theater_act: int | None = None
    theater_stars: int | None = None


@dataclass(slots=True)
class Showcase:
    """A player's public showcase: their profile header plus showcased characters."""

    player: PlayerInfo
    characters: list[Character] = field(default_factory=list)

    def get_character(self, char_id: str) -> Character | None:
        for c in self.characters:
            if c.id == char_id:
                return c
        return None
