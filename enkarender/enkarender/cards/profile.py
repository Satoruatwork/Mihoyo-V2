"""Profile card builder: a Showcase -> player profile PNG."""

from __future__ import annotations

from typing import Any

from PIL import Image

from enkarender.cards.base import CardBuilder, registry
from enkarender.enums import Element
from enkarender.models.domain import Showcase
from enkarender.render.draw import Theme, theme_for
from enkarender.utils.async_tools import gather_map


class ProfileCardBuilder(CardBuilder):
    key = "profile"
    template_key = "profile"
    max_characters = 6

    def _view_model(self, data: Showcase) -> dict[str, Any]:
        p = data.player
        return {
            "nickname": p.nickname or "Traveler",
            "uid": p.uid,
            "level": p.level,
            "world_level": p.world_level,
            "signature": p.signature,
            "achievements": p.achievements,
            "characters": [
                {"name": c.name, "level": c.level, "element": c.element.value}
                for c in data.characters[: self.max_characters]
            ],
        }

    def _theme(self, data: Showcase) -> Theme:
        # The profile header is element-neutral.
        return theme_for(Element.UNKNOWN)

    async def _load_images(self, data: Showcase) -> dict[str, Image.Image]:
        chars = list(enumerate(data.characters[: self.max_characters]))
        by_index = await gather_map(
            [i for i, _ in chars],
            lambda i: self._assets.load_icon(chars[i][1].portrait),
            limit=self.max_characters,
        )
        return {f"portrait_{i}": img for i, img in by_index.items()}


registry.register(ProfileCardBuilder)
