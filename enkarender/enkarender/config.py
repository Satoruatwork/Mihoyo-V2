"""Central configuration for the enkarender engine.

A single immutable :class:`Settings` object holds every tunable: API endpoints, cache
locations/TTLs, network timeouts, and the concurrency cap for asset fetches. Nothing else
in the package hardcodes a URL, path, or timeout — they all read from here, so the whole
system can be reconfigured in one place (and overridden per-instance in tests).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

# Root used for the default on-disk cache. Overridable via ENKARENDER_HOME.
_DEFAULT_HOME = Path(os.environ.get("ENKARENDER_HOME", Path.home() / ".enkarender"))


@dataclass(frozen=True, slots=True)
class Settings:
    """Immutable engine configuration. Construct once and pass down explicitly."""

    # --- Enka API ---
    api_base: str = "https://enka.network"
    showcase_path: str = "/api/uid/{uid}"
    user_agent: str = "enkarender/1.0 (+https://enka.network)"

    # --- Networking ---
    request_timeout: float = 15.0
    download_timeout: float = 30.0
    max_retries: int = 3
    connection_limit: int = 32  # pooled connections shared across downloads

    # --- Concurrency ---
    max_concurrent_downloads: int = 16

    # --- Cache ---
    home: Path = _DEFAULT_HOME
    memory_image_capacity: int = 128  # decoded images kept in the in-memory LRU
    response_ttl: float = 300.0       # seconds an API response stays fresh
    asset_ttl: float = 7 * 24 * 3600  # seconds a downloaded asset stays fresh

    # --- Rendering ---
    default_card_scale: float = 1.0

    @property
    def cache_dir(self) -> Path:
        return self.home / "cache"

    @property
    def asset_dir(self) -> Path:
        return self.home / "assets"

    @property
    def font_dir(self) -> Path:
        return self.home / "fonts"

    def showcase_url(self, uid: str) -> str:
        return self.api_base + self.showcase_path.format(uid=uid)

    def ensure_dirs(self) -> None:
        """Create the cache/asset/font directories if they do not exist."""
        for d in (self.cache_dir, self.asset_dir, self.font_dir):
            d.mkdir(parents=True, exist_ok=True)


# A module-level default; callers may build their own Settings and inject it.
default_settings: Settings = Settings()
