"""Tests for the layer-based rendering engine."""

from __future__ import annotations

import io

from PIL import Image

from enkarender.config import Settings
from enkarender.layered import (
    LayeredAssetManager,
    LayeredRenderer,
    LayerSpec,
    load_layout,
    parse_layout,
    register_layer,
)
from enkarender.layered.layers import LayerRenderer
from enkarender.layered.layout import parse_color

_LAYOUT = {
    "base_width": 1000,
    "base_height": 1500,
    "background": "#101020ff",
    "layers": [
        {"id": "bg", "type": "background", "z": 0, "color": "#202030ff"},
        {"id": "panel", "type": "panel", "z": 10, "x": 40, "y": 40, "width": 920, "height": 200,
         "fill": "#2a2a3aff", "radius": 20},
        {"id": "name", "type": "text", "z": 20, "x": 60, "y": 60, "font_size": 48,
         "color": "#ffffffff", "text": "{nickname}"},
    ],
}
_DATA = {"nickname": "Wanderer"}


def test_parse_layout_splits_fields_and_props():
    layout = parse_layout(_LAYOUT)
    assert layout.base_width == 1000 and layout.base_height == 1500
    panel = next(l for l in layout.layers if l.id == "panel")
    assert panel.type == "panel" and panel.x == 40 and panel.width == 920
    # Unknown keys land in props.
    assert panel.props["fill"] == "#2a2a3aff" and panel.props["radius"] == 20


def test_parse_color_variants():
    assert parse_color("#ff0000") == (255, 0, 0, 255)
    assert parse_color("#00ff0080") == (0, 255, 0, 128)
    assert parse_color([10, 20, 30]) == (10, 20, 30, 255)
    assert parse_color("nonsense", (1, 2, 3, 4)) == (1, 2, 3, 4)
    # Out-of-range channels are clamped instead of making Pillow raise (dropping the layer).
    assert parse_color([300, -5, 0]) == (255, 0, 0, 255)
    # A non-numeric element yields the default rather than raising ValueError.
    assert parse_color(["x", 0, 0], (1, 2, 3, 4)) == (1, 2, 3, 4)


def test_scaling_multiplies_geometry():
    spec = LayerSpec(id="x", type="text", x=100, y=200, width=300, height=50, font_size=20)
    g1 = spec.scaled(1.0)
    g2 = spec.scaled(2.0)
    assert (g1.x, g1.y, g1.width, g1.height, g1.font_size) == (100, 200, 300, 50, 20)
    assert (g2.x, g2.y, g2.width, g2.height, g2.font_size) == (200, 400, 600, 100, 40)


def test_engine_renders_at_base_and_scaled_resolution(tmp_path):
    assets = LayeredAssetManager(tmp_path / "assets", settings=Settings(home=tmp_path))
    engine = LayeredRenderer(assets)
    layout = parse_layout(_LAYOUT)

    img1 = engine.render(layout, _DATA)  # base 1000x1500
    assert img1.size == (1000, 1500)

    png = engine.render_png(layout, _DATA, target_width=2000)  # 2x, no layout change
    img2 = Image.open(io.BytesIO(png))
    assert img2.size == (2000, 3000) and img2.format == "PNG"


def test_asset_located_and_cached(tmp_path):
    assets_dir = tmp_path / "assets" / "backgrounds"
    assets_dir.mkdir(parents=True)
    Image.new("RGBA", (10, 10)).save(assets_dir / "bg.png")

    mgr = LayeredAssetManager(tmp_path / "assets", settings=Settings(home=tmp_path))
    a = mgr.load("backgrounds", "bg")          # resolves without explicit extension
    b = mgr.load("backgrounds", "bg")
    assert a is not None and a is b            # second load served from the memory cache
    assert mgr.load("backgrounds", "missing") is None


def test_new_template_needs_no_code_change(tmp_path):
    # A completely different layout renders with the same engine/code.
    other = {
        "base_width": 400, "base_height": 400, "background": "#000000ff",
        "layers": [{"id": "t", "type": "text", "x": 10, "y": 10, "text": "hi"}],
    }
    assets = LayeredAssetManager(tmp_path / "assets", settings=Settings(home=tmp_path))
    engine = LayeredRenderer(assets)
    assert engine.render(parse_layout(other), {}).size == (400, 400)


def test_custom_layer_type_registers(tmp_path):
    calls = {"n": 0}

    class _Marker(LayerRenderer):
        def render(self, base, spec, scope):
            calls["n"] += 1

    register_layer("marker", _Marker())
    layout = parse_layout({
        "base_width": 100, "base_height": 100,
        "layers": [{"id": "m", "type": "marker", "x": 0, "y": 0}],
    })
    assets = LayeredAssetManager(tmp_path / "assets", settings=Settings(home=tmp_path))
    LayeredRenderer(assets).render(layout, {})
    assert calls["n"] == 1


def test_bundled_profile_layout_loads():
    from pathlib import Path
    import enkarender.layered as layered

    layout_path = Path(layered.__file__).resolve().parent / "layouts" / "profile.json"
    layout = load_layout(layout_path)
    assert layout.base_width == 1000
    types = {l.type for l in layout.layers}
    # The full stack is represented.
    assert {"background", "panel", "character", "weapon", "artifact", "talent",
            "stat", "text", "effect", "footer"}.issubset(types)
