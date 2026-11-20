"""Async HTTP transport.

Owns a single pooled :class:`aiohttp.ClientSession` (created lazily inside the running
loop) reused for every request, with bounded connections, sane timeouts, and exponential
backoff on transient failures. It knows nothing about Enka's schema — it just returns JSON
or bytes and normalizes transport errors into the engine's exception hierarchy.
"""

from __future__ import annotations

import asyncio
from typing import Any

import aiohttp

from enkarender.config import Settings, default_settings
from enkarender.exceptions import NetworkError, RateLimited
from enkarender.logging import get_logger

logger = get_logger("api.http")


class HttpTransport:
    """A reusable, pooled async HTTP client."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or default_settings
        self._session: aiohttp.ClientSession | None = None
        self._lock = asyncio.Lock()

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            async with self._lock:
                if self._session is None or self._session.closed:
                    connector = aiohttp.TCPConnector(
                        limit=self._settings.connection_limit, ttl_dns_cache=300
                    )
                    self._session = aiohttp.ClientSession(
                        headers={"User-Agent": self._settings.user_agent},
                        connector=connector,
                    )
        return self._session

    async def get_json(self, url: str) -> Any:
        """GET ``url`` and decode JSON. Raises a typed :class:`ApiError` subclass on failure."""
        return await self._request(url, self._settings.request_timeout, as_json=True)

    async def get_bytes(self, url: str) -> bytes:
        """GET ``url`` and return the raw body bytes."""
        return await self._request(url, self._settings.download_timeout, as_json=False)

    async def _request(self, url: str, timeout: float, *, as_json: bool) -> Any:
        session = await self._get_session()
        client_timeout = aiohttp.ClientTimeout(total=timeout)
        last_exc: Exception | None = None

        for attempt in range(1, self._settings.max_retries + 1):
            try:
                async with session.get(url, timeout=client_timeout) as resp:
                    if resp.status == 429:
                        raise RateLimited(f"429 for {url}")
                    resp.raise_for_status()
                    return await (resp.json(content_type=None) if as_json else resp.read())
            except RateLimited:
                raise  # do not retry a rate-limit locally
            except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
                last_exc = exc
                backoff = 0.2 * (2 ** (attempt - 1))
                logger.debug("Request %s failed (attempt %d/%d): %s",
                             url, attempt, self._settings.max_retries, exc)
                if attempt < self._settings.max_retries:
                    await asyncio.sleep(backoff)

        raise NetworkError(f"GET {url} failed after {self._settings.max_retries} attempts: {last_exc}")

    async def aclose(self) -> None:
        """Close the pooled session. Safe to call multiple times."""
        if self._session is not None and not self._session.closed:
            await self._session.close()
        self._session = None

    async def __aenter__(self) -> "HttpTransport":
        return self

    async def __aexit__(self, *exc) -> None:
        await self.aclose()
