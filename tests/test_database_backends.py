"""Cross-backend store tests — the same suite runs against every UserStore.

These are the pluggable-backend contract tests: if a new backend passes them,
it can be swapped in via DATABASE_BACKEND with no service changes.
"""

from __future__ import annotations

import pytest

# -- Reuse the Redis fake for the 'memory' (LocalStore) test below -----------


# ---------- helper: drive the same assertions against any UserStore ---------

async def _exercise_basic_crud(store):
    # get_or_create registers a user
    await store.get_or_create(1, "en")
    assert await store.count_users() == 1
    # Idempotent
    await store.get_or_create(1, "en")
    assert await store.count_users() == 1

    # link + get uid
    await store.link_uid(7, "901211014")
    assert await store.get_uid(7) == "901211014"
    await store.link_uid(7, "600000000")
    assert await store.get_uid(7) == "600000000"

    # unlink
    assert await store.unlink_uid(7) is True
    assert await store.get_uid(7) is None
    assert await store.unlink_uid(7) is False

    # language
    assert await store.get_language(5, "en") == "en"
    await store.set_language(5, "ja")
    assert await store.get_language(5, "en") == "ja"

    # settings
    await store.set_setting(9, "show_ranks", "true")
    assert await store.get_setting(9, "show_ranks") == "true"
    await store.set_setting(9, "show_ranks", "false")
    assert await store.get_setting(9, "show_ranks") == "false"
    assert await store.get_setting(9, "missing", "default") == "default"
    assert await store.get_all_settings(9) == {"show_ranks": "false"}

    # hoyolab cookie
    await store.set_hoyolab_cookie(3, "ENC")
    assert await store.get_hoyolab_cookie(3) == "ENC"
    assert await store.clear_hoyolab_cookie(3) is True
    assert await store.get_hoyolab_cookie(3) is None
    assert await store.clear_hoyolab_cookie(3) is False


async def _exercise_stats_and_groups(store):
    # groups
    await store.register_group(-100123)
    await store.register_group(-100123)
    assert await store.count_groups() == 1
    assert -100123 in await store.all_groups()
    await store.unregister_group(-100123)
    assert await store.count_groups() == 0

    # interactions / private
    await store.register_interaction(100, "private")
    await store.register_interaction(100, "private")
    await store.register_interaction(200, "group")
    assert await store.count_users() >= 2
    assert await store.count_private_chats() >= 1

    # broadcast enumeration
    users = await store.all_users()
    assert 100 in users and 200 in users
    # discard
    await store.discard_users([100])
    users_after = await store.all_users()
    assert 100 not in users_after
    await store.register_group(-999)
    await store.discard_groups([-999])
    assert -999 not in await store.all_groups()


# ---------- per-backend tests ---------------------------------------------

@pytest.mark.asyncio
async def test_redis_store_contract(store):
    await _exercise_basic_crud(store)
    await _exercise_stats_and_groups(store)


@pytest.mark.asyncio
async def test_mongo_store_contract(mongo_store):
    await _exercise_basic_crud(mongo_store)
    await _exercise_stats_and_groups(mongo_store)


@pytest.mark.asyncio
async def test_memory_store_contract(memory_store):
    await _exercise_basic_crud(memory_store)
    await _exercise_stats_and_groups(memory_store)


# ---------- factory tests -------------------------------------------------

def test_factory_builds_memory_backend(tmp_path):
    from bot.config import Settings
    from bot.database.factory import build_database, describe_backend

    s = Settings(_env_file=None, bot_token="t", database_backend="memory", local_store_path=str(tmp_path / "l.json"))
    store, client, cache = build_database(s)
    assert store is not None and client is not None and cache is not None
    assert "Memory" in describe_backend(s)


