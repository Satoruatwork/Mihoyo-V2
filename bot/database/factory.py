"""Factory — build the configured database backend and cache from ``Settings``.

This is the only place that knows about concrete backends. All other modules
depend on the ``UserStore``/``Cache``/``DatabaseClient`` interfaces.

Usage::

    store, client, cache = build_database(settings)

``store``  — the ``UserStore`` (RedisStore / MongoStore / PostgresStore / LocalStore)
``client`` — the ``DatabaseClient`` for health checks (same object for LocalStore, or
             the dedicated client for Redis/Mongo/Postgres so /stats can probe it)
``cache``  — the ``Cache`` (RedisCache / MemoryCache / PostgresCache / MongoCache)
"""

from __future__ import annotations

from bot.cache.memory_cache import MemoryCache
from bot.config import Settings
from bot.database.interfaces import DatabaseClient, UserStore
from bot.database.local_store import LocalStore
from bot.cache.interfaces import Cache
from bot.utils.logging import get_logger

logger = get_logger(__name__)

SUPPORTED_BACKENDS = ("redis", "mongodb", "postgres", "memory")


def _resolve_backend(settings: Settings) -> str:
    return settings.resolved_backend


def build_database(settings: Settings) -> tuple[UserStore, DatabaseClient, Cache]:
    """Build (store, client, cache) for the configured backend.

    Falls back to a purely local/memory combination when no remote URL is
    configured — useful for local dev and CI without credentials.
    """
    backend = _resolve_backend(settings)
    fallback = LocalStore(settings.local_store_file)

    if backend == "redis":
        return _build_redis(settings, fallback)
    if backend == "mongodb":
        return _build_mongodb(settings, fallback)
    if backend == "postgres":
        return _build_postgres(settings, fallback)
    if backend == "memory":
        # No remote DB — everything lives in the local file + in-memory cache.
        logger.info("Database backend 'memory' selected — using local file + memory cache")
        cache = MemoryCache(ttl=settings.enka_cache_ttl)
        return fallback, fallback, cache

    # Unknown backend — raise a clear error (surfaced at startup as a log line).
    raise ValueError(
        f"Unknown DATABASE_BACKEND {backend!r}. Supported: {', '.join(SUPPORTED_BACKENDS)}. "
        f"Did you mean 'redis', 'mongodb', or 'postgres' (also works for Supabase/Neon)?"
    )


def describe_backend(settings: Settings) -> str:
    """Human-readable one-liner for the startup logs (no secrets)."""
    backend = _resolve_backend(settings)
    if backend == "redis":
        from bot.database.redis_client import mask_url

        return f"Redis ({mask_url(settings.redis_url)})"
    if backend == "mongodb":
        from bot.database.mongo_store import mask_mongo_url

        return f"MongoDB ({mask_mongo_url(settings.mongodb_url)}, db={settings.mongodb_db})"
    if backend == "postgres":
        from bot.database.postgres_store import mask_postgres_url

        return f"Postgres ({mask_postgres_url(settings.postgres_url)})"
    if backend == "memory":
        return "Memory (local file, no remote DB)"
    return f"Unknown ({backend})"


def validate_backend_config(settings: Settings) -> tuple[bool, str]:
    """Validate that the required URL for the selected backend is present and well-formed."""
    backend = _resolve_backend(settings)
    if backend == "memory":
        return True, "ok"
    if backend == "redis":
        from bot.database.redis_client import validate_redis_url

        return validate_redis_url(settings.redis_url)
    if backend == "mongodb":
        from bot.database.mongo_store import validate_mongo_url

        return validate_mongo_url(settings.mongodb_url)
    if backend == "postgres":
        from bot.database.postgres_store import validate_postgres_url

        return validate_postgres_url(settings.postgres_url)
    return False, f"Unknown DATABASE_BACKEND {backend!r}. Supported: {', '.join(SUPPORTED_BACKENDS)}."


# -- per-backend builders -------------------------------------------------


def _build_redis(settings: Settings, fallback: LocalStore) -> tuple[UserStore, DatabaseClient, Cache]:
    from bot.cache.redis_cache import RedisCache
    from bot.database.redis_client import RedisClient
    from bot.database.store import RedisStore

    client = RedisClient(
        settings.redis_url,
        connect_timeout=settings.redis_connect_timeout,
        socket_timeout=settings.redis_socket_timeout,
        retries=settings.redis_retries,
    )
    store = RedisStore(client.client, fallback=fallback, breaker_cooldown=settings.redis_breaker_cooldown)
    cache = RedisCache(client.client, ttl=settings.enka_cache_ttl, prefix="cache")
    return store, client, cache


def _build_mongodb(settings: Settings, fallback: LocalStore) -> tuple[UserStore, DatabaseClient, Cache]:
    from bot.cache.mongo_cache import MongoCache
    from bot.database.mongo_store import MongoClient, MongoStore

    client = MongoClient(settings.mongodb_url, db_name=settings.mongodb_db)
    store = MongoStore(client.db, fallback=fallback, breaker_cooldown=settings.redis_breaker_cooldown)
    cache = MongoCache(client.db, ttl=settings.enka_cache_ttl)
    return store, client, cache


def _build_postgres(settings: Settings, fallback: LocalStore) -> tuple[UserStore, DatabaseClient, Cache]:
    from bot.cache.postgres_cache import PostgresCache
    from bot.database.postgres_store import PostgresClient, PostgresStore

    client = PostgresClient(settings.postgres_url)
    store = PostgresStore(client, fallback=fallback, breaker_cooldown=settings.redis_breaker_cooldown)
    cache = PostgresCache(client, ttl=settings.enka_cache_ttl)
    return store, client, cache
