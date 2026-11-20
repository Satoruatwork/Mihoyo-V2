"""Spiral Abyss domain model."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class AbyssChamber:
    """A single chamber result."""

    floor: int
    chamber: int
    stars: int = 0


@dataclass(slots=True)
class AbyssData:
    """Spiral Abyss summary for a player (current or previous cycle)."""

    uid: str
    is_previous: bool = False
    total_stars: int | None = None
    max_floor: str | None = None            # e.g. "12-3"
    total_battles: int | None = None
    total_wins: int | None = None
    chambers: list[AbyssChamber] = field(default_factory=list)

    @property
    def available(self) -> bool:
        return self.total_stars is not None or self.max_floor is not None or bool(self.chambers)
