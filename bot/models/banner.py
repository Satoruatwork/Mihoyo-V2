"""Banner domain model."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class Banner:
    """A single event/weapon banner."""

    name: str
    kind: str = "character"              # character / weapon / permanent
    featured: list[str] = field(default_factory=list)
    start: str | None = None            # ISO date string (kept as text; no live clock here)
    end: str | None = None
    version: str | None = None


@dataclass(slots=True)
class BannerBoard:
    """Current and upcoming banners."""

    current: list[Banner] = field(default_factory=list)
    upcoming: list[Banner] = field(default_factory=list)

    @property
    def available(self) -> bool:
        return bool(self.current or self.upcoming)
