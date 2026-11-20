"""Artifact domain models."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class ArtifactStat:
    """A single artifact stat (main stat or substat)."""

    name: str
    value: float
    is_percent: bool = False


@dataclass(slots=True)
class Artifact:
    """A single equipped artifact piece."""

    slot: str                       # flower / plume / sands / goblet / circlet
    set_name: str | None = None
    level: int = 0
    rarity: int | None = None
    icon: str | None = None
    main_stat: ArtifactStat | None = None
    sub_stats: list[ArtifactStat] = field(default_factory=list)
