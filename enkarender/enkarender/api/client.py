"""The Enka API client.

Fetches a UID's public showcase payload and returns it **raw** (a ``dict``). It performs
UID validation and optional response caching, but deliberately does no schema mapping — the
domain model is built by :mod:`enkarender.models.parser`, keeping the transport layer
independent of the model layer.
"""

from __future__ import annotations

import re
from typing import Any, Protocol

from enkarender.api.http import HttpTransport
from enkarender.config import Settings, default_settings
from enkarender.exceptions import InvalidUID, ProfileNotFound
from enkarender.logging import get_logger

logger = get_logger("api.client")

# Genshin UIDs are 9 digits; server digit is the leading one.
_UID_RE = re.compile(r"^\d{9}$")


class ResponseCache(Protocol):
    """Minimal cache contract the client depends on (satisfied by CacheManager)."""

    def get_response(self, key: str) -> Any | None: ...
    def set_response(self, key: str, value: Any) -> None: ...


class EnkaClient:
    """Async client for the Enka showcase endpoint. Returns raw JSON payloads."""

    def __init__(
        self,
        transport: HttpTransport | None = None,
        cache: ResponseCache | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._settings = settings or default_settings
        self._http = transport or HttpTransport(self._settings)
        self._cache = cache

    @staticmethod
    def validate_uid(uid: str) -> str:
        uid = str(uid).strip()
        if not _UID_RE.match(uid):
            raise InvalidUID(f"{uid!r} is not a valid 9-digit UID")
        return uid

    async def fetch_showcase(self, uid: str) -> dict[str, Any]:
        """Return the raw showcase payload for ``uid`` (cached when a cache is configured)."""
        uid = self.validate_uid(uid)
        cache_key = f"showcase:{uid}"

        if self._cache is not None:
            cached = self._cache.get_response(cache_key)
            if cached is not None:
                logger.debug("Showcase cache hit for %s", uid)
                return cached

        url = self._settings.showcase_url(uid)
        payload = await self._http.get_json(url)
        if not isinstance(payload, dict) or "playerInfo" not in payload:
            raise ProfileNotFound(f"No public showcase for UID {uid}")

        if self._cache is not None:
            self._cache.set_response(cache_key, payload)
        return payload

    async def aclose(self) -> None:
        await self._http.aclose()

    async def __aenter__(self) -> "EnkaClient":
        return self

    async def __aexit__(self, *exc) -> None:
        await self.aclose()
