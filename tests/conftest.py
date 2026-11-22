"""Shared pytest fixtures.

Uses in-memory fakes (``fakeredis``, ``mongomock-motor``) so store/cache tests
are fast and isolated. No network access is performed anywhere in the test suite.
"""

from __future__ import annotations

import fakeredis.aioredis
import pytest_asyncio

from bot.cache.memory_cache import MemoryCache
from bot.cache.redis_cache import RedisCache
from bot.database.local_store import LocalStore
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


@pytest_asyncio.fixture
async def memory_store(tmp_path):
    """A LocalStore backed by a temp file (used as the 'memory' backend fixture)."""
    return LocalStore(tmp_path / "local.json")


@pytest_asyncio.fixture
async def memory_cache():
    return MemoryCache(ttl=60)


# -- MongoDB (mongomock-motor) -------------------------------------------

@pytest_asyncio.fixture
async def mongo_db():
    """A fresh in-memory MongoDB database (mongomock-motor)."""
    try:
        import mongomock_motor
    except ImportError:
        import pytest

        pytest.skip("mongomock-motor not installed")
    # mongomock-motor needs an AsyncIOMockClient with a real asyncio loop.
    # It exposes the same API as motor but runs in-memory.
    client = mongomock_motor.AsyncMongoMockClient()
    db = client["test_mihoyo"]
    yield db
    # Clean up collections between tests
    for coll_name in await db.list_collection_names():
        await db[coll_name].delete_many({})


@pytest_asyncio.fixture
async def mongo_store(mongo_db):
    from bot.database.mongo_store import MongoStore

    return MongoStore(mongo_db)


@pytest_asyncio.fixture
async def mongo_cache(mongo_db):
    from bot.cache.mongo_cache import MongoCache

    return MongoCache(mongo_db, ttl=60)
