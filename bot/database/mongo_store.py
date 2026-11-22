"""MongoDB-backed persistent store — implements ``UserStore`` + ``DatabaseClient``."""

from __future__ import annotations

import time
from typing import Any

from bot.database.circuit import CircuitBreaker
from bot.database.interfaces import DatabaseClient, UserStore
from bot.utils.errors import DatastoreUnavailable
from bot.utils.logging import get_logger

logger = get_logger(__name__)


def _now() -> int:
    return int(time.time())


# ---------------------------------------------------------------------------
# MongoClient — owns the Motor connection
# ---------------------------------------------------------------------------
class MongoClient(DatabaseClient):
    """Owns a ``motor.motor_asyncio.AsyncIOMotorClient``."""

    def __init__(
        self,
        url: str,
        db_name: str = "mihoyo",
        *,
        connect_timeout_ms: int = 5000,
        server_selection_timeout_ms: int = 5000,
    ) -> None:
        self._url = url
        self._db_name = db_name
        self._client = None  # lazy
        self._db = None
        self._connect_timeout_ms = connect_timeout_ms
        self._server_selection_timeout_ms = server_selection_timeout_ms
        logger.info("MongoDB client configured for db=%s (%s)", db_name, _mask_url(url))

    def _ensure_client(self):
        if self._client is None:
            try:
                from motor.motor_asyncio import AsyncIOMotorClient
            except ImportError as exc:
                raise RuntimeError(
                    "motor is required for MongoDB backend. Install with: pip install motor"
                ) from exc
            self._client = AsyncIOMotorClient(
                self._url,
                serverSelectionTimeoutMS=self._server_selection_timeout_ms,
                connectTimeoutMS=self._connect_timeout_ms,
            )
            self._db = self._client[self._db_name]
        return self._client

    @property
    def db(self):
        self._ensure_client()
        return self._db

    @property
    def client(self):  # for cache access, mirrors RedisClient.client
        self._ensure_client()
        return self._client

    async def verify(self) -> bool:
        try:
            self._ensure_client()
            await self._client.admin.command("ping")
            logger.info("MongoDB connection verified (ping)")
            return True
        except Exception as exc:  # noqa: BLE001
            logger.error("MongoDB verify failed (%s): %s", type(exc).__name__, exc, exc_info=True)
            return False

    async def is_healthy(self) -> bool:
        try:
            self._ensure_client()
            await self._client.admin.command("ping")
            return True
        except Exception:  # noqa: BLE001
            return False

    async def self_test(self) -> bool:
        if not await self.verify():
            return False
        try:
            col = self.db["_diag_selftest"]
            await col.insert_one({"_id": "probe", "v": "ok"})
            doc = await col.find_one({"_id": "probe"})
            await col.delete_one({"_id": "probe"})
            ok = doc is not None and doc.get("v") == "ok"
            logger.info("MongoDB self-test -> %s", "PASS" if ok else "FAIL")
            return ok
        except Exception as exc:  # noqa: BLE001
            logger.error("MongoDB self-test FAILED (%s): %s", type(exc).__name__, exc, exc_info=True)
            return False

    async def close(self) -> None:
        if self._client is not None:
            try:
                self._client.close()
            except Exception:  # noqa: BLE001
                pass
            self._client = None
            self._db = None


def _mask_url(url: str) -> str:
    if not url:
        return "<empty>"
    try:
        from urllib.parse import urlsplit

        parts = urlsplit(url)
        host = parts.hostname or "?"
        port = f":{parts.port}" if parts.port else ""
        user = parts.username or ""
        auth = f"{user}:***@" if (user or parts.password) else ""
        return f"{parts.scheme}://{auth}{host}{port}"
    except Exception:
        return "<unparseable>"


def mask_mongo_url(url: str) -> str:
    return _mask_url(url)


def validate_mongo_url(url: str) -> tuple[bool, str]:
    if not url or not url.strip():
        return False, "MONGODB_URL is empty."
    lowered = url.strip().lower()
    if not (lowered.startswith("mongodb://") or lowered.startswith("mongodb+srv://")):
        return False, "MONGODB_URL must start with mongodb:// or mongodb+srv://"
    return True, "ok"


