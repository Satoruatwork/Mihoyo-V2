"""The SVG layout is the machine-readable source of truth for card geometry.

These tests pin the contract the renderer depends on: the canvas resolves to the required
1536x864, every slot the card needs exists, and no dynamic slot silently loses its geometry.
"""

from __future__ import annotations

import pytest

from bot.renderer.slot_manager import ImageSlot, TextSlot, get_layout, load_layout


@pytest.fixture(scope="module")
def layout():
    return get_layout()


def test_canvas_is_1536x864_from_a_native_1280x720_viewbox(layout):
    """Coordinates stay in the template's measured pixel space; output is scaled 1.2x."""
    assert (layout.view_width, layout.view_height) == (1280, 720)
    assert (layout.out_width, layout.out_height) == (1536, 864)
    assert layout.scale == pytest.approx(1.2)


def test_every_required_slot_group_is_present(layout):
    required_images = {
        "character-image", "weapon-image", "artifact-set-image",
        "talent-normal-image", "talent-skill-image", "talent-burst-image",
        *(f"artifact-{s}-image" for s in ("flower", "plume", "sands", "goblet", "circlet")),
    }
    assert required_images <= set(layout.images)

    required_text = {
        "character-name", "character-level", "character-constellation",
        "weapon-name", "weapon-base-attack", "weapon-secondary-stat",
        "weapon-level", "weapon-refinement",
        "stat-hp", "stat-atk", "stat-def", "stat-em",
        "stat-crit-rate", "stat-crit-dmg", "stat-energy-recharge", "stat-elemental-bonus",
        "artifact-set-name", "artifact-set-2pc", "artifact-set-4pc",
        "summary-crit-rate", "summary-atk", "summary-elemental-bonus",
    }
    assert required_text <= set(layout.text)


def test_each_artifact_exposes_the_same_component_structure(layout):
    """All five positions are identical components differing only in position."""
    shapes = {}
    for slot in ("flower", "plume", "sands", "goblet", "circlet"):
        roles = layout.artifact_slots(slot)
        shapes[slot] = set(roles)
        assert "image" in roles and "main-stat" in roles and "main-value" in roles
        for i in range(1, 5):
            assert f"substat-{i}-name" in roles
            assert f"substat-{i}-value" in roles
    assert len(set(map(frozenset, shapes.values()))) == 1, "components must be uniform"


def test_artifact_positions_differ_while_structure_matches(layout):
    ys = [layout.image_slot(f"artifact-{s}-image").y
          for s in ("flower", "plume", "sands", "goblet", "circlet")]
    assert ys == sorted(ys)
    gaps = [ys[i + 1] - ys[i] for i in range(4)]
    assert all(g == 115 for g in gaps), gaps


def test_numeric_stat_values_are_end_anchored(layout):
    """A longer number must not shift its row, so stat values right-align."""
    for key in ("hp", "atk", "def", "em", "crit-rate", "crit-dmg",
                "energy-recharge", "elemental-bonus"):
        slot = layout.text_slot(f"stat-{key}")
        assert slot.anchor == "end", key
        assert slot.pil_anchor == "rm"


def test_every_text_slot_can_shrink_to_fit(layout):
    """Text auto-fit needs a real max width and a floor below the nominal size."""
    for slot in layout.text.values():
        assert slot.max_width > 0, slot.id
        assert 0 < slot.min_size <= slot.size, slot.id


def test_every_image_slot_has_a_real_box_and_fit_rule(layout):
    for slot in layout.images.values():
        assert slot.width > 0 and slot.height > 0, slot.id
        assert slot.fit in ("contain", "cover"), slot.id
        assert slot.clip in ("rect", "circle", "stadium"), slot.id


def test_character_image_fills_the_frame_without_distortion(layout):
    """Splash art is 'cover': it fills the pill window and the mask crops the overflow.

    'contain' would letterbox it — Enka's splash sheets are landscape, so containing a
    2048x1024 sheet in a 186x480 portrait window shrinks the character to a sliver.
    Aspect ratio is preserved either way; image_fitter applies one ratio to both axes.
    """
    slot = layout.image_slot("character-image")
    assert slot.fit == "cover"
    assert slot.clip == "stadium", "clipped to the frame's pill window"


def test_unknown_slots_return_none_rather_than_raising(layout):
    assert layout.text_slot("does-not-exist") is None
    assert layout.image_slot("does-not-exist") is None


