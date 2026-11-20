"""End-to-end validation of the production render path.

Only the network boundary is faked — the HTTP call to Enka, and the artwork downloads.
Everything between is the real production code:

    EnkaClient (real post-processing)  ->  CharacterService  ->  characters._render_card_png
      ->  ArtworkService  ->  card_data.from_character  ->  CharacterCardRenderer  ->  PNG

So a regression anywhere in mapping, normalization, formatting or layout fails here, and the
assertions check the values that actually reach the card rather than the values we fed in.
"""

from __future__ import annotations

import io
from types import SimpleNamespace

import pytest
from PIL import Image

from bot.api.enka_client import EnkaClient
from bot.commands import characters
from bot.models.player import PlayerInfo
from bot.renderer.card_data import from_character
from bot.renderer.card_layout import theme_for
from tests.enka_payloads import ARLECCHINO, ODETTE, showcase_payload


class _StubArtwork:
    """Stands in for the network only. Records every URL the resolver was asked for."""

    def __init__(self, missing: set[str] | None = None) -> None:
        self.requested: list[str] = []
        self._missing = missing or set()

    async def get_portrait(self, character):
        self.requested.append(character.art or "")
        return Image.new("RGBA", (2048, 1024), (30, 20, 20, 255))

    async def get_images(self, urls):
        out = {}
        for url in urls:
            self.requested.append(url)
            if url not in self._missing:
                out[url] = Image.new("RGBA", (128, 128), (200, 180, 120, 255))
        return out


class _Legacy:
    def __init__(self) -> None:
        self.calls = 0

    def render_profile_card(self, ctx):
        self.calls += 1
        return b"LEGACY"


@pytest.fixture
def enka_via_payload(monkeypatch):
    """Real EnkaClient with only its HTTP fetch replaced."""

    async def _fetch(self, uid, language):
        payload = getattr(_fetch, "payload")
        import enka  # noqa: PLC0415 - optional dependency, imported like production does

        client = enka.GenshinClient(self._resolve_language(enka, language))
        await client.start()
        try:
            return client.parse_showcase(payload)
        finally:
            await client.close()

    def install(spec):
        _fetch.payload = showcase_payload(*spec)
        monkeypatch.setattr(EnkaClient, "_fetch_raw", _fetch)

    return install


pytest.importorskip("enka", reason="enka library required for the real mapping path")

# These tests run enka's *real* post-processing, which needs its game metadata on disk.
# enka downloads that on first use — so without this guard the suite would silently make a
# network call. Skip instead: the rest of the suite stays hermetic, and these run wherever
# the metadata already exists (dev containers, and CI once it caches .enka_py/).
_ASSETS_READY = True
try:
    from enka.assets.gi.file_paths import CHARACTER_DATA_PATH as _CHAR_DATA

    _ASSETS_READY = _CHAR_DATA.exists()
except Exception:  # noqa: BLE001
    _ASSETS_READY = False

pytestmark = pytest.mark.skipif(
    not _ASSETS_READY,
    reason="enka game metadata not present; run the bot once (or prefetch .enka_py/) to enable",
)


async def _render(spec, artwork=None):
    """Run one character through the exact production render function."""
    client = EnkaClient()
    showcase = await client.fetch_showcase("901211014")
    character = showcase.characters[0]
    art = artwork or _StubArtwork()
    legacy = _Legacy()
    app = SimpleNamespace(artwork_service=art, renderer=legacy)
    png = await characters._render_card_png(app, character, PlayerInfo(uid="901211014"), "en")
    return character, art, legacy, png


async def test_real_pipeline_populates_every_card_field(enka_via_payload):
    """Assert the normalized CardData the renderer receives, not the raw input."""
    enka_via_payload(ARLECCHINO)
    character, _, _, _ = await _render(ARLECCHINO)
    data = from_character(character, glow=theme_for(character.element)["glow"])

    c = data.character
    assert c.id == "10000096"
    assert c.name == "Arlecchino"
    assert c.element == "Fire"
    assert c.level == 90
    assert c.constellation == 1
    assert c.friendship == 10
    assert c.rarity == 5

    w = data.weapon
    assert w is not None
    assert w.name == "Mistsplitter Reforged"       # resolved from the real text map
    assert w.level_text == "Lv. 90 / 90"
    assert w.refinement_text == "R5"
    assert w.base_attack == "674"
    assert w.secondary_stat == "22.1%"

    s = data.stats
    assert s.hp == "20,023" and s.atk == "1,891" and s.defense == "866"
    assert s.em == "203"
    assert s.crit_rate == "81.5%" and s.crit_dmg == "206.6%"
    assert s.energy_recharge == "100.0%"
    assert s.elemental_bonus == "46.6%"
    # Dynamic, never hardcoded: a Pyro character gets the Pyro row.
    assert s.elemental_bonus_name == "Pyro DMG Bonus"

    assert len(data.talents) == 3
    assert all(t.level_text.startswith("Lv. ") for t in data.talents.values())

    assert set(data.artifacts) == {"flower", "plume", "sands", "goblet", "circlet"}
    for slot, art in data.artifacts.items():
        assert art is not None, slot
        assert art.rarity == 5
        assert art.main_stat and art.main_value
        assert len(art.substats) == 4
        assert all(v.startswith("+") for _, v in art.substats)

    assert data.artifact_set is not None
    assert data.artifact_set.name.startswith("Resolution of Sojourner")

    # Base panel and bottom summary read the same fields, so they cannot disagree.
    panel = dict(s.rows())
    summary = dict(s.summary_rows())
    for key in ("crit-rate", "crit-dmg", "atk", "def", "em", "elemental-bonus"):
        assert panel[key] == summary[key]
    assert summary["er"] == panel["energy-recharge"]


