"""Per-layer renderers.

Each class draws exactly **one** kind of layer and nothing else, reading its position and
style entirely from the :class:`~enkarender.layered.layout.LayerSpec` (never hardcoded).
They all share the same signature ``render(base, spec, scope)`` and composite their sprite
onto the shared canvas — so the engine just stacks them in z-order.

Layer types map to renderers via :data:`REGISTRY`; adding a new visual layer type is a new
class + one registry entry, with no change to the engine.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from PIL import Image, ImageDraw

from enkarender.layered.assets import (
    LayeredAssetManager,
    apply_opacity,
    compose,
    contain_fit,
    placeholder,
)
from enkarender.layered.layout import LayerSpec, parse_color
from enkarender.logging import get_logger
from enkarender.render.draw import DrawingUtils

logger = get_logger("layered.layers")


@dataclass(slots=True)
class RenderScope:
    """Everything a layer needs at render time: scale factor, assets/fonts, and the data."""

    scale: float
    assets: LayeredAssetManager
    data: dict[str, Any]


class LayerRenderer:
    """Base class — subclasses implement :meth:`render` for their single layer type."""

    def render(self, base: Image.Image, spec: LayerSpec, scope: RenderScope) -> None:  # noqa: D401
        raise NotImplementedError

    # shared helpers -------------------------------------------------------
    @staticmethod
    def _asset_name(spec: LayerSpec, scope: RenderScope) -> str | None:
        """Resolve the asset filename: a literal ``asset`` or a value from a ``from`` data key."""
        frm = spec.props.get("from")
        if frm and isinstance(scope.data.get(frm), str):
            return scope.data[frm]
        return spec.props.get("asset")

    @staticmethod
    def _text(spec: LayerSpec, scope: RenderScope) -> str:
        """Resolve a text template against the data dict (missing keys tolerated)."""
        template = str(spec.props.get("text", ""))
        try:
            return template.format_map(_SafeDict(scope.data))
        except Exception:  # noqa: BLE001
            return template


class _SafeDict(dict):
    def __missing__(self, key):  # leave unknown placeholders untouched
        return "{" + key + "}"


# --------------------------------------------------------------------------- background
class BackgroundRenderer(LayerRenderer):
    """Fills the entire canvas with a background image (cover-fit) or a solid colour."""

    def render(self, base, spec, scope):
        name = self._asset_name(spec, scope)
        if name:
            img = scope.assets.load("backgrounds", name)
            if img is not None:
                sprite = DrawingUtils.cover_fit(img, base.size)
                compose(base, sprite, 0, 0, opacity=spec.opacity)
                return
        # Solid fill fallback.
        base.alpha_composite(Image.new("RGBA", base.size, spec.rgba))


# --------------------------------------------------------------------------- panel (shape)
class PanelRenderer(LayerRenderer):
    """Draws a rounded rectangle panel (fill + optional outline)."""

    def render(self, base, spec, scope):
        g = spec.scaled(scope.scale)
        if g.width <= 0 or g.height <= 0:
            return
        sprite = Image.new("RGBA", (g.width, g.height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(sprite)
        radius = int(spec.props.get("radius", 24) * scope.scale)
        fill = parse_color(spec.props.get("fill"), spec.rgba)
        outline = parse_color(spec.props.get("outline"), (0, 0, 0, 0))
        width = int(spec.props.get("outline_width", 0) * scope.scale)
        DrawingUtils.rounded_rectangle(
            draw, (0, 0, g.width - 1, g.height - 1), radius,
            fill=fill, outline=outline if width else None, width=max(1, width),
        )
        compose(base, sprite, g.x, g.y, rotation=spec.rotation, opacity=spec.opacity)


# --------------------------------------------------------------------------- generic image
class ImageLayerRenderer(LayerRenderer):
    """Places a single image (contain-fit) from a category into the layer box.

    Used for frames, element badges, decorative overlays — anything that is just a
    positioned picture. The category defaults to the layer ``type`` (so ``frame`` reads
    ``frames/``) but can be overridden via ``props.category``.
    """

    default_category = "overlays"
    fit = "contain"

    def render(self, base, spec, scope):
        g = spec.scaled(scope.scale)
        category = spec.props.get("category") or _CATEGORY_BY_TYPE.get(spec.type, self.default_category)
        name = self._asset_name(spec, scope)
        if not name:
            return
        img = scope.assets.load(category, name)
        if img is None:
            img = placeholder((g.width or 64, g.height or 64), spec.type)
        box = (g.width or img.width, g.height or img.height)
        sprite = DrawingUtils.cover_fit(img, box) if self.fit == "cover" else contain_fit(img, box)
        compose(base, sprite, g.x, g.y, rotation=spec.rotation, opacity=spec.opacity)


class CharacterRenderer(ImageLayerRenderer):
    """Character splash art — cover-fit, optional circular crop (``props.shape=="circle"``)."""

    default_category = "characters"
    fit = "cover"

    def render(self, base, spec, scope):
        g = spec.scaled(scope.scale)
        name = self._asset_name(spec, scope)
        img = scope.assets.load("characters", name) if name else None
        if img is None:
            img = placeholder((g.width or 256, g.height or 256), "character")
        if spec.props.get("shape") == "circle":
            sprite = DrawingUtils.circular(img).resize((g.width, g.height))
        else:
            sprite = DrawingUtils.cover_fit(img, (g.width or img.width, g.height or img.height))
        compose(base, sprite, g.x, g.y, rotation=spec.rotation, opacity=spec.opacity)


class WeaponRenderer(ImageLayerRenderer):
    """Weapon icon — contain-fit so the whole weapon is visible."""

    default_category = "weapons"
    fit = "contain"


# --------------------------------------------------------------------------- repeated icons
class _RepeatIconRenderer(LayerRenderer):
    """Shared logic for grids/rows of icons driven by a data list."""

    category = "icons"

    def _items(self, spec, scope) -> list:
        return list(scope.data.get(spec.props.get("from", ""), []) or [])

    def render(self, base, spec, scope):
        g = spec.scaled(scope.scale)
        items = self._items(spec, scope)
        if not items or g.width <= 0 or g.height <= 0:
            return
        columns = int(spec.props.get("columns", len(items)))
        gap_x = int(spec.props.get("gap_x", 0) * scope.scale)
        gap_y = int(spec.props.get("gap_y", 0) * scope.scale)
        for i, item in enumerate(items):
            col, rowi = i % columns, i // columns
            x = g.x + col * (g.width + gap_x)
            y = g.y + rowi * (g.height + gap_y)
            self._draw_item(base, spec, scope, g, item, x, y)

    def _draw_item(self, base, spec, scope, g, item, x, y):
        name = item if isinstance(item, str) else (item or {}).get("asset")
        img = scope.assets.load(self.category, name) if name else None
        if img is None:
            img = placeholder((g.width, g.height), "")
        sprite = contain_fit(img, (g.width, g.height))
        compose(base, sprite, x, y, opacity=spec.opacity)


class ArtifactRenderer(_RepeatIconRenderer):
    """A row/grid of artifact icons (``props.from`` -> list of names/objects)."""

    category = "artifacts"


class TalentRenderer(_RepeatIconRenderer):
    """A row/grid of talent icons."""

    category = "icons"


class StatRenderer(LayerRenderer):
    """A vertical list of stat rows: an element/stat icon plus its value text."""

    def render(self, base, spec, scope):
        g = spec.scaled(scope.scale)
        rows = list(scope.data.get(spec.props.get("from", ""), []) or [])
        if not rows:
            return
        gap_y = int(spec.props.get("gap_y", 12) * scope.scale)
        icon_size = int(spec.props.get("icon_size", spec.font_size) * scope.scale)
        font = scope.assets.fonts.get(g.font_size, int(spec.props.get("weight", 400)), spec.font)
        for i, row in enumerate(rows):
            y = g.y + i * (icon_size + gap_y)
            icon_name = row.get("icon") if isinstance(row, dict) else None
            if icon_name:
                icon = scope.assets.load("icons", icon_name) or scope.assets.load("elements", icon_name)
                if icon is not None:
                    compose(base, contain_fit(icon, (icon_size, icon_size)), g.x, y, opacity=spec.opacity)
            value = str(row.get("value", "")) if isinstance(row, dict) else str(row)
            tx = g.x + icon_size + int(8 * scope.scale)
            _draw_text(base, value, (tx, y), font, spec.rgba, "left", spec.rotation, spec.opacity)


# --------------------------------------------------------------------------- text
class TextRenderer(LayerRenderer):
    """Dynamic text — font/size/colour/alignment/rotation/opacity from the layout."""

    def render(self, base, spec, scope):
        g = spec.scaled(scope.scale)
        text = self._text(spec, scope)
        if not text:
            return
        weight = int(spec.props.get("weight", 400))
        font = scope.assets.fonts.get(g.font_size, weight, spec.font)
        _draw_text(base, text, (g.x, g.y), font, spec.rgba, spec.align, spec.rotation, spec.opacity,
                   shadow=parse_color(spec.props.get("shadow"), (0, 0, 0, 0)))


class FooterRenderer(TextRenderer):
    """Footer text (or image) pinned by the layout — same mechanics as TextRenderer.

    If the layer provides an ``asset``/``from`` instead of ``text``, it renders that image.
    """

    def render(self, base, spec, scope):
        if self._asset_name(spec, scope) and not spec.props.get("text"):
            ImageLayerRenderer().render(base, spec, scope)
            return
        super().render(base, spec, scope)


# --------------------------------------------------------------------------- effects
class EffectRenderer(LayerRenderer):
    """A visual-effect overlay (glow/particles) alpha-composited over everything below it."""

    def render(self, base, spec, scope):
        g = spec.scaled(scope.scale)
        name = self._asset_name(spec, scope)
        if not name:
            return
        img = scope.assets.load("effects", name)
        if img is None:
            return
        box = (g.width or base.width, g.height or base.height)
        sprite = DrawingUtils.cover_fit(img, box)
        compose(base, sprite, g.x, g.y, rotation=spec.rotation, opacity=spec.opacity)


# --------------------------------------------------------------------------- text helper
def _draw_text(base, text, xy, font, color, align, rotation, opacity, shadow=(0, 0, 0, 0)):
    """Render (possibly multi-line) text to a sprite, then composite with align/rotation/opacity."""
    measure = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    bbox = measure.multiline_textbbox((0, 0), text, font=font)
    w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
    pad = 4
    sprite = Image.new("RGBA", (w + 2 * pad, h + 2 * pad), (0, 0, 0, 0))
    draw = ImageDraw.Draw(sprite)
    if shadow[3]:
        draw.multiline_text((pad + 2, pad + 2 - bbox[1]), text, font=font, fill=shadow)
    draw.multiline_text((pad, pad - bbox[1]), text, font=font, fill=color)

    x, y = xy
    if align == "center":
        x -= (w + 2 * pad) // 2
    elif align == "right":
        x -= (w + 2 * pad)
    compose(base, sprite, x, y, rotation=rotation, opacity=opacity)


# --------------------------------------------------------------------------- registry
_CATEGORY_BY_TYPE = {
    "frame": "frames", "element": "elements", "overlay": "overlays",
    "decoration": "overlays", "panel_image": "panels",
}

REGISTRY: dict[str, LayerRenderer] = {
    "background": BackgroundRenderer(),
    "panel": PanelRenderer(),
    "frame": ImageLayerRenderer(),
    "element": ImageLayerRenderer(),
    "overlay": ImageLayerRenderer(),
    "decoration": ImageLayerRenderer(),
    "character": CharacterRenderer(),
    "weapon": WeaponRenderer(),
    "artifact": ArtifactRenderer(),
    "talent": TalentRenderer(),
    "stat": StatRenderer(),
    "text": TextRenderer(),
    "effect": EffectRenderer(),
    "footer": FooterRenderer(),
}


def register_layer(type_name: str, renderer: LayerRenderer) -> None:
    """Register a renderer for a layer ``type`` (enables drop-in custom layer types)."""
    REGISTRY[type_name] = renderer
