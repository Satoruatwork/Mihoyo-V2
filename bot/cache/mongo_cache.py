"""MongoDB-backed JSON cache."""

from __future__ import annotations

import json
import time
from typing import Any

from bot.utils.logging import get_logger

logger = get_logger(__name__)


class MongoCache:
    """Namespaced JSON cache over a MongoDB database.

    Each entry is a document ``{_id, namespace, key, value, expires_at}``
    with a TTL index hint (we check ``expires_at`` on read; MongoDB TTL
    indexes are optional and created best-effort).
    """

    def __init__(self, database, ttl: int = 300) -> None:
        self._db = database
        self._ttl = ttl
        self._ready = False

    @property
    def _col(self):
        return self._db["cache_entries"]

    async def _ensure_index(self) -> None:
        if self._ready or self._db is None:
            return
        try:
            # expireAfterSeconds requires ``expires_at`` to be a Date; we instead
            # manage expiry in application code and just ensure a unique index.
            await self._col.create_index([("namespace", 1), ("key", 1)], unique=True, background=True)
            self._ready = True
        except Exception as exc:  # noqa: BLE001
            logger.debug("mongo cache index create skipped: %s", exc)

    def _cache_id(self, namespace: str, key: str) -> str:
        return f"{namespace}:{key}"

    async def get_json(self, namespace: str, key: str) -> Any | None:
        await self._ensure_index()
        if self._db is None:
            return None
        try:
            doc = await self._col.find_one({"namespace": namespace, "key": key})
        except Exception as exc:  # noqa: BLE001
            logger.debug("mongo cache get failed (%s/%s): %s", namespace, key, exc)
            return None
        if doc is None:
            return None
        if time.time() > float(doc.get("expires_at", 0)):
            try:
                await self._col.delete_one({"namespace": namespace, "key": key})
            except Exception:  # noqa: BLE001
                pass
            return None
        raw = doc.get("value")
        if isinstance(raw, str):
            try:
                return json.loads(raw)
            except (ValueError, TypeError):
                return None
        return raw

    async def set_json(self, namespace: str, key: str, value: Any, ttl: int | None = None) -> None:
        await self._ensure_index()
        if self._db is None:
            return
        try:
            # Store as JSON string for portability across drivers.
            payload = json.dumps(value, ensure_ascii=False)
        except (TypeError, ValueError) as exc:
            logger.debug("cache serialize failed (%s/%s): %s", namespace, key, exc)
            return
        expires_at = time.time() + (ttl if ttl is not None else self._ttl)
        try:
            await self._col.update_one(
                {"namespace": namespace, "key": key},
                {"$set": {"value": payload, "expires_at": expires_at, "namespace": namespace, "key": key}},
                upsert=True,
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("mongo cache set failed (%s/%s): %s", namespace, key, exc)

    async def invalidate(self, namespace: str, key: str) -> None:
        if self._db is None:
            return
        try:
            await self._col.delete_one({"namespace": namespace, "key": key})
        except Exception:  # noqa: BLE001
            pass
