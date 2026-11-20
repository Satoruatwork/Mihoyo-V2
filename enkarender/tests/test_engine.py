"""RenderEngine + template registry: a custom template renders without touching engine code."""

from __future__ import annotations

import io

from PIL import Image

from enkarender.config import Settings
from enkarender.enums import Anchor
from enkarender.fonts.manager import FontManager
from enkarender.render.draw import Theme
from enkarender.render.engine import RenderEngine
from enkarender.templates.base import Component, RenderContext, Template, TemplateRegistry
from enkarender.templates.components import Label, Panel


class _TinyTemplate(Template):
    key = "tiny"
    size = (200, 100)

    def components(self, ctx: RenderContext) -> list[Component]:
        return [Panel((5, 5, 195, 95)), Label((100, 40), ctx.get("msg", ""), anchor=Anchor.CENTER)]


def test_engine_renders_registered_template(tmp_path):
    fonts = FontManager(Settings(home=tmp_path))
    reg = TemplateRegistry()
    reg.register(_TinyTemplate())
    engine = RenderEngine()

    ctx = RenderContext(data={"msg": "hi"}, fonts=fonts, theme=Theme())
    png = engine.render(reg.get("tiny"), ctx)

    img = Image.open(io.BytesIO(png))
    assert img.size == (200, 100)
    assert img.format == "PNG"


def test_bundled_templates_are_registered():
    from enkarender.templates.base import registry

    assert {"profile", "build"}.issubset(set(registry.keys()))
