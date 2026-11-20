"""Layer-based rendering engine (Photoshop-style, JSON-driven).

A card is composed as an ordered stack of independent layers — background, decorative
overlays, panels, frames, character splash, weapon, artifacts, talents, elements, stats,
text, effects, footer — each drawn by its own renderer and positioned entirely from a JSON
layout (no hardcoded coordinates). Assets are auto-located from category folders and cached;
fonts are managed centrally; layouts scale to any resolution. A brand-new template is a new
JSON layout + assets with zero code changes.

    from enkarender.layered import LayeredRenderer, LayeredAssetManager, load_layout

    assets = LayeredAssetManager("assets")
    engine = LayeredRenderer(assets)
    png = engine.render_png(load_layout("layout.json"), data, target_width=1500)
"""

from __future__ import annotations

from enkarender.layered.assets import LayeredAssetManager
from enkarender.layered.engine import LayeredRenderer
from enkarender.layered.layers import REGISTRY, LayerRenderer, RenderScope, register_layer
from enkarender.layered.layout import Layout, LayerSpec, load_layout, parse_layout

__all__ = [
    "LayeredRenderer",
    "LayeredAssetManager",
    "Layout",
    "LayerSpec",
    "load_layout",
    "parse_layout",
    "LayerRenderer",
    "RenderScope",
    "register_layer",
    "REGISTRY",
]
