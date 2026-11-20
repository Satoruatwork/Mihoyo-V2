#!/usr/bin/env python3
"""Standalone Redis connectivity check.

Tells you whether your Redis is actually reachable/writable, independent of the bot — so you
can distinguish "the database is down/deleted" from "my REDIS_URL is wrong" before deciding
to recreate anything.

Usage:
    REDIS_URL='rediss://default:<password>@<host>.upstash.io:6379' python scripts/check_redis.py
    # or pass it as an argument:
    python scripts/check_redis.py 'rediss://default:<password>@<host>.upstash.io:6379'

Exit code 0 = healthy (connect + read + write + delete all worked); 1 = a problem was found.
"""

from __future__ import annotations

import asyncio
import os
import sys

# Make the bot package importable when run from the repo root.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bot.database.redis_client import RedisClient, mask_url, validate_redis_url  # noqa: E402


async def main() -> int:
    url = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("REDIS_URL", "")

    if not url:
        print("✗ No REDIS_URL provided (set the env var or pass it as an argument).")
        return 1

    print(f"Checking Redis: {mask_url(url)}")

    ok, message = validate_redis_url(url)
    if not ok:
        print(f"✗ URL is invalid: {message}")
        print("  → Fix REDIS_URL. Use the Upstash 'Redis' URL (rediss://default:<pw>@<host>:6379),")
        print("    NOT the 'REST API' URL (https://...).")
        return 1
    print("✓ URL format looks valid.")

    client = RedisClient(url, connect_timeout=6.0, socket_timeout=6.0, retries=1)
    if not await client.verify():
        print("✗ Could not connect / PING failed.")
        print("  Likely causes:")
        print("   • the database was paused or deleted (Upstash free DBs can be removed when idle)")
        print("   • wrong host/password in the URL")
        print("   • the URL is the REST endpoint, not the Redis endpoint")
        await client.close()
        return 1

    ok = await client.self_test()  # PING + SET + GET + DELETE, logs each step
    await client.close()

    if ok:
        print("✓ HEALTHY — connect, read, write, and delete all succeeded.")
        print("  Your database is fine; if the bot still fails, its REDIS_URL differs from this one.")
        return 0
    print("✗ Connected but a read/write/delete was rejected "
          "(e.g. read-only replica or quota exceeded).")
    return 1


if __name__ == "__main__":
    import logging

    logging.basicConfig(level=logging.WARNING, format="  %(message)s")
    # Keep the internal stack trace out of this user-facing check; the verdict lines say enough.
    logging.getLogger("bot.database.redis_client").setLevel(logging.CRITICAL)
    raise SystemExit(asyncio.run(main()))
