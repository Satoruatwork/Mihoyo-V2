"""Build recommendation business logic.

Reads build guides from a bundled JSON resource keyed by character name (with a
``_default`` fallback entry). Replace/extend the file to add real, per-character guides;
no code changes required.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from bot.utils.logging import get_logger

logger = get_logger(__name__)

_RESOURCE = Path(__file__).resolve().parent.parent / "resources" / "build_guides.json"


class BuildService:
    def __init__(self, resource_path: Path | None = None) -> None:
        self._path = resource_path or _RESOURCE
        self._cache: dict[str, Any] | None = None

    async def get_guide(self, character_name: str | None = None) -> dict[str, Any]:
        """Return a build guide for a character, or the default guide.

        Returns an empty dict only if the resource is unreadable and has no default.
        """
        data = self._read()
        if not data:
            return {}
        if character_name and character_name in data:
            return data[character_name]
        return data.get("_default", {})

    def _read(self) -> dict[str, Any]:
        """Read the bundled build-guides resource once and cache it in memory.

        Static bundled file — re-reading + re-parsing it on every ``/build_guide`` command
        was pointless blocking I/O on the event loop.
        """
        if self._cache is not None:
            return self._cache
        try:
            with self._path.open(encoding="utf-8") as fh:
                self._cache = json.load(fh)
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Failed to read build guides resource: %s", exc)
            self._cache = {}
        return self._cache
