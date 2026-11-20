"""Asset layer: caching, downloading, resource loading, and high-level asset resolution.

Layering within this package:
    CacheManager  — memory LRU (decoded images) + disk (downloaded bytes) + response TTL
    Downloader    — async byte fetches over the shared HTTP transport
    ResourceLoader— bytes -> decoded PIL images/fonts, backed by the cache + downloader
    AssetManager  — logical resolution: name-hash localization, character metadata, and
                    turning icon keys/URLs into loaded images (delegates to ResourceLoader)
"""

from __future__ import annotations

from enkarender.assets.cache import CacheManager
from enkarender.assets.downloader import Downloader
from enkarender.assets.loader import ResourceLoader
from enkarender.assets.manager import AssetManager

__all__ = ["CacheManager", "Downloader", "ResourceLoader", "AssetManager"]
