"""Redis connection management (Upstash-compatible).

Wraps ``redis.asyncio`` with:
  * lazy, pooled connections (redis-py auto-reconnects on the next command after a drop),
  * a periodic health check so idle connections are validated,
  * built-in retry with exponential backoff on transient connection/timeout errors,
  * automatic TLS upgrade for Upstash ``redis://`` URLs (Upstash requires TLS),
  * URL validation that rejects the *wrong* Upstash endpoint (the REST ``https://`` URL)
    with an actionable message instead of a bare ``ValueError`` deep in startup,
  * a ``verify()`` used at startup to confirm the connection before the bot serves traffic,
  * a ``self_test()`` that exercises PING + write/read/delete and logs each result.

All higher-level stores accept the underlying ``redis.asyncio.Redis`` client and wrap their
own operations in try/except so a Redis outage degrades gracefully instead of crashing.
"""

from __future__ import annotations

from urllib.parse import urlsplit

import redis.asyncio as redis
from redis.asyncio.retry import Retry
from redis.backoff import ExponentialBackoff
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import RedisError, TimeoutError as RedisTimeoutError

from bot.utils.logging import get_logger

logger = get_logger(__name__)

# Schemes redis-py accepts. Anything else (notably ``https://`` — the Upstash REST
# endpoint) cannot be used by the Redis protocol client.
_VALID_SCHEMES = ("redis://", "rediss://", "unix://")


def normalize_url(url: str) -> str:
    """Normalize a user-supplied Redis URL for redis-py.

    * Trims surrounding whitespace/quotes (a very common copy-paste artifact).
    * Upgrades Upstash ``redis://`` URLs to TLS (``rediss://``) — Upstash closes plain
      connections.
    * Adds a scheme to a bare ``host:port`` string (``rediss://`` for Upstash hosts which
      require TLS, ``redis://`` otherwise).
    """
    if not url:
        return url
    url = url.strip().strip('"').strip("'")

    lowered = url.lower()
    is_upstash = "upstash.io" in lowered

    # Bare host[:port] with no scheme at all → add one so from_url can parse it.
    if "://" not in url:
        return ("rediss://" if is_upstash else "redis://") + url

    if lowered.startswith("redis://") and is_upstash:
        return "rediss://" + url[len("redis://"):]
    return url


def mask_url(url: str) -> str:
    """Return a log-safe rendering of a Redis URL with the password removed."""
    if not url:
        return "<empty>"
    try:
        parts = urlsplit(url)
        host = parts.hostname or "?"
        port = f":{parts.port}" if parts.port else ""
        user = parts.username or ""
        auth = f"{user}:***@" if (user or parts.password) else ""
        return f"{parts.scheme}://{auth}{host}{port}"
    except Exception:  # noqa: BLE001 - masking must never raise
        return "<unparseable>"


def validate_redis_url(url: str) -> tuple[bool, str]:
    """Validate a Redis URL *before* the pool is built.

    Returns ``(ok, message)``. ``message`` is a human-actionable explanation when invalid.
    This catches the most common deployment mistake: pasting the Upstash **REST** URL
    (``https://<db>.upstash.io``) or REST token instead of the **Redis** connection URL
    (``rediss://default:<password>@<db>.upstash.io:6379``), which redis-py rejects with a
    bare ``ValueError``.
    """
    if not url or not url.strip():
        return False, "REDIS_URL is empty."

    normalized = normalize_url(url)
    lowered = normalized.lower()

    if lowered.startswith(("https://", "http://")):
        return False, (
            "REDIS_URL looks like the Upstash REST endpoint "
            f"({mask_url(normalized)}). The bot uses the Redis protocol, not REST. "
            "In the Upstash console open your database → 'Connect' → copy the URL under "
            "'Redis' (starts with rediss://default:<password>@<host>:6379), NOT the "
            "'REST API' URL/token."
        )

    if not lowered.startswith(_VALID_SCHEMES):
        scheme = normalized.split("://", 1)[0] if "://" in normalized else normalized
        return False, (
            f"REDIS_URL scheme '{scheme}' is not supported. Use one of: "
            "redis://, rediss:// (TLS, required by Upstash), or unix://."
        )

    # Final structural check: let redis-py parse it so we fail here (with context)
    # rather than deep inside build_app_context.
    try:
        redis.from_url(normalized, decode_responses=True)
    except Exception as exc:  # noqa: BLE001
        return False, f"REDIS_URL could not be parsed by redis-py: {exc}"

    return True, "ok"


