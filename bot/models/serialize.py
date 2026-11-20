"""(De)serialization for domain models, used to cache showcases as JSON in Redis.

``showcase_to_dict`` uses ``dataclasses.asdict`` (all fields are JSON-friendly primitives,
lists, and dicts). ``showcase_from_dict`` reconstructs the nested dataclasses explicitly so
the cached representation round-trips exactly.
"""

from __future__ import annotations

import dataclasses
from typing import Any

from bot.models.artifact import Artifact, ArtifactStat
from bot.models.character import Character, CharacterStats, ConstellationNode, Talent
from bot.models.player import PlayerInfo, Showcase
from bot.models.ranking import Ranking
from bot.models.weapon import Weapon


def showcase_to_dict(showcase: Showcase) -> dict[str, Any]:
    return dataclasses.asdict(showcase)


def showcase_from_dict(data: dict[str, Any]) -> Showcase:
    player = PlayerInfo(**data["player"])
    characters = [_character_from_dict(c) for c in data.get("characters", [])]
    return Showcase(player=player, characters=characters)


def _character_from_dict(c: dict[str, Any]) -> Character:
    nested = {"weapon", "talents", "constellations", "artifacts", "stats", "ranking"}
    base = {k: v for k, v in c.items() if k not in nested}
    weapon = Weapon(**c["weapon"]) if c.get("weapon") else None
    talents = [Talent(**t) for t in c.get("talents", [])]
    constellations = [ConstellationNode(**n) for n in c.get("constellations", [])]
    artifacts = [_artifact_from_dict(a) for a in c.get("artifacts", [])]
    stats = CharacterStats(**c["stats"]) if c.get("stats") else CharacterStats()
    ranking = Ranking(**c["ranking"]) if c.get("ranking") else None
    return Character(
        **base,
        weapon=weapon,
        talents=talents,
        constellations=constellations,
        artifacts=artifacts,
        stats=stats,
        ranking=ranking,
    )


def _artifact_from_dict(a: dict[str, Any]) -> Artifact:
    base = {k: v for k, v in a.items() if k not in ("main_stat", "sub_stats")}
    main_stat = ArtifactStat(**a["main_stat"]) if a.get("main_stat") else None
    sub_stats = [ArtifactStat(**s) for s in a.get("sub_stats", [])]
    return Artifact(**base, main_stat=main_stat, sub_stats=sub_stats)
