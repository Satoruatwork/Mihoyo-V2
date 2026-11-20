"""Banner information business logic.

Reads current/upcoming banners from a bundled JSON resource (``bot/resources/banners.json``).
Swap the file for a live source later without changing callers. Never raises: an unreadable
or empty file yields an empty board that the command layer reports gracefully.
"""

from __future__ import annotations

import json
from pathlib import Path

from bot.models.banner import Banner, BannerBoard
from bot.utils.logging import get_logger

logger = get_logger(__name__)

_RESOURCE = Path(__file__).resolve().parent.parent / "resources" / "banners.json"


class BannerService:
    def __init__(self, resource_path: Path | None = None) -> None:
        self._path = resource_path or _RESOURCE
        self._cache: dict | None = None

    async def get_banners(self) -> BannerBoard:
        data = self._read()
        return BannerBoard(
            current=[self._to_banner(b) for b in data.get("current", [])],
            upcoming=[self._to_banner(b) for b in data.get("upcoming", [])],
        )

    def _read(self) -> dict:
        """Read the bundled banners resource once and cache it in memory.

        It is a static bundled file, so re-reading + re-parsing it from disk on every
        ``/banner`` command was pointless blocking I/O on the event loop.
        """
        if self._cache is not None:
            return self._cache
        try:
            with self._path.open(encoding="utf-8") as fh:
                self._cache = json.load(fh)
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Failed to read banners resource: %s", exc)
            self._cache = {}
        return self._cache

    @staticmethod
    def _to_banner(raw: dict) -> Banner:
        return Banner(
            name=str(raw.get("name", "?")),
            kind=str(raw.get("kind", "character")),
            featured=list(raw.get("featured", []) or []),
            start=raw.get("start"),
            end=raw.get("end"),
            version=raw.get("version"),
        )
