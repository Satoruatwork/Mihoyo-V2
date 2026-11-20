"""Smoke tests for the Pillow renderer (produces valid PNG bytes)."""

from __future__ import annotations

from bot.models.abyss import AbyssData
from bot.models.character import Character, CharacterStats
from bot.models.player import PlayerInfo
from bot.models.weapon import Weapon
from bot.renderer.context import AbyssCardContext, CharacterCardContext
from bot.renderer.pillow_renderer import PillowRenderer

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def test_character_card_produces_png():
    r = PillowRenderer()
    char = Character(
        id="10000046",
        name="Hu Tao",
        level=90,
        constellation=1,
        weapon=Weapon(name="Staff of Homa", level=90, refinement=1),
        stats=CharacterStats(hp=15000, atk=2000, crit_rate=70.5, crit_dmg=200.0),
    )
    png = r.render_character_card(CharacterCardContext(language="en", character=char, player=PlayerInfo(uid="1")))
    assert png.startswith(PNG_MAGIC)


def test_abyss_card_unavailable_still_renders():
    r = PillowRenderer()
    png = r.render_abyss_card(AbyssCardContext(language="en", abyss=AbyssData(uid="1")))
    assert png.startswith(PNG_MAGIC)
