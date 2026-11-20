"""Tests for the Teyvat Build Card renderer.

The renderer draws a fully-normalised :class:`~bot.renderer.card_data.CardData` — these
tests pin the pieces that are easy to break silently: the CRIT Value math, the grade
thresholds, the way domain data flows through ``from_character``, and an end-to-end PNG
smoke render (this renderer is what ``/card`` sends to Telegram).

Note: ``_CV_GRADES`` thresholds are a working convention, not an official Genshin scale —
they are pinned here so any change is deliberate and visible in review.
"""

from __future__ import annotations

from types import SimpleNamespace

from bot.models.artifact import Artifact, ArtifactStat
from bot.models.character import Character, CharacterStats, ConstellationNode, Talent
from bot.models.player import PlayerInfo
from bot.models.weapon import Weapon
from bot.renderer.card_data import from_character
from bot.renderer.character_card_renderer import (
    artifact_cv,
    artifact_cv_grade,
    artifact_total_cv,
    get_card_renderer,
)

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def _character(**kw) -> Character:
    base = dict(
        id="10000046", name="Hu Tao", element="Fire", rarity=5, level=90, constellation=1,
        ascension=6, friendship=10,
        weapon=Weapon(name="Staff of Homa", level=90, refinement=1, rarity=5, ascension=6,
                      weapon_type="Polearm", main_stat_value=608,
                      sub_stat_name="CRIT DMG", sub_stat_value=66.2),
        talents=[Talent("Secret Spear of Wangsheng", 10),
                 Talent("Guide to Afterlife", 10),
                 Talent("Spirit Soother", 10)],
        constellations=[ConstellationNode(f"C{i + 1}", unlocked=i < 1) for i in range(6)],
        artifacts=[
            Artifact(slot="Flower", set_name="Crimson Witch of Flames", rarity=5, level=20,
                     main_stat=ArtifactStat("HP", 4780),
                     sub_stats=[ArtifactStat("CRIT Rate", 10.5, True),
                                ArtifactStat("CRIT DMG", 14.0, True),
                                ArtifactStat("ATK%", 5.3, True),
                                ArtifactStat("Elemental Mastery", 40)]),
        ],
        stats=CharacterStats(hp=34812, atk=1962, defense=876, crit_rate=72.4, crit_dmg=188.6,
                             energy_recharge=100.0, elemental_mastery=134,
                             extra={"FIGHT_PROP_FIRE_ADD_HURT": 0.616}),
    )
    base.update(kw)
    return Character(**base)


def test_render_produces_a_full_card_png():
    png = get_card_renderer().render(from_character(_character(), portrait=None))
    assert png.startswith(PNG_MAGIC)
    assert len(png) > 100_000  # a real 1536x864 card, not an empty canvas


def test_render_survives_bare_minimum_data():
    """No weapon, no artifacts, no talents, no stats — the card must still render."""
    ch = _character(
        weapon=None, talents=[], artifacts=[],
        stats=CharacterStats(hp=None, atk=None, defense=None, crit_rate=None, crit_dmg=None,
                             energy_recharge=None, elemental_mastery=None, extra={}),
    )
    png = get_card_renderer().render(from_character(ch))
    assert png.startswith(PNG_MAGIC)


def test_artifact_cv_counts_substats_only():
    """A CRIT Rate main stat must not inflate CV; only substats count."""
    substats = [("CRIT Rate", "+10.5%"), ("CRIT DMG", "+14.0%"),
                ("ATK%", "+5.3%"), ("Elemental Mastery", "+40")]
    assert artifact_cv(substats) == 2 * 10.5 + 14.0
    assert artifact_cv([]) == 0.0
    assert artifact_cv(None) == 0.0


def test_artifact_total_cv_sums_across_pieces():
    arts = {
        "flower": SimpleNamespace(substats=[("CRIT Rate", "+10.0%")]),   # 20.0
        "sands": SimpleNamespace(substats=[("CRIT DMG", "+20.0%")]),    # 20.0
        "goblet": None,                                                  # not equipped
    }
    assert artifact_total_cv(arts) == 40.0


def test_artifact_cv_grade_thresholds():
    assert artifact_cv_grade(250.0) == "SS"
    assert artifact_cv_grade(210.0) == "SS"
    assert artifact_cv_grade(185.0) == "S"
    assert artifact_cv_grade(175.0) == "A"
    assert artifact_cv_grade(155.0) == "B"
    assert artifact_cv_grade(150.0) == "C"
    assert artifact_cv_grade(110.0) == "C"
    assert artifact_cv_grade(109.9) == "D"
    assert artifact_cv_grade(0.0) == "D"


def test_from_character_passes_talent_names_through():
    data = from_character(_character())
    assert data.talents["normal"].name == "Secret Spear of Wangsheng"
    assert data.talents["skill"].name == "Guide to Afterlife"
    assert data.talents["burst"].name == "Spirit Soother"


def test_from_character_drops_placeholder_talent_names():
    """Enka reports '?' for undiscovered talents — the card falls back to slot labels."""
    ch = _character(talents=[Talent("?", 1), Talent(None, 1), Talent("", 1)])
    data = from_character(ch)
    assert all(not talent.name for talent in data.talents.values())


def test_from_character_tolerates_missing_stats():
    ch = _character(stats=CharacterStats(hp=None, atk=None, defense=None, crit_rate=None,
                                         crit_dmg=None, energy_recharge=None,
                                         elemental_mastery=None, extra={}))
    data = from_character(ch)
    assert data.stats.crit_value == "--"


def test_player_identity_and_uid_reach_the_card():
    data = from_character(_character(), player=PlayerInfo(uid="812345679", nickname="Traveler"))
    assert data.player_uid == "812345679"
    assert data.player_name == "Traveler"
