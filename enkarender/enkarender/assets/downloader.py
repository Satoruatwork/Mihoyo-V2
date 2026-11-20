"""Async asset downloader.

A thin coordinator over the shared HTTP transport and the disk cache: it returns the cached
bytes when present and fresh, otherwise downloads once and stores them. Failures return
``None`` (best-effort) so a missing icon never aborts a render.
"""

from __future__ import annotations

from enkarender.api.http import HttpTransport
from enkarender.assets.cache import CacheManager
from enkarender.config import Settings, default_settings
from enkarender.logging import get_logger

logger = get_logger("assets.downloader")


class Downloader:
    """Fetch-or-cache byte blobs for asset URLs."""

    def __init__(
        self,
        transport: HttpTransport | None = None,
        cache: CacheManager | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._settings = settings or default_settings
        self._http = transport or HttpTransport(self._settings)
        self._cache = cache or CacheManager(self._settings)

    async def fetch(self, url: str) -> bytes | None:
        """Return the bytes for ``url`` from disk cache, or download and cache them."""
        cached = self._cache.get_bytes(url)
        if cached is not None:
            return cached
        try:
            data = await self._http.get_bytes(url)
        except Exception as exc:  # noqa: BLE001 - best effort
            logger.debug("Download failed for %s: %s", url, exc)
            return None
        if data:
            self._cache.put_bytes(url, data)
        return data
