"""Render the validation cards through the production path, with real assets.

Wipes tests/output first: stale PNGs with plausible names are worse than none, because
they get mistaken for current output. Every file this writes is from the current code.

    python scripts/render_cards.py
"""
from __future__ import annotations

import asyncio
import io
import logging
import pathlib
import sys
from types import SimpleNamespace

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from PIL import Image

import enka
from bot.api.enka_client import EnkaClient
from bot.commands import characters
from bot.models.player import PlayerInfo
from bot.services.artwork_service import ArtworkService
from tests.enka_payloads import ARLECCHINO, ODETTE, showcase_payload

logging.basicConfig(level=logging.ERROR)

OUT = pathlib.Path(__file__).resolve().parent.parent / "tests" / "output"
CHARACTERS = {
    "lauma": (10000119, (11191, 11192, 11195)),
    "arlecchino": ARLECCHINO,
    "mavuika": (10000106, (11061, 11062, 11065)),
    "nahida": (10000073, (10731, 10732, 10735)),
    "odette": ODETTE,
}


class _Tracking(ArtworkService):
    def __init__(self) -> None:
        super().__init__()
        self.ok: list[str] = []
        self.missing: list[str] = []

    async def get_portrait(self, character):
        img = await super().get_portrait(character)
        (self.ok if img is not None else self.missing).append(character.art or "?")
        return img

    async def get_images(self, urls):
        urls = [u for u in urls if u]
        out = await super().get_images(urls)
        for u in urls:
            (self.ok if u in out else self.missing).append(u)
        return out


async def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    for stale in OUT.glob("*.png"):
        stale.unlink()

    failures = 0
    for name, spec in CHARACTERS.items():
        payload = showcase_payload(*spec)

        async def _fetch(self, uid, language, _p=payload):
            client = enka.GenshinClient(self._resolve_language(enka, language))
            await client.start()
            try:
                return client.parse_showcase(_p)
            finally:
                await client.close()

        EnkaClient._fetch_raw = _fetch
        character = (await EnkaClient().fetch_showcase("901211014")).characters[0]

        art = _Tracking()
        png = await characters._render_card_png(
            SimpleNamespace(artwork_service=art, renderer=None),
            character, PlayerInfo(uid="901211014", nickname="Rexxyyy"), "en",
        )
        path = OUT / f"card_{name}.png"
        path.write_bytes(png)
        img = Image.open(io.BytesIO(png))
        ok = img.size == (1536, 864) and img.format == "PNG"
        failures += 0 if ok else 1
        print(f"{name:12s} {character.name:12s} {img.size} assets {len(art.ok)} ok / "
              f"{len(art.missing)} missing {'OK' if ok else 'BAD SIZE'}")
        for u in art.missing:
            print(f"    MISSING: {u}")
        await art.aclose()
    return failures


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
