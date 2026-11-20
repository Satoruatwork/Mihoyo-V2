"""Build card builder: a single Character -> full build PNG."""

from __future__ import annotations

import asyncio
from typing import Any

from PIL import Image

from enkarender.cards.base import CardBuilder, registry
from enkarender.models.domain import Character, Stat
from enkarender.render.draw import Theme, theme_for


class BuildCardBuilder(CardBuilder):
    key = "build"
    template_key = "build"
    max_artifacts = 5

    def _view_model(self, data: Character) -> dict[str, Any]:
        return {
            "name": data.name,
            "level": data.level,
            "element": data.element.value,
            "rarity": data.rarity,
            "constellation": data.constellation,
            "friendship": data.friendship,
            "weapon": self._weapon_vm(data),
            "stats": [{"label": s.name, "value": s.formatted()} for s in data.stats[:7]],
            "artifacts": [
                {
                    "slot": a.slot,
                    "level": a.level,
                    "set_name": a.set_name,
                    "main_stat": self._stat_text(a.main_stat),
                }
                for a in data.artifacts[: self.max_artifacts]
            ],
        }

    @staticmethod
    def _weapon_vm(data: Character) -> dict[str, Any] | None:
        w = data.weapon
        if w is None:
            return None
        return {
            "name": w.name,
            "level": w.level,
            "refinement": w.refinement,
            "main_stat": BuildCardBuilder._stat_text(w.main_stat),
            "sub_stat": BuildCardBuilder._stat_text(w.sub_stat),
        }

    @staticmethod
    def _stat_text(stat: Stat | None) -> str | None:
        return f"{stat.name} {stat.formatted()}" if stat else None

    def _theme(self, data: Character) -> Theme:
        return theme_for(data.element)

    async def _load_images(self, data: Character) -> dict[str, Image.Image]:
        # Portrait, weapon icon, and each artifact icon — all resolved concurrently.
        jobs: dict[str, Any] = {"portrait": data.portrait}
        if data.weapon and data.weapon.icon:
            jobs["weapon_icon"] = data.weapon.icon
        for i, art in enumerate(data.artifacts[: self.max_artifacts]):
            if art.icon:
                jobs[f"artifact_{i}"] = art.icon

        keys = list(jobs)
        results = await asyncio.gather(
            *(self._assets.load_icon(jobs[k]) for k in keys), return_exceptions=True
        )
        images: dict[str, Image.Image] = {}
        for key, res in zip(keys, results):
            if isinstance(res, Image.Image):
                images[key] = res
        return images


registry.register(BuildCardBuilder)
