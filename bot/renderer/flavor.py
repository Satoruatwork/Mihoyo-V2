"""Bundled tables backing the Teyvat Build Card dressing.

The build card design carries a handful of strings that Enka.Network does not report:
series number, affiliation kicker, epithet, constellation name, region, weapon passives,
artifact set effects. They are static, official game data, kept in small JSON tables under
``bot/resources/`` so the renderer never invents them — anything missing degrades to "not
shown", never to a guess:

- ``card_flavor.json``     character name (lower) -> fig/affiliation/epithet/constellation_name/region
- ``weapon_flavor.json``   weapon name (lower)    -> passive description (R1 wording)
- ``artifact_sets.json``   set name (lower)       -> {"two_piece": ..., "four_piece": ...}

Keys are normalised (lower-case, collapsed whitespace) before lookup, so Enka's casing does
not matter. Tables are loaded once per process and cached; a missing or malformed file logs
and yields an empty table.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from bot.utils.logging import get_logger

logger = get_logger(__name__)

_RESOURCES = Path(__file__).resolve().parent.parent / "resources"


def normalize_name(value: str | None) -> str:
    """Normalise a game-data name for table lookup (case/whitespace-insensitive)."""
    return " ".join((value or "").strip().lower().split())


@lru_cache(maxsize=None)
def _table(filename: str) -> dict:
    path = _RESOURCES / filename
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        logger.warning("Card flavor table %s is missing; related dressing is hidden", path.name)
        return {}
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Card flavor table %s could not be loaded (%s); hiding dressing",
                       path.name, exc)
        return {}
    return data if isinstance(data, dict) else {}


def character_flavor(name: str | None) -> dict:
    """Studio-card dressing for ``name``; {} when the character has no table entry."""
    entry = _table("card_flavor.json").get(normalize_name(name))
    return entry if isinstance(entry, dict) else {}


def weapon_passive(name: str | None) -> str:
    """Passive description for ``name``; "" when unknown (line is simply not drawn)."""
    entry = _table("weapon_flavor.json").get(normalize_name(name))
    return entry if isinstance(entry, str) else ""


def artifact_set_effects(name: str | None) -> tuple[str, str]:
    """``(two_piece, four_piece)`` effect text for ``name``; ("", "") when unknown."""
    entry = _table("artifact_sets.json").get(normalize_name(name))
    if not isinstance(entry, dict):
        return "", ""
    two = entry.get("two_piece")
    four = entry.get("four_piece")
    return (two if isinstance(two, str) else "", four if isinstance(four, str) else "")
