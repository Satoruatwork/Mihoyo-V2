"""Player profile card template (layout only).

Renders a header (nickname, UID, AR/WL, signature) plus a row of showcased-character
medallions. Reads a plain view-model from ``ctx.data`` (prepared by the card builder) and
character portraits from ``ctx.images``; performs no I/O.

View-model contract (``ctx.data``):
    nickname:str, uid:str, level:int, world_level:int, signature:str, achievements:int|None,
    characters: list[{name:str, level:int, element:str}]  (portrait images under
                image keys ``portrait_{i}``)
"""

from __future__ import annotations

from enkarender.enums import Anchor
from enkarender.templates.base import Component, RenderContext, Template, registry
from enkarender.templates.components import (
    CircleImage,
    Divider,
    Gradient,
    Label,
    Panel,
    TintOverlay,
)

_W, _H = 960, 540


class ProfileCardTemplate(Template):
    key = "profile"
    size = (_W, _H)

    def components(self, ctx: RenderContext) -> list[Component]:
        d = ctx.data
        parts: list[Component] = [Gradient(), TintOverlay()]

        # Header panel.
        parts.append(Panel((32, 28, _W - 32, 210), radius=20))
        parts.append(Label((60, 52), d.get("nickname", "Traveler"), size=48, weight=700,
                            max_width=_W - 360))
        parts.append(Label((60, 116), f"UID {d.get('uid', '')}", size=24, muted=True))
        parts.append(Label((_W - 60, 52), f"AR {d.get('level', 0)}", size=30, weight=600,
                            anchor=Anchor.RIGHT))
        parts.append(Label((_W - 60, 92), f"WL {d.get('world_level', 0)}", size=24,
                           anchor=Anchor.RIGHT, muted=True))
        ach = d.get("achievements")
        if ach is not None:
            parts.append(Label((_W - 60, 126), f"Achievements {ach}", size=20,
                               anchor=Anchor.RIGHT, muted=True))
        sig = d.get("signature") or ""
        if sig:
            parts.append(Label((60, 156), sig, size=22, muted=True, max_width=_W - 120))

        parts.append(Divider((60, 232), _W - 120))

        # Character medallions.
        chars = d.get("characters", [])[:6]
        slot_w = (_W - 120) // 6
        for i, ch in enumerate(chars):
            cx = 60 + i * slot_w + slot_w // 2
            diameter = 120
            parts.append(CircleImage((cx - diameter // 2, 270), diameter, f"portrait_{i}"))
            parts.append(Label((cx, 402), ch.get("name", "?"), size=22, anchor=Anchor.CENTER,
                               max_width=slot_w - 8))
            parts.append(Label((cx, 432), f"Lv.{ch.get('level', 1)}", size=18,
                               anchor=Anchor.CENTER, muted=True))
            parts.append(Label((cx, 458), ch.get("element", ""), size=18,
                               anchor=Anchor.CENTER,
                               color=ctx.theme.accent))
        return parts


registry.register(ProfileCardTemplate())