async def test_production_path_output_is_a_valid_1536x864_png(enka_via_payload):
    enka_via_payload(ARLECCHINO)
    _, _, legacy, png = await _render(ARLECCHINO)

    assert legacy.calls == 0, "successful renders must not touch the legacy renderer"
    img = Image.open(io.BytesIO(png))
    assert img.format == "PNG"
    assert img.size == (1536, 864)
    assert len(png) > 50_000


async def test_asset_resolver_is_asked_for_every_slot(enka_via_payload):
    """The renderer never discovers URLs — the artwork service resolves them all."""
    enka_via_payload(ARLECCHINO)
    _, art, _, _ = await _render(ARLECCHINO)

    urls = art.requested
    assert any("Gacha_AvatarImg" in u for u in urls), "character splash"
    assert any("UI_EquipIcon" in u for u in urls), "weapon"
    assert sum("Skill_" in u for u in urls) >= 3, "three talent icons"
    assert sum("UI_RelicIcon" in u for u in urls) >= 5, "five artifact icons"
    assert all(u.startswith("http") for u in urls if u), "all resolved to real CDN URLs"


async def test_a_missing_asset_leaves_the_slot_empty_without_breaking_layout(enka_via_payload):
    """ASSET NOT AVAILABLE must degrade the slot, never the card."""
    enka_via_payload(ARLECCHINO)
    client = EnkaClient()
    character = (await client.fetch_showcase("901211014")).characters[0]
    missing = {character.weapon.icon}

    art = _StubArtwork(missing=missing)
    legacy = _Legacy()
    app = SimpleNamespace(artwork_service=art, renderer=legacy)
    png = await characters._render_card_png(app, character, PlayerInfo(uid="1"), "en")

    assert legacy.calls == 0, "a missing asset is not a rendering failure"
    assert Image.open(io.BytesIO(png)).size == (1536, 864)


async def test_newly_released_character_renders_with_no_code_changes(enka_via_payload):
    """A character absent from any local dictionary must flow through unchanged.

    Odette appears here only as an avatar id; nothing in bot/ names her. If the pipeline
    needed a per-character entry, this would fail.
    """
    enka_via_payload(ODETTE)
    character, art, legacy, png = await _render(ODETTE)

    assert character.id == "10000150"
    assert character.name == "Odette", "resolved dynamically from upstream metadata"
    assert character.element == "Ice"

    data = from_character(character, glow=theme_for(character.element)["glow"])
    assert data.stats.elemental_bonus_name == "Cryo DMG Bonus", "element-driven, not hardcoded"
    assert data.weapon is not None and data.weapon.name == "Mistsplitter Reforged"
    assert all(a is not None for a in data.artifacts.values())

    assert legacy.calls == 0
    assert Image.open(io.BytesIO(png)).size == (1536, 864)
    assert any("Gacha_AvatarImg_Odette" in u for u in art.requested), "real splash art URL"


async def test_element_labels_follow_the_character_not_the_template(enka_via_payload):
    """The template bakes "Pyro DMG Bonus"; a Cryo character must not inherit it."""
    enka_via_payload(ODETTE)
    client = EnkaClient()
    character = (await client.fetch_showcase("901211014")).characters[0]
    data = from_character(character, glow=theme_for(character.element)["glow"])

    assert data.stats.elemental_bonus_name == "Cryo DMG Bonus"

    # Both label slots exist so the renderer can cover the baked text.
    from bot.renderer.slot_manager import get_layout

    layout = get_layout()
    assert layout.text_slot("stat-elemental-bonus-label") is not None
    assert layout.text_slot("summary-elemental-bonus-label") is not None


def test_generated_pngs_are_valid_1536x864(tmp_path):
    """Any card PNG produced into tests/output must satisfy the output contract."""
    from pathlib import Path

    out = Path(__file__).resolve().parent / "output"
    pngs = sorted(out.glob("*.png")) if out.exists() else []
    if not pngs:
        pytest.skip("no rendered output present (run the render scripts first)")
    for path in pngs:
        img = Image.open(path)
        assert img.format == "PNG", path.name
        assert img.size == (1536, 864), f"{path.name} is {img.size}"
        assert path.stat().st_size > 10_000, path.name