class RedisClient:
    """Owns the process-wide async Redis connection pool."""

    def __init__(
        self,
        url: str,
        *,
        connect_timeout: float = 4.0,
        socket_timeout: float = 4.0,
        retries: int = 1,
    ) -> None:
        self._url = normalize_url(url)
        self._redis: redis.Redis | None = None
        self._connect_timeout = connect_timeout
        self._socket_timeout = socket_timeout
        self._retries = retries
        logger.info("Redis client configured for %s", mask_url(self._url))

    @property
    def client(self) -> redis.Redis:
        """Return the shared client, creating the pool on first access.

        Timeouts are deliberately short so an unreachable Redis fails fast (a couple of
        seconds) rather than hanging the command for tens of seconds.
        """
        if self._redis is None:
            self._redis = redis.from_url(
                self._url,
                decode_responses=True,
                socket_connect_timeout=self._connect_timeout,
                socket_timeout=self._socket_timeout,
                socket_keepalive=True,
                health_check_interval=30,
                retry=Retry(ExponentialBackoff(cap=1, base=0.1), retries=self._retries),
                retry_on_error=[RedisConnectionError, RedisTimeoutError],
            )
        return self._redis

    async def verify(self) -> bool:
        """Ping Redis to confirm connectivity. Returns False instead of raising.

        Catches *any* exception (not just ``RedisError``) so a misconfigured URL or an
        unexpected client error can never abort startup.
        """
        try:
            pong = await self.client.ping()
            if pong:
                logger.info("Redis connection verified (PING -> PONG)")
                return True
            logger.error("Redis PING returned a falsy response")
            return False
        except Exception as exc:  # noqa: BLE001 - never propagate out of startup
            logger.error(
                "Redis connection could not be verified (%s): %s",
                type(exc).__name__, exc, exc_info=True,
            )
            return False

    async def self_test(self) -> bool:
        """Exercise PING + write/read/delete on a throwaway key. Never raises.

        Logs the result of every operation so a partially-working Redis (e.g. read-only,
        eviction, auth-limited) is diagnosable from the startup logs. Returns True only if
        the full round-trip succeeds.
        """
        key = "diag:selftest"
        try:
            pong = await self.client.ping()
            logger.info("Redis self-test | PING   -> %s", pong)

            await self.client.set(key, "ok", ex=30)
            logger.info("Redis self-test | WRITE  -> set %s", key)

            value = await self.client.get(key)
            logger.info("Redis self-test | READ   -> %r", value)

            deleted = await self.client.delete(key)
            logger.info("Redis self-test | DELETE -> removed %s key(s)", deleted)

            ok = bool(pong) and value == "ok" and deleted == 1
            logger.info("Redis self-test | RESULT -> %s", "PASS" if ok else "FAIL")
            return ok
        except Exception as exc:  # noqa: BLE001 - diagnostics must never crash startup
            logger.error(
                "Redis self-test FAILED (%s): %s", type(exc).__name__, exc, exc_info=True,
            )
            return False

    async def is_healthy(self) -> bool:
        """Lightweight health probe used by /stats. Never raises."""
        try:
            return bool(await self.client.ping())
        except Exception:  # noqa: BLE001
            return False

    async def close(self) -> None:
        """Close the pool on shutdown."""
        if self._redis is not None:
            try:
                await self._redis.aclose()
            except Exception:  # noqa: BLE001
                pass
            self._redis = None
