"""Postgres-backed persistent store — implements ``UserStore`` + ``DatabaseClient``.

Works with any Postgres-compatible server, including Supabase, Neon, and
self-hosted Postgres. Uses ``asyncpg`` for async access.

Tables are created lazily on first use (``CREATE TABLE IF NOT EXISTS``), so
a fresh database needs no manual migration.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any
from urllib.parse import urlsplit

from bot.database.circuit import CircuitBreaker
from bot.database.interfaces import DatabaseClient, UserStore
from bot.utils.errors import DatastoreUnavailable
from bot.utils.logging import get_logger

logger = get_logger(__name__)

CREATE_TABLES = """
CREATE TABLE IF NOT EXISTS users (
    telegram_id BIGINT PRIMARY KEY,
    uid TEXT,
    language TEXT NOT NULL DEFAULT 'en',
    created_at BIGINT NOT NULL,
    last_seen BIGINT,
    last_chat_type TEXT,
    hoyolab_cookie TEXT,
    is_private BOOLEAN NOT NULL DEFAULT FALSE,
    settings JSONB NOT NULL DEFAULT '{}'::jsonb
);
CREATE TABLE IF NOT EXISTS user_settings (
    telegram_id BIGINT NOT NULL,
    key TEXT NOT NULL,
    value TEXT NOT NULL,
    PRIMARY KEY (telegram_id, key)
);
-- Kept for backwards compat with earlier schema that used a separate table;
-- the current code uses users.settings JSONB, but we keep the table from being
-- referenced by older migrations.
CREATE TABLE IF NOT EXISTS groups (
    chat_id BIGINT PRIMARY KEY
);
CREATE TABLE IF NOT EXISTS counters (
    id TEXT PRIMARY KEY,
    value BIGINT NOT NULL DEFAULT 0
);
INSERT INTO counters (id, value) VALUES ('interactions', 0)
ON CONFLICT (id) DO NOTHING;
"""


def _now() -> int:
    return int(time.time())


def mask_postgres_url(url: str) -> str:
    if not url:
        return "<empty>"
    try:
        parts = urlsplit(url)
        host = parts.hostname or "?"
        port = f":{parts.port}" if parts.port else ""
        user = parts.username or ""
        auth = f"{user}:***@" if (user or parts.password) else ""
        # Normalise scheme for display (postgres/postgresql/supabase all count).
        return f"{parts.scheme}://{auth}{host}{port}"
    except Exception:
        return "<unparseable>"


def validate_postgres_url(url: str) -> tuple[bool, str]:
    if not url or not url.strip():
        return False, "POSTGRES_URL / DATABASE_URL is empty."
    lowered = url.strip().lower()
    valid_prefixes = ("postgres://", "postgresql://", "postgresql+asyncpg://")
    if not lowered.startswith(valid_prefixes):
        return False, (
            "Postgres URL must start with postgres:// or postgresql:// "
            f"(got {url.split('://', 1)[0] if '://' in url else url!r}). "
            "For Supabase, use the 'Connection string' URI from Database → Connection pooling."
        )
    return True, "ok"


# ---------------------------------------------------------------------------
# PostgresClient — owns the asyncpg pool
# ---------------------------------------------------------------------------
class PostgresClient(DatabaseClient):
    """Owns an ``asyncpg`` pool. Pool is created lazily."""

    def __init__(
        self,
        dsn: str,
        *,
        min_size: int = 1,
        max_size: int = 5,
        command_timeout: float = 10.0,
    ) -> None:
        self._dsn = dsn
        self._min_size = min_size
        self._max_size = max_size
        self._command_timeout = command_timeout
        self._pool = None
        self._pool_lock = asyncio.Lock()
        self._schema_ready = False
        logger.info("Postgres client configured for %s", mask_postgres_url(dsn))

    @property
    async def pool(self):
        """Return the pool, creating it on first use."""
        if self._pool is None:
            async with self._pool_lock:
                if self._pool is None:
                    try:
                        import asyncpg
                    except ImportError as exc:
                        raise RuntimeError(
                            "asyncpg is required for Postgres/Supabase backend. Install with: pip install asyncpg"
                        ) from exc
                    self._pool = await asyncpg.create_pool(
                        self._dsn,
                        min_size=self._min_size,
                        max_size=self._max_size,
                        command_timeout=self._command_timeout,
                    )
        return self._pool

    async def _ensure_schema(self) -> None:
        if self._schema_ready:
            return
        pool = await self.pool
        if pool is None:
            return
        try:
            async with pool.acquire() as conn:
                await conn.execute(CREATE_TABLES)
            self._schema_ready = True
        except Exception as exc:  # noqa: BLE001
            logger.debug("postgres schema ensure skipped: %s", exc)

    async def verify(self) -> bool:
        try:
            pool = await self.pool
            async with pool.acquire() as conn:
                await conn.fetchval("SELECT 1")
            logger.info("Postgres connection verified (SELECT 1)")
            # Also ensure tables so the upcoming store round-trip passes.
            await self._ensure_schema()
            return True
        except Exception as exc:  # noqa: BLE001
            logger.error("Postgres verify failed (%s): %s", type(exc).__name__, exc, exc_info=True)
            return False

    async def is_healthy(self) -> bool:
        try:
            pool = await self.pool
            async with pool.acquire() as conn:
                await conn.fetchval("SELECT 1")
            return True
        except Exception:  # noqa: BLE001
            return False

    async def self_test(self) -> bool:
        if not await self.verify():
            return False
        try:
            pool = await self.pool
            async with pool.acquire() as conn:
                await conn.execute("CREATE TABLE IF NOT EXISTS _diag_selftest (k TEXT PRIMARY KEY, v TEXT)")
                await conn.execute("INSERT INTO _diag_selftest (k,v) VALUES ('probe','ok') ON CONFLICT (k) DO UPDATE SET v='ok'")
                v = await conn.fetchval("SELECT v FROM _diag_selftest WHERE k='probe'")
                await conn.execute("DELETE FROM _diag_selftest WHERE k='probe'")
            ok = v == "ok"
            logger.info("Postgres self-test -> %s", "PASS" if ok else "FAIL")
            return ok
        except Exception as exc:  # noqa: BLE001
            logger.error("Postgres self-test FAILED (%s): %s", type(exc).__name__, exc, exc_info=True)
            return False

    async def close(self) -> None:
        if self._pool is not None:
            try:
                await self._pool.close()
            except Exception:  # noqa: BLE001
                pass
            self._pool = None


# ---------------------------------------------------------------------------
# PostgresStore — UserStore over Postgres (asyncpg)
# ---------------------------------------------------------------------------
class PostgresStore(UserStore):
    """Persistent store over Postgres / Supabase."""

    def __init__(
        self,
        client: PostgresClient,
        fallback=None,
        breaker_cooldown: float = 30.0,
    ) -> None:
        self._client = client
        self._fallback = fallback
        self._breaker = CircuitBreaker(breaker_cooldown)

    def _skip_db(self) -> bool:
        return self._fallback is not None and self._breaker.is_open()

    async def _ensure_schema(self) -> None:
        await self._client._ensure_schema()  # noqa: SLF001

    # -- users ------------------------------------------------------------
    async def get_or_create(self, telegram_user_id: int, default_language: str = "en") -> dict[str, Any]:
        if self._skip_db():
            return await self._fallback.get_or_create(telegram_user_id, default_language)
        try:
            await self._ensure_schema()
            pool = await self._client.pool
            async with pool.acquire() as conn:
                row = await conn.fetchrow("SELECT * FROM users WHERE telegram_id=$1", telegram_user_id)
                if row is None:
                    now = _now()
                    await conn.execute(
                        "INSERT INTO users (telegram_id, language, created_at, last_seen, is_private, settings) "
                        "VALUES ($1,$2,$3,$3,FALSE,'{}'::jsonb)",
                        telegram_user_id, default_language, now,
                    )
                    self._breaker.record_success()
                    return {"language": default_language, "created_at": now, "last_seen": now}
                self._breaker.record_success()
                return dict(row)
        except Exception as exc:  # noqa: BLE001
            self._breaker.record_failure()
            logger.warning("postgres get_or_create failed for %s: %s", telegram_user_id, exc)
            if self._fallback is not None:
                return await self._fallback.get_or_create(telegram_user_id, default_language)
            return {}

    async def link_uid(self, telegram_user_id: int, uid: str, default_language: str = "en") -> None:
        if self._skip_db():
            await self._fallback.link_uid(telegram_user_id, uid, default_language)
            return
        try:
            await self._ensure_schema()
            pool = await self._client.pool
            now = _now()
            async with pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO users (telegram_id, uid, language, created_at, last_seen, is_private, settings)
                    VALUES ($1, $2, $3, $4, $4, FALSE, '{}'::jsonb)
                    ON CONFLICT (telegram_id) DO UPDATE SET uid=EXCLUDED.uid, last_seen=EXCLUDED.last_seen
                    """,
                    telegram_user_id, str(uid), default_language, now,
                )
            self._breaker.record_success()
        except Exception as exc:  # noqa: BLE001
            self._breaker.record_failure()
            logger.error("postgres link_uid failed for %s: %s", telegram_user_id, exc)
            if self._fallback is not None:
                logger.warning("link_uid falling back to local store for %s", telegram_user_id)
                await self._fallback.link_uid(telegram_user_id, uid, default_language)
                return
            raise DatastoreUnavailable(str(exc)) from exc

    async def unlink_uid(self, telegram_user_id: int) -> bool:
        if self._skip_db():
            return await self._fallback.unlink_uid(telegram_user_id)
        try:
            await self._ensure_schema()
            pool = await self._client.pool
            async with pool.acquire() as conn:
                row = await conn.fetchrow("SELECT uid FROM users WHERE telegram_id=$1", telegram_user_id)
                had = row is not None and row["uid"] is not None
                if had:
                    await conn.execute("UPDATE users SET uid=NULL WHERE telegram_id=$1", telegram_user_id)
                self._breaker.record_success()
                return bool(had)
        except Exception as exc:  # noqa: BLE001
            self._breaker.record_failure()
            logger.error("postgres unlink_uid failed for %s: %s", telegram_user_id, exc)
            if self._fallback is not None:
                return await self._fallback.unlink_uid(telegram_user_id)
            return False

    async def get_uid(self, telegram_user_id: int) -> str | None:
        if self._skip_db():
            return await self._fallback.get_uid(telegram_user_id)
        try:
            pool = await self._client.pool
            async with pool.acquire() as conn:
                uid = await conn.fetchval("SELECT uid FROM users WHERE telegram_id=$1", telegram_user_id)
            self._breaker.record_success()
            return uid
        except Exception as exc:  # noqa: BLE001
            self._breaker.record_failure()
            logger.warning("postgres get_uid failed for %s: %s", telegram_user_id, exc)
            if self._fallback is not None:
                return await self._fallback.get_uid(telegram_user_id)
            return None

    # -- language ---------------------------------------------------------
    async def set_language(self, telegram_user_id: int, language: str, default_language: str = "en") -> None:
        if self._skip_db():
            await self._fallback.set_language(telegram_user_id, language, default_language)
            return
        try:
            await self._ensure_schema()
            pool = await self._client.pool
            now = _now()
            async with pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO users (telegram_id, language, created_at, last_seen, is_private, settings)
                    VALUES ($1,$2,$3,$3,FALSE,'{}'::jsonb)
                    ON CONFLICT (telegram_id) DO UPDATE SET language=EXCLUDED.language
                    """,
                    telegram_user_id, language, now,
                )
            self._breaker.record_success()
        except Exception as exc:  # noqa: BLE001
            self._breaker.record_failure()
            logger.error("postgres set_language failed for %s: %s", telegram_user_id, exc)
            if self._fallback is not None:
                await self._fallback.set_language(telegram_user_id, language, default_language)

    async def get_language(self, telegram_user_id: int, default_language: str = "en") -> str:
        if self._skip_db():
            return await self._fallback.get_language(telegram_user_id, default_language)
        try:
            pool = await self._client.pool
            async with pool.acquire() as conn:
                lang = await conn.fetchval("SELECT language FROM users WHERE telegram_id=$1", telegram_user_id)
            self._breaker.record_success()
            return lang if lang else default_language
        except Exception as exc:  # noqa: BLE001
            self._breaker.record_failure()
            logger.warning("postgres get_language failed for %s: %s", telegram_user_id, exc)
            if self._fallback is not None:
                return await self._fallback.get_language(telegram_user_id, default_language)
            return default_language

    # -- settings (stored as JSONB in users.settings) --------------------
    async def set_setting(self, telegram_user_id: int, key: str, value: str) -> None:
        if self._skip_db():
            await self._fallback.set_setting(telegram_user_id, key, value)
            return
        try:
            await self._ensure_schema()
            pool = await self._client.pool
            now = _now()
            async with pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO users (telegram_id, language, created_at, last_seen, is_private, settings)
                    VALUES ($1,'en',$2,$2,FALSE, jsonb_build_object($3,$4))
                    ON CONFLICT (telegram_id) DO UPDATE
                    SET settings = users.settings || jsonb_build_object($3,$4)
                    """,
                    telegram_user_id, now, key, value,
                )
            self._breaker.record_success()
        except Exception as exc:  # noqa: BLE001
            self._breaker.record_failure()
            logger.error("postgres set_setting failed for %s: %s", telegram_user_id, exc)
            if self._fallback is not None:
                await self._fallback.set_setting(telegram_user_id, key, value)

    async def get_setting(self, telegram_user_id: int, key: str, default: str | None = None) -> str | None:
        if self._skip_db():
            return await self._fallback.get_setting(telegram_user_id, key, default)
        try:
            pool = await self._client.pool
            async with pool.acquire() as conn:
                settings = await conn.fetchval("SELECT settings FROM users WHERE telegram_id=$1", telegram_user_id)
            self._breaker.record_success()
            if settings is not None:
                # asyncpg may return dict (jsonb) or str depending on codec
                import json as _json

                data = settings if isinstance(settings, dict) else _json.loads(settings) if isinstance(settings, str) else {}
                return data.get(key, default)
            return default
        except Exception as exc:  # noqa: BLE001
            self._breaker.record_failure()
            logger.warning("postgres get_setting failed for %s: %s", telegram_user_id, exc)
            if self._fallback is not None:
                return await self._fallback.get_setting(telegram_user_id, key, default)
            return default

    async def get_all_settings(self, telegram_user_id: int) -> dict[str, str]:
        if self._skip_db():
            return await self._fallback.get_all_settings(telegram_user_id)
        try:
            pool = await self._client.pool
            async with pool.acquire() as conn:
                settings = await conn.fetchval("SELECT settings FROM users WHERE telegram_id=$1", telegram_user_id)
            self._breaker.record_success()
            if settings is not None:
                import json as _json

                if isinstance(settings, dict):
                    return dict(settings)
                if isinstance(settings, str):
                    return _json.loads(settings)
            return {}
        except Exception as exc:  # noqa: BLE001
            self._breaker.record_failure()
            logger.warning("postgres get_all_settings failed for %s: %s", telegram_user_id, exc)
            if self._fallback is not None:
                return await self._fallback.get_all_settings(telegram_user_id)
            return {}

    # -- HoYoLAB cookie ---------------------------------------------------
    async def set_hoyolab_cookie(self, telegram_user_id: int, token: str) -> None:
        if self._skip_db():
            await self._fallback.set_hoyolab_cookie(telegram_user_id, token)
            return
        try:
            await self._ensure_schema()
            pool = await self._client.pool
            now = _now()
            async with pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO users (telegram_id, hoyolab_cookie, created_at, last_seen, is_private, settings)
                    VALUES ($1,$2,$3,$3,FALSE,'{}'::jsonb)
                    ON CONFLICT (telegram_id) DO UPDATE SET hoyolab_cookie=EXCLUDED.hoyolab_cookie
                    """,
                    telegram_user_id, token, now,
                )
            self._breaker.record_success()
        except Exception as exc:  # noqa: BLE001
            self._breaker.record_failure()
            logger.error("postgres set_hoyolab_cookie failed for %s: %s", telegram_user_id, exc)
            if self._fallback is not None:
                await self._fallback.set_hoyolab_cookie(telegram_user_id, token)

    async def get_hoyolab_cookie(self, telegram_user_id: int) -> str | None:
        if self._skip_db():
            return await self._fallback.get_hoyolab_cookie(telegram_user_id)
        try:
            pool = await self._client.pool
            async with pool.acquire() as conn:
                v = await conn.fetchval("SELECT hoyolab_cookie FROM users WHERE telegram_id=$1", telegram_user_id)
            self._breaker.record_success()
            return v
        except Exception as exc:  # noqa: BLE001
            self._breaker.record_failure()
            logger.warning("postgres get_hoyolab_cookie failed for %s: %s", telegram_user_id, exc)
            if self._fallback is not None:
                return await self._fallback.get_hoyolab_cookie(telegram_user_id)
            return None

    async def clear_hoyolab_cookie(self, telegram_user_id: int) -> bool:
        if self._skip_db():
            return await self._fallback.clear_hoyolab_cookie(telegram_user_id)
        try:
            pool = await self._client.pool
            async with pool.acquire() as conn:
                row = await conn.fetchrow("SELECT hoyolab_cookie FROM users WHERE telegram_id=$1", telegram_user_id)
                had = row is not None and row["hoyolab_cookie"] is not None
                if had:
                    await conn.execute("UPDATE users SET hoyolab_cookie=NULL WHERE telegram_id=$1", telegram_user_id)
                self._breaker.record_success()
                return bool(had)
        except Exception as exc:  # noqa: BLE001
            self._breaker.record_failure()
            logger.error("postgres clear_hoyolab_cookie failed for %s: %s", telegram_user_id, exc)
            if self._fallback is not None:
                return await self._fallback.clear_hoyolab_cookie(telegram_user_id)
            return False

    # -- registration / tracking -----------------------------------------
    async def register_interaction(self, telegram_user_id: int, chat_type: str | None) -> None:
        if self._breaker.is_open():
            return
        try:
            await self._ensure_schema()
            pool = await self._client.pool
            now = _now()
            is_priv = chat_type in (None, "private")
            async with pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO users (telegram_id, created_at, last_seen, last_chat_type, is_private, settings)
                    VALUES ($1,$2,$3,$4,$5,'{}'::jsonb)
                    ON CONFLICT (telegram_id) DO UPDATE
                    SET last_seen=EXCLUDED.last_seen, last_chat_type=EXCLUDED.last_chat_type,
                        is_private = users.is_private OR EXCLUDED.is_private
                    """,
                    telegram_user_id, now, now, chat_type or "private", is_priv,
                )
                await conn.execute(
                    "INSERT INTO counters (id, value) VALUES ('interactions', 1) "
                    "ON CONFLICT (id) DO UPDATE SET value = counters.value + 1"
                )
            self._breaker.record_success()
        except Exception as exc:  # noqa: BLE001
            self._breaker.record_failure()
            logger.debug("postgres register_interaction failed for %s: %s", telegram_user_id, exc)

    async def register_group(self, chat_id: int) -> None:
        try:
            await self._ensure_schema()
            pool = await self._client.pool
            async with pool.acquire() as conn:
                await conn.execute("INSERT INTO groups (chat_id) VALUES ($1) ON CONFLICT DO NOTHING", chat_id)
        except Exception as exc:  # noqa: BLE001
            logger.debug("postgres register_group failed for %s: %s", chat_id, exc)

    async def unregister_group(self, chat_id: int) -> None:
        try:
            pool = await self._client.pool
            async with pool.acquire() as conn:
                await conn.execute("DELETE FROM groups WHERE chat_id=$1", chat_id)
        except Exception as exc:  # noqa: BLE001
            logger.debug("postgres unregister_group failed for %s: %s", chat_id, exc)

    # -- broadcast --------------------------------------------------------
    async def all_users(self) -> list[int]:
        try:
            pool = await self._client.pool
            async with pool.acquire() as conn:
                rows = await conn.fetch("SELECT telegram_id FROM users")
            return [int(r["telegram_id"]) for r in rows]
        except Exception as exc:  # noqa: BLE001
            logger.warning("postgres all_users failed: %s", exc)
            return []

    async def all_groups(self) -> list[int]:
        try:
            pool = await self._client.pool
            async with pool.acquire() as conn:
                rows = await conn.fetch("SELECT chat_id FROM groups")
            return [int(r["chat_id"]) for r in rows]
        except Exception as exc:  # noqa: BLE001
            logger.warning("postgres all_groups failed: %s", exc)
            return []

    async def discard_users(self, ids: list[int]) -> None:
        if not ids:
            return
        try:
            pool = await self._client.pool
            async with pool.acquire() as conn:
                await conn.execute("DELETE FROM users WHERE telegram_id = ANY($1)", ids)
        except Exception as exc:  # noqa: BLE001
            logger.debug("postgres discard_users failed: %s", exc)

    async def discard_groups(self, ids: list[int]) -> None:
        if not ids:
            return
        try:
            pool = await self._client.pool
            async with pool.acquire() as conn:
                await conn.execute("DELETE FROM groups WHERE chat_id = ANY($1)", ids)
        except Exception as exc:  # noqa: BLE001
            logger.debug("postgres discard_groups failed: %s", exc)

    # -- statistics -------------------------------------------------------
    async def count_users(self) -> int:
        try:
            pool = await self._client.pool
            async with pool.acquire() as conn:
                return int(await conn.fetchval("SELECT COUNT(*) FROM users"))
        except Exception:
            return 0

    async def count_private_chats(self) -> int:
        try:
            pool = await self._client.pool
            async with pool.acquire() as conn:
                return int(await conn.fetchval("SELECT COUNT(*) FROM users WHERE is_private=TRUE"))
        except Exception:
            return 0

    async def count_groups(self) -> int:
        try:
            pool = await self._client.pool
            async with pool.acquire() as conn:
                return int(await conn.fetchval("SELECT COUNT(*) FROM groups"))
        except Exception:
            return 0

    async def count_interactions(self) -> int:
        try:
            pool = await self._client.pool
            async with pool.acquire() as conn:
                v = await conn.fetchval("SELECT value FROM counters WHERE id='interactions'")
            return int(v) if v is not None else 0
        except Exception:
            return 0
