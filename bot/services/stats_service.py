"""Bot statistics: live counts + runtime info assembled from Redis."""

from __future__ import annotations

import time
from dataclasses import dataclass

from bot import __version__
from bot.database.redis_client import RedisClient
from bot.database.store import RedisStore


@dataclass(slots=True)
class StatsSnapshot:
    users: int
    groups: int
    private_chats: int
    interactions: int
    redis_ok: bool
    uptime_seconds: int
    version: str


class StatsService:
    """Produces a live snapshot of bot statistics."""

    def __init__(self, store: RedisStore, redis: RedisClient, started_at: float) -> None:
        self._store = store
        self._redis = redis
        self._started_at = started_at

    async def snapshot(self) -> StatsSnapshot:
        redis_ok = await self._redis.is_healthy()
        return StatsSnapshot(
            users=await self._store.count_users(),
            groups=await self._store.count_groups(),
            private_chats=await self._store.count_private_chats(),
            interactions=await self._store.count_interactions(),
            redis_ok=redis_ok,
            uptime_seconds=int(time.time() - self._started_at),
            version=__version__,
        )
