"""Redis-backed cache for external API responses (JSON values).

Stores cached API payloads in Redis with a TTL so they survive process restarts and are
shared across workers, while still expiring to respect upstream rate limits. All operations
degrade gracefully: on any Redis error, ``get_json`` returns ``None`` (cache miss) and
``set_json`` is a no-op, so callers simply fall back to a live fetch.
"""

from __future__ import annotations

import json
from typing import Any

from redis.asyncio import Redis
from redis.exceptions import RedisError

from bot.utils.logging import get_logger

logger = get_logger(__name__)


class RedisCache:
    """Namespaced JSON cache over Redis."""

    def __init__(self, redis: Redis, ttl: int = 300, prefix: str = "cache") -> None:
        self._r = redis
        self._ttl = ttl
        self._prefix = prefix

    def _key(self, namespace: str, key: str) -> str:
        return f"{self._prefix}:{namespace}:{key}"

    async def get_json(self, namespace: str, key: str) -> Any | None:
        try:
            raw = await self._r.get(self._key(namespace, key))
        except RedisError as exc:
            logger.debug("cache get failed (%s/%s): %s", namespace, key, exc)
            return None
        if raw is None:
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
        try:
            await self._r.set(self._key(namespace, key), payload, ex=ttl or self._ttl)
        except RedisError as exc:
            logger.debug("cache set failed (%s/%s): %s", namespace, key, exc)

    async def invalidate(self, namespace: str, key: str) -> None:
        try:
            await self._r.delete(self._key(namespace, key))
        except RedisError:
            pass
