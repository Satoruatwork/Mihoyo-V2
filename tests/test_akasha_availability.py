"""Enka availability and Akasha availability are independent concerns.

Akasha only ranks builds it has a damage calculation for. A newly released character is
fully resolvable by Enka and simultaneously unranked by Akasha — the card must show the
build and say the ranking isn't available, instead of printing a placement that looks real.
"""

from __future__ import annotations

from bot.api.akasha_client import AkashaClient
from bot.api.character_metadata import placeholder_name
from bot.commands.characters import _build_caption
from bot.models.character import Character, CharacterStats
from bot.models.player import PlayerInfo, Showcase
from bot.models.ranking import Ranking
from bot.models.weapon import Weapon
from bot.services.character_service import CharacterService


class _FakeEnka:
    def __init__(self, showcase):
        self._s = showcase

    async def fetch_showcase(self, uid, language="en"):
        return self._s


class _FakeAkasha:
    """Akasha that knows the established character but not the new one."""

    def __init__(self, rankings):
        self._r = rankings

    async def fetch_rankings(self, uid):
        return self._r


class _DeadAkasha:
    async def fetch_rankings(self, uid):
        raise RuntimeError("akasha.cv unreachable")


def _showcase():
    return Showcase(
        player=PlayerInfo(uid="901211014", nickname="Rexxyyy"),
        characters=[
            Character(id="10000046", name="Hu Tao", level=90, stats=CharacterStats(hp=15000)),
            Character(id="10000150", name="Odette", level=90, stats=CharacterStats(hp=14000),
                      weapon=Weapon(name="Test Blade", level=90)),
        ],
    )


async def test_character_unranked_by_akasha_is_still_fully_shown(cache):
    """Enka resolved the character; Akasha has no calculation for it yet."""
    ranked = Ranking(rank=2147, total_players=100_000, top_percent=2.1, calculation_name="Hypercarry")
    service = CharacterService(
        _FakeEnka(_showcase()), _FakeAkasha({"10000046": ranked}), cache, ttl=60
    )

    showcase = await service.get_showcase("901211014")

    hutao = showcase.get_character("10000046")
    odette = showcase.get_character("10000150")
    assert hutao.ranking is not None and hutao.ranking.rank == 2147
    # The unranked character keeps every piece of Enka data...
    assert odette.name == "Odette"
    assert odette.level == 90
    assert odette.weapon.name == "Test Blade"
    assert odette.stats.hp == 14000
    # ...and simply has no ranking attached.
    assert odette.ranking is None


async def test_akasha_outage_does_not_affect_character_data(cache):
    service = CharacterService(_FakeEnka(_showcase()), _DeadAkasha(), cache, ttl=60)

    showcase = await service.get_showcase("901211014")

    assert [c.name for c in showcase.characters] == ["Hu Tao", "Odette"]
    assert all(c.ranking is None for c in showcase.characters)


async def test_unresolved_character_gets_a_short_cache_ttl(cache):
    """A placeholder name must not be cached for the full TTL once upstream catches up."""
    showcase = Showcase(
        player=PlayerInfo(uid="901211014"),
        characters=[Character(id="10000199", name=placeholder_name("10000199"), level=90)],
    )
    service = CharacterService(_FakeEnka(showcase), _FakeAkasha({}), cache, ttl=3600)

    assert service._cache_ttl_for(showcase) == 60
    assert service._cache_ttl_for(_showcase()) == 3600


def test_caption_states_unavailable_rather_than_faking_a_placement():
    character = Character(id="10000150", name="Odette", level=90, ranking=None)

    caption = _build_caption(character, PlayerInfo(uid="1", nickname="Rexxyyy"))

    assert "Odette" in caption          # Enka data present
    assert "Rexxyyy" in caption
    assert "Rank: Not available" in caption
    assert "Top: Not available" in caption
    assert "Category: Not available" in caption
    assert "#--" not in caption


def test_caption_is_localized():
    character = Character(id="10000150", name="Odette", level=90, ranking=None)

    assert "No disponible" in _build_caption(character, None, "es")
    assert "Non disponibile" in _build_caption(character, None, "it")


def test_akasha_entry_without_a_ranking_is_not_treated_as_available():
    """An Akasha entry whose calculation carries no placement must not become '#0'."""
    entries = [{"characterId": 10000150, "calculations": {"fit": {"name": "New rotation"}}}]

    ranking = AkashaClient()._parse(entries, "901211014")["10000150"]

    assert ranking.rank is None
    assert ranking.top_percent is None
    assert ranking.available is False
