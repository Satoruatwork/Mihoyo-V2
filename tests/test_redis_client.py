"""Tests for Redis URL normalization/validation and the startup diagnostics.

Regression coverage for the deployment bug where an Upstash REST URL
(``https://<db>.upstash.io``) fed to redis-py raised a ``ValueError`` out of
``build_app_context`` inside ``_post_init`` and prevented the bot from ever
polling. ``validate_redis_url`` now rejects that URL up front with a clear message,
``verify()`` never propagates, and ``self_test()`` exercises full CRUD.
"""

from __future__ import annotations

import fakeredis.aioredis
import pytest

from bot.database.redis_client import (
    RedisClient,
    mask_url,
    normalize_url,
    validate_redis_url,
)


def test_normalize_upgrades_upstash_to_tls():
    assert normalize_url("redis://default:pw@x.upstash.io:6379") == (
        "rediss://default:pw@x.upstash.io:6379"
    )


def test_normalize_strips_whitespace_and_quotes():
    assert normalize_url('  "rediss://default:pw@x.upstash.io:6379"  ') == (
        "rediss://default:pw@x.upstash.io:6379"
    )


def test_normalize_adds_scheme_to_bare_host():
    assert normalize_url("x.upstash.io:6379") == "rediss://x.upstash.io:6379"
    assert normalize_url("localhost:6379") == "redis://localhost:6379"


def test_normalize_leaves_plain_non_upstash_redis_unchanged():
    assert normalize_url("redis://localhost:6379") == "redis://localhost:6379"


@pytest.mark.parametrize(
    "url",
    [
        "rediss://default:pw@x.upstash.io:6379",
        "redis://default:pw@x.upstash.io:6379",
        "redis://localhost:6379/0",
    ],
)
def test_validate_accepts_valid_urls(url):
    ok, msg = validate_redis_url(url)
    assert ok, msg


def test_validate_rejects_rest_endpoint():
    ok, msg = validate_redis_url("https://x.upstash.io")
    assert not ok
    assert "REST" in msg


def test_validate_rejects_empty():
    ok, msg = validate_redis_url("")
    assert not ok
    assert "empty" in msg.lower()


def test_validate_rejects_unknown_scheme():
    ok, msg = validate_redis_url("memcache://x:1")
    assert not ok
    assert "scheme" in msg.lower()


def test_mask_url_hides_password():
    masked = mask_url("rediss://default:supersecret@x.upstash.io:6379")
    assert "supersecret" not in masked
    assert "x.upstash.io" in masked


async def test_self_test_full_crud_passes_on_working_redis():
    rc = RedisClient("rediss://default:pw@x.upstash.io:6379")
    rc._redis = fakeredis.aioredis.FakeRedis(decode_responses=True)  # inject fake, offline
    assert await rc.verify() is True
    assert await rc.self_test() is True
    # self_test cleans up after itself.
    assert await rc._redis.get("diag:selftest") is None
    await rc.close()
