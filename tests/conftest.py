"""Shared pytest fixtures.

Uses an in-memory fake Redis (``fakeredis``) so store/cache tests are fast and isolated.
No network access is performed anywhere in the test suite.
"""

from __future__ import annotations

import fakeredis.aioredis
import pytest_asyncio

from bot.cache.redis_cache import RedisCache
from bot.database.store import RedisStore


@pytest_asyncio.fixture
async def redis_client():
    """A fresh in-memory fake Redis client per test."""
    client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    yield client
    await client.flushall()
    await client.aclose()


@pytest_asyncio.fixture
async def store(redis_client):
    return RedisStore(redis_client)


@pytest_asyncio.fixture
async def cache(redis_client):
    return RedisCache(redis_client, ttl=60)
