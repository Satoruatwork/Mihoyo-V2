"""Caching: an in-memory LRU for decoded images, a disk cache for downloaded bytes, and a
short-lived in-memory cache for API responses.

Three tiers, one class, each with a single clear purpose:
  * ``get_image``/``put_image`` — hot decoded ``PIL.Image`` objects, bounded LRU (memory).
  * ``get_bytes``/``put_bytes``  — downloaded blobs on disk, keyed by a hash, TTL-checked.
  * ``get_response``/``set_response`` — parsed API payloads, in-memory, TTL-checked.
"""

from __future__ import annotations

import hashlib
import time
from collections import OrderedDict
from typing import Any

from PIL import Image

from enkarender.config import Settings, default_settings
from enkarender.logging import get_logger

logger = get_logger("assets.cache")


class CacheManager:
    """Multi-tier cache. Constructed once and shared across the engine."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or default_settings
        self._settings.ensure_dirs()
        self._images: "OrderedDict[str, Image.Image]" = OrderedDict()
        self._responses: dict[str, tuple[float, Any]] = {}

    # --- tier 1: decoded images (memory, LRU) ---
    def get_image(self, key: str) -> Image.Image | None:
        img = self._images.get(key)
        if img is not None:
            self._images.move_to_end(key)  # mark most-recently-used
        return img

    def put_image(self, key: str, image: Image.Image) -> None:
        self._images[key] = image
        self._images.move_to_end(key)
        while len(self._images) > self._settings.memory_image_capacity:
            evicted, _ = self._images.popitem(last=False)
            logger.debug("Evicted image from LRU: %s", evicted)

    # --- tier 2: downloaded bytes (disk, TTL) ---
    def _disk_path(self, key: str):
        digest = hashlib.sha1(key.encode("utf-8")).hexdigest()
        return self._settings.cache_dir / f"{digest}.bin"

    def get_bytes(self, key: str) -> bytes | None:
        path = self._disk_path(key)
        if not path.exists():
            return None
        if (time.time() - path.stat().st_mtime) > self._settings.asset_ttl:
            return None  # stale; caller will refetch
        try:
            return path.read_bytes()
        except OSError as exc:
            logger.debug("Disk cache read failed for %s: %s", key, exc)
            return None

    def put_bytes(self, key: str, data: bytes) -> None:
        try:
            self._disk_path(key).write_bytes(data)
        except OSError as exc:
            logger.debug("Disk cache write failed for %s: %s", key, exc)

    # --- tier 3: API responses (memory, TTL) ---
    def get_response(self, key: str) -> Any | None:
        entry = self._responses.get(key)
        if entry is None:
            return None
        ts, value = entry
        if (time.time() - ts) > self._settings.response_ttl:
            self._responses.pop(key, None)
            return None
        return value

    def set_response(self, key: str, value: Any) -> None:
        self._responses[key] = (time.time(), value)

    def clear(self) -> None:
        self._images.clear()
        self._responses.clear()
