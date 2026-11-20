"""Tests for Enka client error mapping and defensive field mapping."""

from __future__ import annotations

import pytest

from bot.api.enka_client import EnkaClient
from bot.utils.errors import ApiUnavailable, NetworkError, ProfilePrivate, RateLimited


@pytest.mark.parametrize(
    "exc, expected",
    [
        (Exception("HTTP 429 rate limit"), RateLimited),
        (TimeoutError("connection timeout"), NetworkError),
        (Exception("player does not exist"), ProfilePrivate),
        (Exception("something weird"), ApiUnavailable),
    ],
)
def test_error_mapping(exc, expected):
    with pytest.raises(expected):
        EnkaClient._raise_mapped(exc)


class _FakeStat:
    def __init__(self, value):
        self.value = value


class _FakeRawChar:
    id = "10000046"
    name = "Hu Tao"
    level = 90
    constellation = 6
    weapon = None
    talents = []
    artifacts = []

    class _Stats:
        max_hp = _FakeStat(15000)
        atk = _FakeStat(2000)
        crit_rate = _FakeStat(70.5)

    stats = _Stats()


class _FakeRawPlayer:
    nickname = "Traveler"
    level = 60
    world_level = 8
    signature = "hi"


class _FakeRawShowcase:
    player = _FakeRawPlayer()
    characters = [_FakeRawChar()]


def test_map_showcase_defensive():
    client = EnkaClient()
    showcase = client._map_showcase("901211014", _FakeRawShowcase())
    assert showcase.player.nickname == "Traveler"
    assert len(showcase.characters) == 1
    c = showcase.characters[0]
    assert c.name == "Hu Tao"
    assert c.level == 90
    assert c.stats.hp == 15000
    assert c.stats.crit_rate == 70.5


class _FakeConst:
    def __init__(self, name, unlocked):
        self.name = name
        self.unlocked = unlocked


def test_constellation_counts_unlocked_nodes():
    """C2: two unlocked nodes out of the supplied list -> constellation == 2."""
    client = EnkaClient()
    nodes = [_FakeConst(f"C{i}", i < 2) for i in range(6)]
    c = client._map_character(type("RC", (), {"id": "1", "name": "x", "constellations": nodes})())
    assert c.constellation == 2


def test_constellation_zero_is_not_overridden_by_stale_scalar():
    """A genuine C0 (all nodes locked) must stay 0, even if a raw ``constellation`` attr exists.

    Regression for the truthiness-``or`` bug: sum == 0 is falsy, so the old code fell through
    to the raw scalar and mis-labelled a C0 character.
    """
    client = EnkaClient()
    nodes = [_FakeConst(f"C{i}", False) for i in range(6)]
    raw = type("RC", (), {"id": "1", "name": "x", "constellations": nodes, "constellation": 6})()
    c = client._map_character(raw)
    assert c.constellation == 0


class _FakeStatType:
    def __init__(self, name):
        self.name = name


class _FakeWeaponStat:
    def __init__(self, type_name, value, name):
        self.type = _FakeStatType(type_name)
        self.value = value
        self.name = name


class _FakeRawWeapon:
    """Mirrors enka's Weapon: stats live in a ``stats`` list, not ``main_stat``/``sub_stat``."""

    def __init__(self, icon, stats, name="Mistsplitter Reforged", level=90, refinement=1):
        self.name = name
        self.level = level
        self.refinement = refinement
        self.ascension = 6
        self.rarity = 5
        self.item_type = "ITEM_WEAPON"  # never encodes the weapon class
        self.icon = icon
        self.stats = stats


def test_map_weapon_reads_stats_list_and_derives_type():
    """Regression: weapon main/sub stats + type must populate from enka's stats list + icon."""
    client = EnkaClient()
    w = _FakeRawWeapon(
        icon="https://enka.network/ui/UI_EquipIcon_Sword_Narukami.png",
        stats=[
            _FakeWeaponStat("FIGHT_PROP_BASE_ATTACK", 674.0, "Base ATK"),
            _FakeWeaponStat("FIGHT_PROP_CRITICAL_HURT", 44.1, "CRIT DMG"),
        ],
    )
    dw = client._map_weapon(w)
    assert dw.weapon_type == "Sword"  # derived from the icon filename, not item_type
    assert dw.main_stat_name == "Base ATK"
    assert dw.main_stat_value == 674.0
    assert dw.sub_stat_name == "CRIT DMG"
    assert dw.sub_stat_value == 44.1


def test_map_weapon_main_stat_is_order_independent():
    client = EnkaClient()
    w = _FakeRawWeapon(
        icon="x/UI_EquipIcon_Pole_Kitain.png",
        stats=[
            _FakeWeaponStat("FIGHT_PROP_ATTACK_PERCENT", 27.6, "ATK%"),
            _FakeWeaponStat("FIGHT_PROP_BASE_ATTACK", 542.0, "Base ATK"),
        ],
    )
    dw = client._map_weapon(w)
    assert dw.weapon_type == "Polearm"
    assert dw.main_stat_name == "Base ATK"  # found by type, even though it is second in the list
    assert dw.sub_stat_name == "ATK%"


def test_map_weapon_handles_missing_stats_and_none():
    client = EnkaClient()
    dw = client._map_weapon(_FakeRawWeapon(icon="x/UI_EquipIcon_Bow_Amos.png", stats=[]))
    assert dw.weapon_type == "Bow"
    assert dw.main_stat_name is None
    assert dw.sub_stat_name is None
    assert client._map_weapon(None) is None
