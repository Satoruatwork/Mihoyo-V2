"""Data models: framework-agnostic domain objects and the raw->domain parser.

The models know nothing about HTTP or rendering. The parser turns a raw Enka payload into
these objects and accepts an optional ``resolve_name`` callable so name-hash localization is
injected rather than hard-wired (keeping the model layer independent of the asset layer).
"""

from __future__ import annotations

from enkarender.models.domain import (
    Artifact,
    Character,
    Player,
    Showcase,
    Stat,
    Weapon,
)
from enkarender.models.parser import parse_showcase

__all__ = [
    "Artifact",
    "Character",
    "Player",
    "Showcase",
    "Stat",
    "Weapon",
    "parse_showcase",
]
