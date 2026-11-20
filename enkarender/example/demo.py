"""Offline end-to-end demo.

Runs the full pipeline WITHOUT any network: it loads a bundled Enka-shaped fixture, parses
it into the domain model (injecting a tiny name resolver to show the localization hook),
and renders both a profile card and a build card to PNG files. Icons resolve to placeholders
since no asset URLs are provided — with real URLs/maps they would download + cache.

    python -m example.demo            # writes profile.png and build.png here

The point is to demonstrate the layered flow: parse -> build (assets/fonts) -> template ->
engine -> bytes, all decoupled.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from enkarender.assets.manager import AssetManager
from enkarender.cards.base import registry as card_registry
from enkarender.fonts.manager import FontManager
from enkarender.models.parser import parse_showcase

# Import side-effect: register the bundled templates + card builders.
import enkarender.templates  # noqa: F401
import enkarender.cards  # noqa: F401

HERE = Path(__file__).resolve().parent

# A minimal name map standing in for Enka's text map (normally injected by AssetManager).
_NAMES = {"W1": "Amos' Bow", "W2": "Freedom-Sworn", "S1": "Blizzard Strayer"}


async def main() -> None:
    raw = json.loads((HERE / "fixture.json").read_text(encoding="utf-8"))
    showcase = parse_showcase(raw, resolve_name=lambda h: _NAMES.get(str(h)))
    print(f"Parsed {showcase.player.nickname} (UID {showcase.player.uid}) "
          f"with {len(showcase.characters)} characters")

    # Offline: no asset maps, no URLs -> icons become placeholders (instant, no network).
    assets = AssetManager()
    fonts = FontManager()

    profile_builder = card_registry.create("profile", assets, fonts)
    (HERE / "profile.png").write_bytes(await profile_builder.build(showcase))
    print("Wrote profile.png")

    build_builder = card_registry.create("build", assets, fonts)
    (HERE / "build.png").write_bytes(await build_builder.build(showcase.characters[0]))
    print("Wrote build.png")

    print("Registered templates:", card_registry.keys())


if __name__ == "__main__":
    asyncio.run(main())
