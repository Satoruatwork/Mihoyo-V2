"""In-memory JSON cache with per-key TTL.

Used as a fallback when no external cache (Redis) is configured, and as the
cache backend for Postgres/MongoDB deployments that don't want to run Redis
alongside their primary database.
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any

from bot.cache.interfaces import Cache
from bot.utils.logging import get_logger

logger = get_logger(__name__)


class MemoryCache(Cache):
    """Process-local dict cache with TTL expiry."""

    def __init__(self, ttl: int = 300, max_entries: int = 1024) -> None:
        self._ttl = ttl
        self._max = max_entries
        # key -> (expires_at_monotonic, json_string)
        self._store: dict[str, tuple[float, str]] = {}
        self._lock = asyncio.Lock()

    def _cache_key(self, namespace: str, key: str) -> str:
        return f"{namespace}:{key}"

    async def get_json(self, namespace: str, key: str) -> Any | None:
        ck = self._cache_key(namespace, key)
        async with self._lock:
            entry = self._store.get(ck)
            if entry is None:
                return None
            expires_at, raw = entry
            if time.monotonic() > expires_at:
                self._store.pop(ck, None)
                return None
        try:
            return json.loads(raw)
        except (ValueError, TypeError):
            return None

    async def set_json(self, namespace: str, key: str, value: Any, ttl: int | None = None) -> None:
        try:
            payload = json.dumps(value, ensure_ascii=False)
        except (TypeError, ValueError) as exc:
            logger.debug("cache serialize failed (%s/%s): %s", namespace, key, exc)
            return
        ck = self._cache_key(namespace, key)
        expires = time.monotonic() + (ttl if ttl is not None else self._ttl)
        async with self._lock:
            # Simple eviction: drop oldest entries if over capacity.
            if len(self._store) >= self._max and ck not in self._store:
                oldest = min(self._store.items(), key=lambda kv: kv[1][0], default=None)
                if oldest is not None:
                    self._store.pop(oldest[0], None)
            self._store[ck] = (expires, payload)

    async def invalidate(self, namespace: str, key: str) -> None:
        ck = self._cache_key(namespace, key)
        async with self._lock:
            self._store.pop(ck, None)

    async def clear(self) -> None:
        async with self._lock:
            self._store.clear()
