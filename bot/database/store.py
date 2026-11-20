"""Redis-backed persistent store — the primary source of truth for user data.

Holds everything that must survive bot restarts:
  * per-user record (linked Genshin UID, language, timestamps, session metadata),
  * per-user settings (free-form key/value, so new preferences need no schema change),
  * the set of registered users and the subsets by chat context,
  * the set of groups/supergroups the bot is in,
  * bot statistics counters.

Every operation is wrapped so a Redis outage degrades gracefully (safe default / no-op)
rather than crashing the bot. Reads return ``None``/defaults on failure; the caller then
behaves as if the data is absent (e.g. the user is asked to link) — never a crash.

Key layout
----------
  user:{tid}            hash   uid, language, created_at, last_seen, last_chat_type
  user:{tid}:settings   hash   arbitrary preference key/value
  users                 set    all registered telegram user ids
  chats:private         set    user ids that have opened a private chat
  groups                set    group/supergroup chat ids the bot is in
  stats:interactions    str    monotonically increasing interaction counter
"""

from __future__ import annotations

import time
from typing import Any

from redis.asyncio import Redis
from redis.exceptions import RedisError

from bot.database.local_store import LocalStore
from bot.utils.errors import DatastoreUnavailable
from bot.utils.logging import get_logger

logger = get_logger(__name__)

USERS_SET = "users"
PRIVATE_SET = "chats:private"
GROUPS_SET = "groups"
INTERACTIONS = "stats:interactions"


class _CircuitBreaker:
    """Skip a known-down Redis for a cooldown so commands don't wait on it every time.

    After a failure the circuit stays 'open' for ``cooldown`` seconds — while open, callers
    go straight to the fallback instead of paying the connection timeout again. A success
    closes it immediately.
    """

    def __init__(self, cooldown: float = 30.0) -> None:
        self._cooldown = cooldown
        self._open_until = 0.0

    def is_open(self) -> bool:
        return time.monotonic() < self._open_until

    def record_failure(self) -> None:
        self._open_until = time.monotonic() + self._cooldown

    def record_success(self) -> None:
        self._open_until = 0.0


def _user_key(tid: int) -> str:
    return f"user:{tid}"


def _settings_key(tid: int) -> str:
    return f"user:{tid}:settings"


def _now() -> int:
    return int(time.time())


