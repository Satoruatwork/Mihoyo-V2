"""Tests for AbyssService.max_floor formatting.

Regression coverage for the L1 bug: a legitimate ``chamber == 0`` was degraded
to floor-only because the formatter used a truthiness check instead of a
None check.
"""

from __future__ import annotations

import pytest

from bot.models.player import PlayerInfo, Showcase
from bot.services.abyss_service import AbyssService
from bot.utils.errors import DataUnavailable


class _StubCharacterService:
    def __init__(self, player: PlayerInfo) -> None:
        self._player = player

    async def get_showcase(self, uid: str, language: str = "en") -> Showcase:
        return Showcase(player=self._player)


def _service(**player_kwargs) -> AbyssService:
    player = PlayerInfo(uid="800000000", **player_kwargs)
    return AbyssService(_StubCharacterService(player))


async def test_max_floor_full():
    data = await _service(abyss_floor=12, abyss_chamber=3).get_abyss("800000000")
    assert data.max_floor == "12-3"


async def test_max_floor_chamber_zero_is_preserved():
    # chamber == 0 must NOT collapse to floor-only.
    data = await _service(abyss_floor=9, abyss_chamber=0).get_abyss("800000000")
    assert data.max_floor == "9-0"


async def test_max_floor_floor_only_when_no_chamber():
    data = await _service(abyss_floor=7, abyss_chamber=None).get_abyss("800000000")
    assert data.max_floor == "7"


async def test_no_abyss_data_raises():
    with pytest.raises(DataUnavailable):
        await _service(abyss_floor=None, abyss_chamber=None).get_abyss("800000000")
