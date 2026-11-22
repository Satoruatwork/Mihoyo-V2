#!/usr/bin/env python3
"""Check database connectivity for any configured backend.

Tells you whether your database is reachable/writable, independent of the bot.

Usage:
    # Auto-detect from environment (.env or env vars):
    python scripts/check_db.py

    # Explicit URL + backend:
    DATABASE_BACKEND=mongodb MONGODB_URL='mongodb+srv://...' python scripts/check_db.py
    DATABASE_BACKEND=postgres POSTGRES_URL='postgresql://...' python scripts/check_db.py
    REDIS_URL='rediss://...' python scripts/check_db.py  # backwards compat

Exit code 0 = healthy; 1 = problem found.
"""

from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bot.config import get_settings  # noqa: E402
from bot.database.factory import build_database, describe_backend, validate_backend_config  # noqa: E402


async def main() -> int:
    # Allow overriding via CLI arg (single URL interpreted as redis for backwards compat)
    if len(sys.argv) > 1 and "://" in sys.argv[1]:
        # If bare URL passed, inject as REDIS_URL so old `python check_redis.py <url>` still works
        os.environ.setdefault("REDIS_URL", sys.argv[1])

    # Force re-read of env after potential CLI injection
    get_settings.cache_clear()
    settings = get_settings()

    print(f"Backend: {settings.resolved_backend}")
    print(f"Config : {describe_backend(settings)}")

    ok, message = validate_backend_config(settings)
    if not ok:
        print(f"✗ Config invalid: {message}")
        if settings.resolved_backend == "redis":
            print("  → Fix REDIS_URL. Use the Upstash 'Redis' URL (rediss://default:<pw>@<host>:6379),")
            print("    NOT the 'REST API' URL (https://...).")
        elif settings.resolved_backend == "mongodb":
            print("  → Fix MONGODB_URL (mongodb://... or mongodb+srv://...) and MONGODB_DB.")
        elif settings.resolved_backend == "postgres":
            print("  → Fix POSTGRES_URL / DATABASE_URL (postgresql://user:pw@host/db).")
            print("    For Supabase: Dashboard → Database → Connection string → URI tab.")
        return 1
    print("✓ URL format looks valid.")

    try:
        store, client, _cache = build_database(settings)
    except Exception as exc:
        print(f"✗ Failed to build database client: {exc}")
        return 1

    if not await client.verify():
        print("✗ Could not connect / ping failed.")
        print("  Likely causes: wrong host/password, DB paused/deleted, firewall, or network.")
        try:
            await client.close()
        except Exception:
            pass
        return 1

    ok = await client.self_test()
    try:
        await client.close()
    except Exception:
        pass

    if ok:
        print("✓ HEALTHY — connect, read, write, and delete all succeeded.")
        return 0
    print("✗ Connected but a read/write/delete was rejected (e.g. read-only or quota exceeded).")
    return 1


if __name__ == "__main__":
    import logging

    logging.basicConfig(level=logging.WARNING, format="  %(message)s")
    raise SystemExit(asyncio.run(main()))
