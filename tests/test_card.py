"""Tests for the character profile card: caption, element theme, and render output."""

from __future__ import annotations

from bot.commands.characters import _build_caption
from bot.models.artifact import Artifact, ArtifactStat
from bot.models.character import Character, CharacterStats, Talent
from bot.models.player import PlayerInfo
from bot.models.ranking import Ranking
from bot.models.weapon import Weapon
from bot.renderer import card_layout
from bot.renderer.context import CharacterCardContext
from bot.renderer.pillow_renderer import PillowRenderer
from bot.utils.text import strip_custom_emoji

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def _character(**kw) -> Character:
    base = dict(
        id="10000046", name="Hu Tao", element="Fire", rarity=5, level=90, constellation=1,
        weapon=Weapon(name="Staff of Homa", level=90, refinement=1, rarity=5),
        talents=[Talent("Normal", 10), Talent("Skill", 9), Talent("Burst", 9)],
        artifacts=[
            Artifact(slot="Flower", set_name="Crimson Witch", rarity=5,
                     main_stat=ArtifactStat("HP", 4780),
                     sub_stats=[ArtifactStat("CRIT Rate", 7.8), ArtifactStat("ATK%", 9.3)]),
        ],
        stats=CharacterStats(hp=15552, atk=2100, defense=876, crit_rate=72.4, crit_dmg=241.0,
                             energy_recharge=128.0, elemental_mastery=120,
                             extra={"FIGHT_PROP_FIRE_ADD_HURT": 0.616}),
    )
    base.update(kw)
    return Character(**base)


def test_elemental_bonus_prefers_on_element_over_larger_off_element():
    """A larger off-element *_ADD_HURT (e.g. Physical DMG) must not override the on-element one."""
    from pytest import approx

    renderer = PillowRenderer()
    stats = CharacterStats(extra={
        "FIGHT_PROP_FIRE_ADD_HURT": 0.616,       # Pyro DMG (on-element)
        "FIGHT_PROP_PHYSICAL_ADD_HURT": 0.90,    # larger, off-element
    })
    assert renderer._elemental_bonus(stats, "Fire") == approx(61.6)


def test_elemental_bonus_falls_back_to_max_when_on_element_absent():
    from pytest import approx

    renderer = PillowRenderer()
    stats = CharacterStats(extra={"FIGHT_PROP_PHYSICAL_ADD_HURT": 0.58})
    assert renderer._elemental_bonus(stats, "Fire") == approx(58.0)


def test_caption_with_ranking():
    ch = _character(ranking=Ranking(rank=2147, total_players=100000, top_percent=0.8,
                                    calculation_name="Hypercarry"))
    cap = _build_caption(ch, PlayerInfo(uid="1", nickname="Traveler"))
    assert "Hu Tao" in cap and "Traveler" in cap
    assert "Rank: #2,147" in cap
    assert "Top 0.8%" in cap
    assert "Category: Hypercarry" in cap
    assert "tg-emoji" in cap  # custom emoji present


def test_caption_marks_missing_ranking_unavailable():
    """No Akasha data -> an explicit unavailable state, not a fabricated '#--' placement.

    A character Enka resolves perfectly well can legitimately have no Akasha ranking (every
    newly released character does), so the card must say so rather than imply a real result.
    """
    ch = _character(ranking=None)
    cap = _build_caption(ch, PlayerInfo(uid="1", nickname=""))
    assert "Rank: Not available" in cap
    assert "Top: Not available" in cap
    assert "Category: Not available" in cap
    # The misleading placeholders are gone.
    assert "#--" not in cap and "--%" not in cap
    # The character itself is still fully identified.
    assert "Hu Tao" in cap
    # And it degrades to plain emoji cleanly.
    assert "tg-emoji" not in strip_custom_emoji(cap)


def test_element_aliases():
    assert card_layout.canonical_element("Fire") == "PYRO"
    assert card_layout.canonical_element("Water") == "HYDRO"
    assert card_layout.canonical_element("Grass") == "DENDRO"
    assert card_layout.theme_for("Ice") is card_layout.ELEMENT_THEMES["CRYO"]
    assert card_layout.theme_for(None) is card_layout.DEFAULT_THEME


def test_render_profile_card_produces_png():
    ch = _character(ranking=Ranking(rank=5, top_percent=1.2, calculation_name="DPS"))
    png = PillowRenderer().render_profile_card(
        CharacterCardContext(language="en", character=ch, player=PlayerInfo(uid="1", nickname="T"),
                             portrait=None)
    )
    assert png.startswith(PNG_MAGIC)


def test_render_profile_card_no_ranking_still_renders():
    ch = _character(ranking=None)
    png = PillowRenderer().render_profile_card(
        CharacterCardContext(language="en", character=ch, player=PlayerInfo(uid="1"))
    )
    assert png.startswith(PNG_MAGIC)


def test_render_with_constellation_lock_states():
    from bot.models.character import ConstellationNode
    nodes = [ConstellationNode(name=f"C{i+1}", unlocked=(i < 3)) for i in range(6)]
    ch = _character(constellation=3, constellations=nodes, ranking=None)
    png = PillowRenderer().render_profile_card(
        CharacterCardContext(language="en", character=ch, player=PlayerInfo(uid="1"))
    )
    assert png.startswith(PNG_MAGIC)


def test_render_full_card_with_portrait_and_icons_is_correct_size():
    """Exercises the placeholder-erase + icon paths and checks the fixed 1280x720 output."""
    import io

    from PIL import Image

    portrait = Image.new("RGBA", (400, 700), (0, 0, 0, 0))
    icon = Image.new("RGBA", (96, 96), (200, 80, 60, 255))
    ch = _character(
        constellation=2,
        weapon=Weapon(name="Staff of Homa", level=90, refinement=1, rarity=5,
                      weapon_type="Polearm", icon="w"),
        talents=[Talent("Normal", 9, icon="t1"), Talent("Skill", 9, icon="t2"),
                 Talent("Burst", 10, icon="t3")],
        ranking=None,
    )
    for a in ch.artifacts:
        a.icon = "art"
    icons = {u: icon for u in ("w", "t1", "t2", "t3", "art")}
    png = PillowRenderer().render_profile_card(
        CharacterCardContext(language="en", character=ch,
                             player=PlayerInfo(uid="1", nickname="Traveler"),
                             portrait=portrait, icons=icons)
    )
    assert png.startswith(PNG_MAGIC)
    assert Image.open(io.BytesIO(png)).size == card_layout.CARD_SIZE


def test_weapon_type_and_url_helpers():
    from bot.api.enka_client import _as_url, _weapon_type
    assert _weapon_type("WEAPON_SWORD_ONE_HAND") == "Sword"
    assert _weapon_type("WEAPON_POLE") == "Polearm"
    assert _weapon_type("WEAPON_BOW") == "Bow"
    assert _as_url("https://enka.network/ui/x.png") == "https://enka.network/ui/x.png"
    assert _as_url(None) is None


def test_serialize_roundtrips_constellations():
    from bot.models.character import ConstellationNode
    from bot.models.serialize import showcase_from_dict, showcase_to_dict
    from bot.models.player import Showcase
    ch = _character(constellations=[ConstellationNode(name="C1", unlocked=True, icon="u")])
    sc = Showcase(player=PlayerInfo(uid="1"), characters=[ch])
    back = showcase_from_dict(showcase_to_dict(sc))
    node = back.characters[0].constellations[0]
    assert node.name == "C1" and node.unlocked is True and node.icon == "u"
