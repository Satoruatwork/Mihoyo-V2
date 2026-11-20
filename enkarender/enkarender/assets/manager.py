"""High-level asset resolution.

Owns the two "logical" concerns that sit above raw bytes:
  * localization — resolve ``nameTextMapHash`` / ``avatarId`` via optional JSON maps
    (``text_map.json``, ``characters.json``) downloaded once into the asset dir;
  * image resolution — turn an icon *key* (Enka filename) or a full URL into a loaded,
    cached ``PIL.Image`` by delegating to the :class:`ResourceLoader`.

Maps are optional: when absent the resolvers return ``None`` and callers fall back to ids —
so the engine runs fully offline with placeholders, and gains real names/art once the maps
are provided. This mirrors the reference library's "assets are external + updatable" design.
"""

from __future__ import annotations

import json
from typing import Any

from PIL import Image

from enkarender.assets.cache import CacheManager
from enkarender.assets.downloader import Downloader
from enkarender.assets.loader import ResourceLoader
from enkarender.config import Settings, default_settings
from enkarender.logging import get_logger

logger = get_logger("assets.manager")

_ICON_CDN = "https://enka.network/ui/{key}.png"


class AssetManager:
    """Localization + image resolution over the resource loader."""

    def __init__(
        self,
        loader: ResourceLoader | None = None,
        cache: CacheManager | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._settings = settings or default_settings
        self._cache = cache or CacheManager(self._settings)
        self._loader = loader or ResourceLoader(Downloader(cache=self._cache, settings=self._settings), self._cache)
        self._text_map: dict[str, str] = {}
        self._character_map: dict[str, dict[str, Any]] = {}
        self._load_maps()

    # --- localization ---
    def _load_maps(self) -> None:
        self._text_map = self._read_json("text_map.json")
        self._character_map = self._read_json("characters.json")
        if self._text_map or self._character_map:
            logger.info(
                "Loaded asset maps: %d names, %d characters",
                len(self._text_map), len(self._character_map),
            )

    def _read_json(self, name: str) -> dict:
        path = self._settings.asset_dir / name
        if not path.exists():
            return {}
        try:
            with path.open(encoding="utf-8") as fh:
                data = json.load(fh)
            return data if isinstance(data, dict) else {}
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Could not read asset map %s: %s", name, exc)
            return {}

    def resolve_name(self, hash_id: Any) -> str | None:
        return self._text_map.get(str(hash_id)) if hash_id is not None else None

    def resolve_character(self, avatar_id: str) -> dict[str, Any] | None:
        return self._character_map.get(str(avatar_id))

    # --- image resolution ---
    @staticmethod
    def icon_url(key_or_url: str | None) -> str | None:
        if not key_or_url:
            return None
        if key_or_url.startswith(("http://", "https://")):
            return key_or_url
        return _ICON_CDN.format(key=key_or_url)

    async def load_icon(self, key_or_url: str | None) -> Image.Image | None:
        """Load a (cached) icon image from an Enka key or a full URL."""
        return await self._loader.load_image(self.icon_url(key_or_url))

    def placeholder(self, size: tuple[int, int], label: str = "") -> Image.Image:
        return self._loader.placeholder(size, label)
