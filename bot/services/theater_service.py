"""Imaginarium Theater business logic.

Enka's public profile exposes a player's Imaginarium Theater summary (the act reached and
stars earned) *when the player has enabled showing it in-game*. This service reads those
fields from the showcase's player info. If the player hasn't shown any Theater progress the
result is simply empty (``available`` is False) — the command layer reports that clearly
rather than treating it as an error.
"""

from __future__ import annotations

from bot.models.theater import TheaterData
from bot.services.character_service import CharacterService


class TheaterService:
    def __init__(self, characters: CharacterService) -> None:
        self._characters = characters

    async def get_theater(self, uid: str, language: str = "en") -> TheaterData:
        showcase = await self._characters.get_showcase(uid, language)
        player = showcase.player
        return TheaterData(
            uid=uid,
            act=player.theater_act,
            stars=player.theater_stars,
        )
