"""Spiral Abyss business logic.

Enka's public profile exposes the player's current Abyss progress (deepest floor/chamber).
Full per-chamber breakdowns require an authenticated HoYoLAB session, which is out of scope
for this public-data foundation, so we surface what Enka provides and degrade gracefully
otherwise. The service shape supports richer sources being plugged in later.
"""

from __future__ import annotations

from bot.models.abyss import AbyssData
from bot.services.character_service import CharacterService
from bot.utils.errors import DataUnavailable


class AbyssService:
    def __init__(self, characters: CharacterService) -> None:
        self._characters = characters

    async def get_abyss(self, uid: str, *, previous: bool = False, language: str = "en") -> AbyssData:
        showcase = await self._characters.get_showcase(uid, language)
        player = showcase.player
        floor = player.abyss_floor
        chamber = player.abyss_chamber
        if floor is not None and chamber is not None:
            max_floor = f"{floor}-{chamber}"
        elif floor is not None:
            max_floor = str(floor)
        else:
            max_floor = None
        data = AbyssData(uid=uid, is_previous=previous, max_floor=max_floor)
        if not data.available:
            raise DataUnavailable(f"No abyss data for {uid}")
        return data
