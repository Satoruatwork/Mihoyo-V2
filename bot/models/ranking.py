"""Akasha ranking domain model.

All fields are optional: ranking data is best-effort. When Akasha is unavailable or a
character isn't ranked, an empty :class:`Ranking` (or ``None``) is used and the UI omits it.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class Ranking:
    """Leaderboard placement for a character build (from Akasha System)."""

    calculation_id: str | None = None
    calculation_name: str | None = None      # e.g. the damage rotation being ranked
    rank: int | None = None                  # this build's position
    total_players: int | None = None         # size of the leaderboard
    top_percent: float | None = None         # e.g. 3.2 meaning top 3.2%
    leaderboard_url: str | None = None
    damage: float | None = None              # the computed damage figure, if provided

    @property
    def available(self) -> bool:
        """Whether there's any meaningful ranking data to display."""
        return self.rank is not None or self.top_percent is not None
