"""Imaginarium Theater domain model."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class TheaterData:
    """Imaginarium Theater summary for a player."""

    uid: str
    difficulty: str | None = None
    stars: int | None = None
    act: int | None = None
    max_rounds: int | None = None
    best_record: str | None = None

    @property
    def available(self) -> bool:
        return any(
            v is not None
            for v in (self.difficulty, self.stars, self.act, self.max_rounds, self.best_record)
        )
