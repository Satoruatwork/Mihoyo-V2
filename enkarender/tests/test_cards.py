"""Card builders + parser: end-to-end from domain model to PNG (offline), and the parser."""

from __future__ import annotations

import io
import json
from pathlib import Path

from PIL import Image

from enkarender.assets.manager import AssetManager
from enkarender.cards.base import registry as card_registry
from enkarender.config import Settings
from enkarender.enums import Element
from enkarender.fonts.manager import FontManager
from enkarender.models.domain import Artifact, Character, Player, Showcase, Stat, Weapon
from enkarender.models.parser import parse_showcase

# Ensure templates + builders are registered.
import enkarender.templates  # noqa: F401
import enkarender.cards  # noqa: F401

FIXTURE = Path(__file__).resolve().parent.parent / "example" / "fixture.json"


def _sample_character() -> Character:
    return Character(
        id="10000037", name="Ganyu", element=Element.CRYO, rarity=5, level=90, constellation=1,
        weapon=Weapon(name="Amos' Bow", level=90, refinement=1, rarity=5,
                      main_stat=Stat("Base ATK", 608), sub_stat=Stat("CRIT DMG", 33.1, True)),
        artifacts=[Artifact(slot="Flower", level=20, set_name="Blizzard Strayer",
                            main_stat=Stat("HP", 4780))],
        stats=[Stat("CRIT Rate", 71.6, True), Stat("CRIT DMG", 152.3, True)],
    )


async def test_build_card_produces_png(settings):
    assets = AssetManager(settings=settings)
    fonts = FontManager(settings)
    builder = card_registry.create("build", assets, fonts)
    png = await builder.build(_sample_character())
    img = Image.open(io.BytesIO(png))
    assert img.format == "PNG"
    assert img.size == (900, 1200)


async def test_profile_card_produces_png(settings):
    assets = AssetManager(settings=settings)
    fonts = FontManager(settings)
    showcase = Showcase(player=Player(uid="800000001", nickname="Wanderer", level=60),
                        characters=[_sample_character()])
    builder = card_registry.create("profile", assets, fonts)
    png = await builder.build(showcase)
    assert Image.open(io.BytesIO(png)).size == (960, 540)


def test_parser_reads_fixture():
    raw = json.loads(FIXTURE.read_text(encoding="utf-8"))
    showcase = parse_showcase(raw, resolve_name=lambda h: {"W1": "Amos' Bow"}.get(str(h)))
    assert showcase.player.nickname == "Wanderer"
    assert len(showcase.characters) == 2
    ganyu = showcase.characters[0]
    assert ganyu.name == "Ganyu"
    assert ganyu.element is Element.CRYO
    assert ganyu.constellation == 1
    assert ganyu.weapon is not None and ganyu.weapon.name == "Amos' Bow"
    # Elemental DMG goblet main stat is prettified + percent, not a raw enum.
    goblet = next(a for a in ganyu.artifacts if a.slot == "Goblet")
    assert goblet.main_stat.name == "Cryo DMG" and goblet.main_stat.percent


def test_new_card_type_registers_without_touching_others():
    from enkarender.cards.base import CardBuilder, CardRegistry
    from enkarender.render.draw import Theme

    class _NoopBuilder(CardBuilder):
        key = "noop"
        template_key = "build"

        def _view_model(self, data):
            return {}

        def _theme(self, data):
            return Theme()

        async def _load_images(self, data):
            return {}

    reg = CardRegistry()
    reg.register(_NoopBuilder)
    assert reg.keys() == ["noop"]  # isolated; does not affect the global registry