class RedisStore:
    """Async persistent store backed by Redis."""

    def __init__(
        self,
        redis: Redis,
        fallback: LocalStore | None = None,
        breaker_cooldown: float = 30.0,
    ) -> None:
        self._r = redis
        self._fallback = fallback
        self._breaker = _CircuitBreaker(breaker_cooldown)

    def _skip_redis(self) -> bool:
        """True when we should bypass Redis (circuit open) and a fallback exists."""
        return self._fallback is not None and self._breaker.is_open()

    # ------------------------------------------------------------------ users
    async def get_or_create(self, telegram_user_id: int, default_language: str = "en") -> dict[str, Any]:
        """Ensure a user record exists and is registered. Returns the record.

        Mirrors the degradation contract of its siblings: when the circuit is open it goes
        straight to the local fallback, and a live Redis failure falls back too (instead of
        returning ``{}`` and silently skipping the first-contact user row).
        """
        if self._skip_redis():
            return await self._fallback.get_or_create(telegram_user_id, default_language)
        key = _user_key(telegram_user_id)
        try:
            existing = await self._r.hgetall(key)
            if not existing:
                now = _now()
                await self._r.hset(key, mapping={
                    "language": default_language,
                    "created_at": now,
                    "last_seen": now,
                })
                await self._r.sadd(USERS_SET, telegram_user_id)
                self._breaker.record_success()
                return {"language": default_language, "created_at": now, "last_seen": now}
            self._breaker.record_success()
            return existing
        except RedisError as exc:
            self._breaker.record_failure()
            logger.warning("get_or_create failed for %s: %s", telegram_user_id, exc)
            if self._fallback is not None:
                return await self._fallback.get_or_create(telegram_user_id, default_language)
            return {}

    async def link_uid(self, telegram_user_id: int, uid: str, default_language: str = "en") -> None:
        """Persist a user's Genshin UID. Uses the local fallback if Redis is unavailable."""
        if self._skip_redis():
            await self._fallback.link_uid(telegram_user_id, uid, default_language)
            return
        key = _user_key(telegram_user_id)
        try:
            async with self._r.pipeline(transaction=True) as pipe:
                pipe.hsetnx(key, "created_at", _now())
                pipe.hsetnx(key, "language", default_language)
                pipe.hset(key, mapping={"uid": str(uid), "last_seen": _now()})
                pipe.sadd(USERS_SET, telegram_user_id)
                await pipe.execute()
            self._breaker.record_success()
        except RedisError as exc:
            self._breaker.record_failure()
            logger.error("link_uid failed for %s: %s", telegram_user_id, exc)
            if self._fallback is not None:
                logger.warning("link_uid falling back to local store for %s", telegram_user_id)
                await self._fallback.link_uid(telegram_user_id, uid, default_language)
                return
            # No fallback: surface a clear, localized "try again" message.
            raise DatastoreUnavailable(str(exc)) from exc

    async def unlink_uid(self, telegram_user_id: int) -> bool:
        """Remove a user's linked UID. Returns True if one was present."""
        if self._skip_redis():
            return await self._fallback.unlink_uid(telegram_user_id)
        key = _user_key(telegram_user_id)
        try:
            removed = await self._r.hdel(key, "uid")
            self._breaker.record_success()
            return bool(removed)
        except RedisError as exc:
            self._breaker.record_failure()
            logger.error("unlink_uid failed for %s: %s", telegram_user_id, exc)
            if self._fallback is not None:
                return await self._fallback.unlink_uid(telegram_user_id)
            return False

    async def get_uid(self, telegram_user_id: int) -> str | None:
        if self._skip_redis():
            return await self._fallback.get_uid(telegram_user_id)
        try:
            value = await self._r.hget(_user_key(telegram_user_id), "uid")
            self._breaker.record_success()
            return value
        except RedisError as exc:
            self._breaker.record_failure()
            logger.warning("get_uid failed for %s: %s", telegram_user_id, exc)
            if self._fallback is not None:
                return await self._fallback.get_uid(telegram_user_id)
            return None

    # --------------------------------------------------------------- language
    async def set_language(self, telegram_user_id: int, language: str, default_language: str = "en") -> None:
        if self._skip_redis():
            await self._fallback.set_language(telegram_user_id, language, default_language)
            return
        key = _user_key(telegram_user_id)
        try:
            await self._r.hset(key, "language", language)
            await self._r.sadd(USERS_SET, telegram_user_id)
            self._breaker.record_success()
        except RedisError as exc:
            self._breaker.record_failure()
            logger.error("set_language failed for %s: %s", telegram_user_id, exc)
            if self._fallback is not None:
                await self._fallback.set_language(telegram_user_id, language, default_language)

    async def get_language(self, telegram_user_id: int, default_language: str = "en") -> str:
        if self._skip_redis():
            return await self._fallback.get_language(telegram_user_id, default_language)
        try:
            lang = await self._r.hget(_user_key(telegram_user_id), "language")
            self._breaker.record_success()
            return lang or default_language
        except RedisError as exc:
            self._breaker.record_failure()
            logger.warning("get_language failed for %s: %s", telegram_user_id, exc)
            if self._fallback is not None:
                return await self._fallback.get_language(telegram_user_id, default_language)
            return default_language

    # --------------------------------------------------------------- settings
    async def set_setting(self, telegram_user_id: int, key: str, value: str) -> None:
        if self._skip_redis():
            await self._fallback.set_setting(telegram_user_id, key, value)
            return
        try:
            await self._r.hset(_settings_key(telegram_user_id), key, value)
            self._breaker.record_success()
        except RedisError as exc:
            self._breaker.record_failure()
            logger.error("set_setting failed for %s: %s", telegram_user_id, exc)
            if self._fallback is not None:
                await self._fallback.set_setting(telegram_user_id, key, value)

    async def get_setting(self, telegram_user_id: int, key: str, default: str | None = None) -> str | None:
        if self._skip_redis():
            return await self._fallback.get_setting(telegram_user_id, key, default)
        try:
            value = await self._r.hget(_settings_key(telegram_user_id), key)
            self._breaker.record_success()
            return value if value is not None else default
        except RedisError as exc:
            self._breaker.record_failure()
            logger.warning("get_setting failed for %s: %s", telegram_user_id, exc)
            if self._fallback is not None:
                return await self._fallback.get_setting(telegram_user_id, key, default)
            return default

    async def get_all_settings(self, telegram_user_id: int) -> dict[str, str]:
        if self._skip_redis():
            return await self._fallback.get_all_settings(telegram_user_id)
        try:
            result = await self._r.hgetall(_settings_key(telegram_user_id)) or {}
            self._breaker.record_success()
            return result
        except RedisError as exc:
            self._breaker.record_failure()
            logger.warning("get_all_settings failed for %s: %s", telegram_user_id, exc)
            if self._fallback is not None:
                return await self._fallback.get_all_settings(telegram_user_id)
            return {}

    # ----------------------------------------------- HoYoLAB session cookie
    # Stored as an (already-encrypted) token on the user hash, so it never appears in the
    # free-form settings hash and can't leak via get_all_settings. Mirrors the link_uid
    # degradation pattern (circuit breaker + local fallback).
    async def set_hoyolab_cookie(self, telegram_user_id: int, token: str) -> None:
        if self._skip_redis():
            await self._fallback.set_hoyolab_cookie(telegram_user_id, token)
            return
        key = _user_key(telegram_user_id)
        try:
            await self._r.hset(key, "hoyolab_cookie", token)
            await self._r.sadd(USERS_SET, telegram_user_id)
            self._breaker.record_success()
        except RedisError as exc:
            self._breaker.record_failure()
            logger.error("set_hoyolab_cookie failed for %s: %s", telegram_user_id, exc)
            if self._fallback is not None:
                await self._fallback.set_hoyolab_cookie(telegram_user_id, token)

    async def get_hoyolab_cookie(self, telegram_user_id: int) -> str | None:
        if self._skip_redis():
            return await self._fallback.get_hoyolab_cookie(telegram_user_id)
        try:
            value = await self._r.hget(_user_key(telegram_user_id), "hoyolab_cookie")
            self._breaker.record_success()
            return value
        except RedisError as exc:
            self._breaker.record_failure()
            logger.warning("get_hoyolab_cookie failed for %s: %s", telegram_user_id, exc)
            if self._fallback is not None:
                return await self._fallback.get_hoyolab_cookie(telegram_user_id)
            return None

    async def clear_hoyolab_cookie(self, telegram_user_id: int) -> bool:
        if self._skip_redis():
            return await self._fallback.clear_hoyolab_cookie(telegram_user_id)
        try:
            removed = await self._r.hdel(_user_key(telegram_user_id), "hoyolab_cookie")
            self._breaker.record_success()
            return bool(removed)
        except RedisError as exc:
            self._breaker.record_failure()
            logger.error("clear_hoyolab_cookie failed for %s: %s", telegram_user_id, exc)
            if self._fallback is not None:
                return await self._fallback.clear_hoyolab_cookie(telegram_user_id)
            return False

    # ----------------------------------------------- registration & sessions
    async def register_interaction(self, telegram_user_id: int, chat_type: str | None) -> None:
        """Register a user on interaction and record lightweight session metadata.

        Called for every update via the tracking handler. Idempotent (sets prevent
        duplicates). Never raises.

        Participates in the circuit breaker: this is the single most frequently-called write,
        so while Redis is known-down we skip it entirely rather than paying the full socket
        timeout on every update (which would otherwise pile up background tasks for the whole
        cooldown window). It is best-effort statistics/registration, so skipping is safe.
        """
        if self._breaker.is_open():
            return
        key = _user_key(telegram_user_id)
        try:
            async with self._r.pipeline(transaction=False) as pipe:
                pipe.sadd(USERS_SET, telegram_user_id)
                pipe.hsetnx(key, "created_at", _now())
                pipe.hset(key, mapping={"last_seen": _now(), "last_chat_type": chat_type or "private"})
                if chat_type in (None, "private"):
                    pipe.sadd(PRIVATE_SET, telegram_user_id)
                pipe.incr(INTERACTIONS)
                await pipe.execute()
            self._breaker.record_success()
        except RedisError as exc:
            self._breaker.record_failure()
            logger.debug("register_interaction failed for %s: %s", telegram_user_id, exc)

    async def register_group(self, chat_id: int) -> None:
        try:
            await self._r.sadd(GROUPS_SET, chat_id)
        except RedisError as exc:
            logger.debug("register_group failed for %s: %s", chat_id, exc)

    async def unregister_group(self, chat_id: int) -> None:
        try:
            await self._r.srem(GROUPS_SET, chat_id)
        except RedisError as exc:
            logger.debug("unregister_group failed for %s: %s", chat_id, exc)

    # ---------------------------------------------------- broadcast recipients
    async def all_users(self) -> list[int]:
        """Return every registered user id (for broadcasting). Empty list on failure."""
        return await self._members(USERS_SET)

    async def all_groups(self) -> list[int]:
        """Return every registered group/supergroup chat id. Empty list on failure."""
        return await self._members(GROUPS_SET)

    async def _members(self, set_key: str) -> list[int]:
        try:
            members = await self._r.smembers(set_key)
        except RedisError as exc:
            logger.warning("smembers %s failed: %s", set_key, exc)
            return []
        ids: list[int] = []
        for m in members or ():
            try:
                ids.append(int(m))
            except (TypeError, ValueError):
                continue
        return ids

    async def discard_users(self, ids: list[int]) -> None:
        """Remove users from the registered/private sets (e.g. they blocked the bot)."""
        if not ids:
            return
        try:
            await self._r.srem(USERS_SET, *ids)
            await self._r.srem(PRIVATE_SET, *ids)
        except RedisError as exc:
            logger.debug("discard_users failed: %s", exc)

    async def discard_groups(self, ids: list[int]) -> None:
        """Remove groups from the registered set (e.g. the bot was kicked)."""
        if not ids:
            return
        try:
            await self._r.srem(GROUPS_SET, *ids)
        except RedisError as exc:
            logger.debug("discard_groups failed: %s", exc)

    # -------------------------------------------------------------- statistics
    async def count_users(self) -> int:
        try:
            return int(await self._r.scard(USERS_SET))
        except RedisError:
            return 0

    async def count_private_chats(self) -> int:
        try:
            return int(await self._r.scard(PRIVATE_SET))
        except RedisError:
            return 0

    async def count_groups(self) -> int:
        try:
            return int(await self._r.scard(GROUPS_SET))
        except RedisError:
            return 0

    async def count_interactions(self) -> int:
        try:
            value = await self._r.get(INTERACTIONS)
            return int(value) if value else 0
        except (RedisError, ValueError):
            return 0
