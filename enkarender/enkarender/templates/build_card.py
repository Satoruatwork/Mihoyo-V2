"""Character build card template (layout only).

A single character's full build: portrait + identity header, weapon panel, top stats panel,
and an artifact row. Reads a plain view-model from ``ctx.data`` and images from
``ctx.images`` (``portrait``, ``weapon_icon``, ``artifact_{i}``). No I/O.

View-model contract (``ctx.data``):
    name:str, level:int, element:str, rarity:int|None, constellation:int, friendship:int|None,
    weapon: {name, level, refinement, main_stat, sub_stat} | None,
    stats: list[{label, value}],
    artifacts: list[{slot, level, set_name, main_stat}]
"""

from __future__ import annotations

from enkarender.enums import Anchor
from enkarender.templates.base import Component, RenderContext, Template, registry
from enkarender.templates.components import (
    CircleImage,
    Divider,
    Gradient,
    Icon,
    Label,
    Panel,
    StatRow,
    TintOverlay,
)

_W, _H = 900, 1200


class BuildCardTemplate(Template):
    key = "build"
    size = (_W, _H)

    def components(self, ctx: RenderContext) -> list[Component]:
        d = ctx.data
        parts: list[Component] = [Gradient(), TintOverlay()]

        # --- identity header ---
        parts.append(CircleImage((48, 48), 220, "portrait"))
        parts.append(Label((300, 70), d.get("name", "?"), size=64, weight=700, shadow=True,
                           max_width=_W - 340))
        stars = "★" * int(d.get("rarity") or 0)
        parts.append(Label((300, 150), stars, size=32, color=ctx.theme.accent))
        parts.append(Label((300, 196), f"Lv. {d.get('level', 1)}", size=30, weight=600))
        parts.append(Label((470, 196), f"C{d.get('constellation', 0)}", size=30,
                           color=ctx.theme.accent))
        parts.append(Label((300, 236), d.get("element", ""), size=26, muted=True))
        fr = d.get("friendship")
        if fr is not None:
            parts.append(Label((470, 236), f"♥ {fr}", size=26, anchor=Anchor.LEFT, muted=True))

        parts.append(Divider((48, 300), _W - 96))

        # --- weapon panel ---
        weapon = d.get("weapon")
        parts.append(Panel((48, 328, _W - 48, 470)))
        parts.append(Icon((72, 352, 192, 452), "weapon_icon", fallback="weapon"))
        if weapon:
            parts.append(Label((220, 352), weapon.get("name", "?"), size=36, weight=600,
                               max_width=_W - 280))
            parts.append(Label((220, 402), f"Lv.{weapon.get('level', 1)}  "
                                           f"R{weapon.get('refinement', 1)}", size=26, muted=True))
            main = weapon.get("main_stat")
            sub = weapon.get("sub_stat")
            if main:
                parts.append(Label((_W - 72, 402), main, size=26, anchor=Anchor.RIGHT))
            if sub:
                parts.append(Label((_W - 72, 432), sub, size=22, anchor=Anchor.RIGHT, muted=True))
        else:
            parts.append(Label((220, 392), "No weapon", size=28, muted=True))

        # --- stats panel ---
        parts.append(Panel((48, 494, _W - 48, 760)))
        parts.append(Label((72, 510), "Stats", size=26, weight=600, color=ctx.theme.accent))
        stats = d.get("stats", [])[:7]
        for i, st in enumerate(stats):
            y = 552 + i * 28
            parts.append(StatRow((72, y), st.get("label", "?"), st.get("value", "--"),
                                 _W - 144, size=24))

        # --- artifacts row ---
        parts.append(Label((72, 792), "Artifacts", size=26, weight=600, color=ctx.theme.accent))
        arts = d.get("artifacts", [])[:5]
        slot_w = (_W - 96) // 5
        for i, art in enumerate(arts):
            x0 = 48 + i * slot_w
            parts.append(Panel((x0 + 6, 832, x0 + slot_w - 6, 1160), radius=14))
            parts.append(Icon((x0 + 22, 852, x0 + slot_w - 22, 952), f"artifact_{i}",
                              fallback=art.get("slot", "")))
            parts.append(Label((x0 + slot_w // 2, 964), art.get("slot", "?"), size=18,
                               anchor=Anchor.CENTER, muted=True))
            parts.append(Label((x0 + slot_w // 2, 992), f"+{art.get('level', 0)}", size=20,
                               anchor=Anchor.CENTER))
            main = art.get("main_stat")
            if main:
                parts.append(Label((x0 + slot_w // 2, 1024), main, size=18,
                                   anchor=Anchor.CENTER, color=ctx.theme.accent,
                                   max_width=slot_w - 20))
            set_name = art.get("set_name")
            if set_name:
                parts.append(Label((x0 + slot_w // 2, 1060), set_name, size=15,
                                   anchor=Anchor.CENTER, muted=True, max_width=slot_w - 16))
        return parts


registry.register(BuildCardTemplate())