# ---------------------------------------------------------------------------
# MongoStore — UserStore over MongoDB
# ---------------------------------------------------------------------------
class MongoStore(UserStore):
    """Persistent store backed by MongoDB (Motor)."""

    def __init__(
        self,
        database,  # AsyncIOMotorDatabase
        fallback=None,  # LocalStore | None
        breaker_cooldown: float = 30.0,
    ) -> None:
        self._db = database
        self._users = database["users"]
        self._groups = database["groups"]
        self._counters = database["counters"]
        self._fallback = fallback
        self._breaker = CircuitBreaker(breaker_cooldown)

    def _skip_db(self) -> bool:
        return self._fallback is not None and self._breaker.is_open()

    # Helpers --------------------------------------------------------------
    def _tid_filter(self, tid: int) -> dict:
        # Store Telegram IDs as ints for query consistency; Mongo handles int64.
        return {"_id": tid}

    # Users ---------------------------------------------------------------
    async def get_or_create(self, telegram_user_id: int, default_language: str = "en") -> dict[str, Any]:
        if self._skip_db():
            return await self._fallback.get_or_create(telegram_user_id, default_language)
        try:
            doc = await self._users.find_one(self._tid_filter(telegram_user_id))
            if not doc:
                now = _now()
                new_doc: dict[str, Any] = {
                    "_id": telegram_user_id,
                    "language": default_language,
                    "created_at": now,
                    "last_seen": now,
                    "settings": {},
                }
                await self._users.insert_one(new_doc)
                self._breaker.record_success()
                return {"language": default_language, "created_at": now, "last_seen": now}
            self._breaker.record_success()
            return doc  # type: ignore[return-value]
        except Exception as exc:  # noqa: BLE001
            self._breaker.record_failure()
            logger.warning("mongo get_or_create failed for %s: %s", telegram_user_id, exc)
            if self._fallback is not None:
                return await self._fallback.get_or_create(telegram_user_id, default_language)
            return {}

    async def link_uid(self, telegram_user_id: int, uid: str, default_language: str = "en") -> None:
        if self._skip_db():
            await self._fallback.link_uid(telegram_user_id, uid, default_language)
            return
        try:
            now = _now()
            await self._users.update_one(
                self._tid_filter(telegram_user_id),
                {
                    "$set": {"uid": str(uid), "last_seen": now},
                    "$setOnInsert": {
                        "language": default_language,
                        "created_at": now,
                        "settings": {},
                    },
                },
                upsert=True,
            )
            self._breaker.record_success()
        except Exception as exc:  # noqa: BLE001
            self._breaker.record_failure()
            logger.error("mongo link_uid failed for %s: %s", telegram_user_id, exc)
            if self._fallback is not None:
                logger.warning("link_uid falling back to local store for %s", telegram_user_id)
                await self._fallback.link_uid(telegram_user_id, uid, default_language)
                return
            raise DatastoreUnavailable(str(exc)) from exc

    async def unlink_uid(self, telegram_user_id: int) -> bool:
        if self._skip_db():
            return await self._fallback.unlink_uid(telegram_user_id)
        try:
            doc = await self._users.find_one(self._tid_filter(telegram_user_id), {"uid": 1})
            had = doc is not None and "uid" in doc
            if had:
                await self._users.update_one(self._tid_filter(telegram_user_id), {"$unset": {"uid": ""}})
            self._breaker.record_success()
            return bool(had)
        except Exception as exc:  # noqa: BLE001
            self._breaker.record_failure()
            logger.error("mongo unlink_uid failed for %s: %s", telegram_user_id, exc)
            if self._fallback is not None:
                return await self._fallback.unlink_uid(telegram_user_id)
            return False

    async def get_uid(self, telegram_user_id: int) -> str | None:
        if self._skip_db():
            return await self._fallback.get_uid(telegram_user_id)
        try:
            doc = await self._users.find_one(self._tid_filter(telegram_user_id), {"uid": 1})
            self._breaker.record_success()
            return doc.get("uid") if doc else None
        except Exception as exc:  # noqa: BLE001
            self._breaker.record_failure()
            logger.warning("mongo get_uid failed for %s: %s", telegram_user_id, exc)
            if self._fallback is not None:
                return await self._fallback.get_uid(telegram_user_id)
            return None

    # Language ------------------------------------------------------------
    async def set_language(self, telegram_user_id: int, language: str, default_language: str = "en") -> None:
        if self._skip_db():
            await self._fallback.set_language(telegram_user_id, language, default_language)
            return
        try:
            await self._users.update_one(
                self._tid_filter(telegram_user_id),
                {"$set": {"language": language}, "$setOnInsert": {"created_at": _now(), "settings": {}}},
                upsert=True,
            )
            self._breaker.record_success()
        except Exception as exc:  # noqa: BLE001
            self._breaker.record_failure()
            logger.error("mongo set_language failed for %s: %s", telegram_user_id, exc)
            if self._fallback is not None:
                await self._fallback.set_language(telegram_user_id, language, default_language)

    async def get_language(self, telegram_user_id: int, default_language: str = "en") -> str:
        if self._skip_db():
            return await self._fallback.get_language(telegram_user_id, default_language)
        try:
            doc = await self._users.find_one(self._tid_filter(telegram_user_id), {"language": 1})
            self._breaker.record_success()
            return doc.get("language") if doc and doc.get("language") else default_language
        except Exception as exc:  # noqa: BLE001
            self._breaker.record_failure()
            logger.warning("mongo get_language failed for %s: %s", telegram_user_id, exc)
            if self._fallback is not None:
                return await self._fallback.get_language(telegram_user_id, default_language)
            return default_language

    # Settings ------------------------------------------------------------
    async def set_setting(self, telegram_user_id: int, key: str, value: str) -> None:
        if self._skip_db():
            await self._fallback.set_setting(telegram_user_id, key, value)
            return
        try:
            # Use fetch-merge to stay compatible with mongomock which has issues
            # with dotted $set on nested dicts.
            doc = await self._users.find_one(self._tid_filter(telegram_user_id), {"settings": 1})
            if doc is not None:
                settings = dict(doc.get("settings") or {})
                settings[key] = value
                await self._users.update_one(
                    self._tid_filter(telegram_user_id),
                    {"$set": {"settings": settings}},
                )
            else:
                await self._users.update_one(
                    self._tid_filter(telegram_user_id),
                    {
                        "$set": {"settings": {key: value}},
                        "$setOnInsert": {"created_at": _now(), "language": "en"},
                    },
                    upsert=True,
                )
            self._breaker.record_success()
        except Exception as exc:  # noqa: BLE001
            self._breaker.record_failure()
            logger.error("mongo set_setting failed for %s: %s", telegram_user_id, exc)
            if self._fallback is not None:
                await self._fallback.set_setting(telegram_user_id, key, value)

    async def get_setting(self, telegram_user_id: int, key: str, default: str | None = None) -> str | None:
        if self._skip_db():
            return await self._fallback.get_setting(telegram_user_id, key, default)
        try:
            doc = await self._users.find_one(self._tid_filter(telegram_user_id), {"settings": 1})
            self._breaker.record_success()
            if doc and isinstance(doc.get("settings"), dict):
                return doc["settings"].get(key, default)
            return default
        except Exception as exc:  # noqa: BLE001
            self._breaker.record_failure()
            logger.warning("mongo get_setting failed for %s: %s", telegram_user_id, exc)
            if self._fallback is not None:
                return await self._fallback.get_setting(telegram_user_id, key, default)
            return default

    async def get_all_settings(self, telegram_user_id: int) -> dict[str, str]:
        if self._skip_db():
            return await self._fallback.get_all_settings(telegram_user_id)
        try:
            doc = await self._users.find_one(self._tid_filter(telegram_user_id), {"settings": 1})
            self._breaker.record_success()
            if doc and isinstance(doc.get("settings"), dict):
                return dict(doc["settings"])
            return {}
        except Exception as exc:  # noqa: BLE001
            self._breaker.record_failure()
            logger.warning("mongo get_all_settings failed for %s: %s", telegram_user_id, exc)
            if self._fallback is not None:
                return await self._fallback.get_all_settings(telegram_user_id)
            return {}

    # HoYoLAB cookie ------------------------------------------------------
    async def set_hoyolab_cookie(self, telegram_user_id: int, token: str) -> None:
        if self._skip_db():
            await self._fallback.set_hoyolab_cookie(telegram_user_id, token)
            return
        try:
            await self._users.update_one(
                self._tid_filter(telegram_user_id),
                {"$set": {"hoyolab_cookie": token}, "$setOnInsert": {"created_at": _now(), "settings": {}}},
                upsert=True,
            )
            self._breaker.record_success()
        except Exception as exc:  # noqa: BLE001
            self._breaker.record_failure()
            logger.error("mongo set_hoyolab_cookie failed for %s: %s", telegram_user_id, exc)
            if self._fallback is not None:
                await self._fallback.set_hoyolab_cookie(telegram_user_id, token)

    async def get_hoyolab_cookie(self, telegram_user_id: int) -> str | None:
        if self._skip_db():
            return await self._fallback.get_hoyolab_cookie(telegram_user_id)
        try:
            doc = await self._users.find_one(self._tid_filter(telegram_user_id), {"hoyolab_cookie": 1})
            self._breaker.record_success()
            return doc.get("hoyolab_cookie") if doc else None
        except Exception as exc:  # noqa: BLE001
            self._breaker.record_failure()
            logger.warning("mongo get_hoyolab_cookie failed for %s: %s", telegram_user_id, exc)
            if self._fallback is not None:
                return await self._fallback.get_hoyolab_cookie(telegram_user_id)
            return None

    async def clear_hoyolab_cookie(self, telegram_user_id: int) -> bool:
        if self._skip_db():
            return await self._fallback.clear_hoyolab_cookie(telegram_user_id)
        try:
            doc = await self._users.find_one(self._tid_filter(telegram_user_id), {"hoyolab_cookie": 1})
            had = doc is not None and "hoyolab_cookie" in doc
            if had:
                await self._users.update_one(self._tid_filter(telegram_user_id), {"$unset": {"hoyolab_cookie": ""}})
            self._breaker.record_success()
            return bool(had)
        except Exception as exc:  # noqa: BLE001
            self._breaker.record_failure()
            logger.error("mongo clear_hoyolab_cookie failed for %s: %s", telegram_user_id, exc)
            if self._fallback is not None:
                return await self._fallback.clear_hoyolab_cookie(telegram_user_id)
            return False

    # Registration & sessions --------------------------------------------
    async def register_interaction(self, telegram_user_id: int, chat_type: str | None) -> None:
        if self._breaker.is_open():
            return
        try:
            now = _now()
            update: dict[str, Any] = {
                "$set": {"last_seen": now, "last_chat_type": chat_type or "private"},
                "$setOnInsert": {"created_at": now, "language": "en", "settings": {}},
            }
            if chat_type in (None, "private"):
                update["$set"]["is_private"] = True
            await self._users.update_one(self._tid_filter(telegram_user_id), update, upsert=True)
            await self._counters.update_one(
                {"_id": "interactions"}, {"$inc": {"value": 1}}, upsert=True
            )
            self._breaker.record_success()
        except Exception as exc:  # noqa: BLE001
            self._breaker.record_failure()
            logger.debug("mongo register_interaction failed for %s: %s", telegram_user_id, exc)

    async def register_group(self, chat_id: int) -> None:
        try:
            await self._groups.update_one({"_id": chat_id}, {"$set": {"_id": chat_id}}, upsert=True)
        except Exception as exc:  # noqa: BLE001
            logger.debug("mongo register_group failed for %s: %s", chat_id, exc)

    async def unregister_group(self, chat_id: int) -> None:
        try:
            await self._groups.delete_one({"_id": chat_id})
        except Exception as exc:  # noqa: BLE001
            logger.debug("mongo unregister_group failed for %s: %s", chat_id, exc)

    # Broadcast recipients -----------------------------------------------
    async def all_users(self) -> list[int]:
        try:
            ids: list[int] = []
            async for doc in self._users.find({}, {"_id": 1}):
                try:
                    ids.append(int(doc["_id"]))
                except (TypeError, ValueError, KeyError):
                    continue
            return ids
        except Exception as exc:  # noqa: BLE001
            logger.warning("mongo all_users failed: %s", exc)
            return []

    async def all_groups(self) -> list[int]:
        try:
            ids: list[int] = []
            async for doc in self._groups.find({}, {"_id": 1}):
                try:
                    ids.append(int(doc["_id"]))
                except (TypeError, ValueError, KeyError):
                    continue
            return ids
        except Exception as exc:  # noqa: BLE001
            logger.warning("mongo all_groups failed: %s", exc)
            return []

    async def discard_users(self, ids: list[int]) -> None:
        if not ids:
            return
        try:
            await self._users.delete_many({"_id": {"$in": ids}})
        except Exception as exc:  # noqa: BLE001
            logger.debug("mongo discard_users failed: %s", exc)

    async def discard_groups(self, ids: list[int]) -> None:
        if not ids:
            return
        try:
            await self._groups.delete_many({"_id": {"$in": ids}})
        except Exception as exc:  # noqa: BLE001
            logger.debug("mongo discard_groups failed: %s", exc)

    # Statistics ---------------------------------------------------------
    async def count_users(self) -> int:
        try:
            return await self._users.count_documents({})
        except Exception:
            return 0

    async def count_private_chats(self) -> int:
        try:
            return await self._users.count_documents({"is_private": True})
        except Exception:
            return 0

    async def count_groups(self) -> int:
        try:
            return await self._groups.count_documents({})
        except Exception:
            return 0

    async def count_interactions(self) -> int:
        try:
            doc = await self._counters.find_one({"_id": "interactions"})
            return int(doc["value"]) if doc and "value" in doc else 0
        except Exception:
            return 0
