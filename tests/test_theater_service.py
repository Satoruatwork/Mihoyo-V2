"""Tests for TheaterService reading Theater fields from the player showcase."""

from __future__ import annotations

from bot.models.player import PlayerInfo, Showcase
from bot.services.theater_service import TheaterService


class _StubCharacters:
    def __init__(self, player: PlayerInfo) -> None:
        self._player = player

    async def get_showcase(self, uid, language="en"):
        return Showcase(player=self._player)


async def test_theater_available_from_player():
    player = PlayerInfo(uid="618285856", theater_act=3, theater_stars=6)
    svc = TheaterService(_StubCharacters(player))
    data = await svc.get_theater("618285856")
    assert data.available is True
    assert data.act == 3
    assert data.stars == 6


async def test_theater_unavailable_when_player_has_none():
    player = PlayerInfo(uid="618285856")  # no theater fields shown
    svc = TheaterService(_StubCharacters(player))
    data = await svc.get_theater("618285856")
    assert data.available is False
