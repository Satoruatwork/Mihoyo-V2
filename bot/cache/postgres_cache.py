"""Postgres-backed JSON cache (works with any Postgres, including Supabase/Neon)."""

from __future__ import annotations

import json
import time
from typing import Any

from bot.utils.logging import get_logger

logger = get_logger(__name__)

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS cache_entries (
    namespace TEXT NOT NULL,
    key TEXT NOT NULL,
    value JSONB NOT NULL,
    expires_at DOUBLE PRECISION NOT NULL,
    PRIMARY KEY (namespace, key)
);
"""


class PostgresCache:
    """Namespaced JSON cache over a Postgres pool."""

    def __init__(self, pool_provider, ttl: int = 300) -> None:
        # pool_provider is a ``PostgresClient`` (or any object with ``pool`` async property)
        # to avoid a circular import we accept a generic provider.
        self._provider = pool_provider
        self._ttl = ttl
        self._ready = False

    async def _ensure_table(self) -> None:
        if self._ready:
            return
        pool = await self._provider.pool
        if pool is None:
            return
        try:
            async with pool.acquire() as conn:
                await conn.execute(_CREATE_TABLE)
            self._ready = True
        except Exception as exc:  # noqa: BLE001
            logger.debug("postgres cache table create skipped: %s", exc)

    async def get_json(self, namespace: str, key: str) -> Any | None:
        await self._ensure_table()
        pool = await self._provider.pool
        if pool is None:
            return None
        try:
            async with pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT value, expires_at FROM cache_entries WHERE namespace=$1 AND key=$2",
                    namespace, key,
                )
            if row is None:
                return None
            if time.time() > float(row["expires_at"]):
                # Expired — delete lazily (best-effort, ignore errors).
                try:
                    async with pool.acquire() as conn:
                        await conn.execute(
                            "DELETE FROM cache_entries WHERE namespace=$1 AND key=$2",
                            namespace, key,
                        )
                except Exception:  # noqa: BLE001
                    pass
                return None
            val = row["value"]
            # asyncpg returns JSONB as str or dict depending on codec; handle both.
            if isinstance(val, str):
                return json.loads(val)
            return val
        except Exception as exc:  # noqa: BLE001
            logger.debug("postgres cache get failed (%s/%s): %s", namespace, key, exc)
            return None

    async def set_json(self, namespace: str, key: str, value: Any, ttl: int | None = None) -> None:
        await self._ensure_table()
        pool = await self._provider.pool
        if pool is None:
            return
        try:
            payload = json.dumps(value, ensure_ascii=False)
        except (TypeError, ValueError) as exc:
            logger.debug("cache serialize failed (%s/%s): %s", namespace, key, exc)
            return
        expires_at = time.time() + (ttl if ttl is not None else self._ttl)
        try:
            async with pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO cache_entries (namespace, key, value, expires_at)
                    VALUES ($1, $2, $3::jsonb, $4)
                    ON CONFLICT (namespace, key) DO UPDATE
                    SET value = EXCLUDED.value, expires_at = EXCLUDED.expires_at
                    """,
                    namespace, key, payload, expires_at,
                )
        except Exception as exc:  # noqa: BLE001
            logger.debug("postgres cache set failed (%s/%s): %s", namespace, key, exc)

    async def invalidate(self, namespace: str, key: str) -> None:
        pool = await self._provider.pool
        if pool is None:
            return
        try:
            async with pool.acquire() as conn:
                await conn.execute(
                    "DELETE FROM cache_entries WHERE namespace=$1 AND key=$2",
                    namespace, key,
                )
        except Exception:  # noqa: BLE001
            pass