def test_layout_reloads_from_disk(tmp_path):
    """load_layout parses a file directly; get_layout is the cached process-wide view."""
    fresh = load_layout()
    assert isinstance(fresh.text["character-name"], TextSlot)
    assert isinstance(fresh.images["character-image"], ImageSlot)


# --------------------------------------------------------------------------- fitters
def test_image_fitter_preserves_aspect_ratio():
    """One ratio on both axes — an image can be cropped, never stretched."""
    from PIL import Image

    from bot.renderer.image_fitter import fit

    src = Image.new("RGBA", (2048, 1024))
    for mode in ("contain", "cover"):
        out = fit(src, 186, 480, mode=mode)
        assert abs(out.width / out.height - 2.0) < 0.02, mode


def test_image_fitter_trims_transparent_padding():
    """Enka splash sheets pad the character with transparency, differently per character."""
    from PIL import Image

    from bot.renderer.image_fitter import trim_transparent

    src = Image.new("RGBA", (400, 400), (0, 0, 0, 0))
    src.paste(Image.new("RGBA", (50, 80), (255, 0, 0, 255)), (100, 60))
    assert trim_transparent(src).size == (50, 80)


def test_text_fitter_shrinks_then_truncates():
    from PIL import Image, ImageDraw, ImageFont

    from bot.renderer.slot_manager import TextSlot
    from bot.renderer.text_fitter import fit_text

    draw = ImageDraw.Draw(Image.new("RGB", (10, 10)))
    font_for = lambda size, weight=400: ImageFont.load_default(size)  # noqa: E731
    slot = TextSlot(id="t", x=0, y=0, size=20, max_width=60, min_size=8)

    short, _ = fit_text(draw, "Hi", slot, font_for)
    assert short == "Hi", "short text is untouched"

    long_text = "Fragment of Harmonic Whimsy and Then Some More Words"
    fitted, font = fit_text(draw, long_text, slot, font_for)
    assert draw.textlength(fitted, font=font) <= slot.max_width
    assert fitted.endswith("…"), "falls back to truncation once at min size"


# --------------------------------------------------------------------------- production path
async def test_production_render_path_uses_the_slot_renderer(monkeypatch):
    """/mycharacters -> _render_card_png -> CharacterCardRenderer, at 1536x864.

    Asserts the real production function, not the renderer in isolation.
    """
    from types import SimpleNamespace

    from PIL import Image

    from bot.commands import characters
    from bot.models.character import Character, CharacterStats
    from bot.models.player import PlayerInfo

    used = {"legacy": 0}

    class _Artwork:
        async def get_portrait(self, character):
            return Image.new("RGBA", (2048, 1024), (10, 10, 10, 255))

        async def get_images(self, urls):
            return {}

    class _Legacy:
        def render_profile_card(self, ctx):
            used["legacy"] += 1
            return b"LEGACY"

    app = SimpleNamespace(artwork_service=_Artwork(), renderer=_Legacy())
    character = Character(id="10000096", name="Arlecchino", element="Fire", rarity=5,
                          level=90, constellation=1, stats=CharacterStats(hp=20023))

    png = await characters._render_card_png(app, character, PlayerInfo(uid="1"), "en")

    assert used["legacy"] == 0, "the legacy renderer must not serve successful requests"
    assert Image.open(__import__("io").BytesIO(png)).size == (1536, 864)


async def test_production_render_falls_back_when_the_new_renderer_raises(monkeypatch, caplog):
    """A rendering bug degrades to the old renderer loudly, never silently."""
    from types import SimpleNamespace

    from PIL import Image

    from bot.commands import characters
    from bot.models.character import Character
    from bot.models.player import PlayerInfo

    class _Artwork:
        async def get_portrait(self, character):
            return Image.new("RGBA", (64, 64))

        async def get_images(self, urls):
            return {}

    class _Legacy:
        def render_profile_card(self, ctx):
            return b"LEGACY"

    class _Broken:
        def render(self, data, *, debug=False):
            raise RuntimeError("boom")

    monkeypatch.setattr(characters, "get_card_renderer", lambda: _Broken())
    app = SimpleNamespace(artwork_service=_Artwork(), renderer=_Legacy())

    with caplog.at_level("ERROR"):
        png = await characters._render_card_png(
            app, Character(id="1", name="X"), PlayerInfo(uid="1"), "en")

    assert png == b"LEGACY"
    assert "[RENDERER] New renderer failed, using fallback renderer" in caplog.text