def test_factory_builds_redis(tmp_path):
    from bot.config import Settings
    from bot.database.factory import build_database

    # No actual server needed — RedisClient is lazy; building doesn't connect.
    s = Settings(_env_file=None, bot_token="t", database_backend="redis", redis_url="redis://localhost:6379", local_store_path=str(tmp_path / "l.json"))
    store, client, cache = build_database(s)
    from bot.database.store import RedisStore

    assert isinstance(store, RedisStore)


def test_factory_builds_mongo(tmp_path):
    from bot.config import Settings
    from bot.database.factory import build_database

    s = Settings(_env_file=None, bot_token="t", database_backend="mongodb", mongodb_url="mongodb://localhost:27017", mongodb_db="test", local_store_path=str(tmp_path / "l.json"))
    store, client, cache = build_database(s)
    from bot.database.mongo_store import MongoStore

    assert isinstance(store, MongoStore)


def test_factory_builds_postgres(tmp_path):
    from bot.config import Settings
    from bot.database.factory import build_database

    s = Settings(_env_file=None, bot_token="t", database_backend="postgres", postgres_url="postgresql://user:pass@localhost/db", local_store_path=str(tmp_path / "l.json"))
    store, client, cache = build_database(s)
    from bot.database.postgres_store import PostgresStore

    assert isinstance(store, PostgresStore)


def test_factory_supabase_alias(tmp_path):
    from bot.config import Settings

    # SUPABASE_URL is an alias for POSTGRES_URL — should resolve to postgres.
    s = Settings(_env_file=None, bot_token="t", supabase_url="postgresql://user:pass@localhost/db", local_store_path=str(tmp_path / "l.json"))
    assert s.resolved_backend == "postgres"
    assert s.postgres_url == "postgresql://user:pass@localhost/db"


def test_factory_unknown_backend_raises(tmp_path):
    from bot.config import Settings
    from bot.database.factory import build_database

    s = Settings(_env_file=None, bot_token="t", database_backend="dynamodb", local_store_path=str(tmp_path / "l.json"))
    try:
        build_database(s)
        assert False, "should have raised"
    except ValueError as exc:
        assert "Unknown DATABASE_BACKEND" in str(exc)


# ---------- cache contract tests -----------------------------------------

async def _exercise_cache(cache):
    assert await cache.get_json("ns", "missing") is None
    await cache.set_json("ns", "k", {"a": 1})
    assert await cache.get_json("ns", "k") == {"a": 1}
    await cache.invalidate("ns", "k")
    assert await cache.get_json("ns", "k") is None
    # TTL override: zero TTL should expire immediately on next read if checked by time?
    # Memory cache uses monotonic expiry; we just test set/get works.
    await cache.set_json("ns", "x", [1, 2, 3], ttl=600)
    assert await cache.get_json("ns", "x") == [1, 2, 3]


@pytest.mark.asyncio
async def test_redis_cache_contract(cache):
    await _exercise_cache(cache)


@pytest.mark.asyncio
async def test_mongo_cache_contract(mongo_cache):
    await _exercise_cache(mongo_cache)


@pytest.mark.asyncio
async def test_memory_cache_contract(memory_cache):
    await _exercise_cache(memory_cache)


# ---------- config inference tests ---------------------------------------

def test_config_infers_redis_from_url(tmp_path):
    from bot.config import Settings

    s = Settings(_env_file=None, redis_url="redis://localhost:6379", local_store_path=str(tmp_path / "l.json"))
    assert s.resolved_backend == "redis"


def test_config_infers_postgres_from_database_url(tmp_path):
    from bot.config import Settings

    s = Settings(_env_file=None, database_url="postgresql://u:p@h/db", local_store_path=str(tmp_path / "l.json"))
    assert s.resolved_backend == "postgres"


def test_config_explicit_backend_wins(tmp_path):
    from bot.config import Settings

    s = Settings(
        _env_file=None,
        database_backend="mongodb",
        mongodb_url="mongodb://localhost:27017",
        redis_url="redis://localhost:6379",
        local_store_path=str(tmp_path / "l.json"),
    )
    assert s.resolved_backend == "mongodb"
