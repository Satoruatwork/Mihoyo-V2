"""Local file-backed fallback store.

A tiny JSON-backed store mirroring the full ``UserStore`` interface so the bot
keeps working — logins persist, ``/myuid`` etc. answer — even when the primary
datastore is unreachable.

Durability caveat: this file lives on the local disk. On a container platform with an
ephemeral filesystem (e.g. Railway without a mounted volume) it survives restarts but not
redeploys. It is a resilience layer, not a replacement for a remote DB; mount a volume
at the data dir for durability, or use a hosted database.
"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Any

from bot.database.interfaces import DatabaseClient, UserStore
from bot.utils.logging import get_logger

logger = get_logger(__name__)


class LocalStore(UserStore, DatabaseClient):
    """JSON-file user store implementing the full ``UserStore`` + ``DatabaseClient``."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = asyncio.Lock()
        self._data: dict[str, Any] = self._load()

    def _load(self) -> dict[str, Any]:
        try:
            if self._path.exists():
                with self._path.open(encoding="utf-8") as fh:
                    data = json.load(fh)
                if isinstance(data, dict):
                    # Backwards compat: old file had {"users": {...}}
                    if "users" in data and isinstance(data["users"], dict) and "groups" not in data:
                        return {"users": data["users"], "groups": [], "private": [], "interactions": 0}
                    return {
                        "users": data.get("users", {}) if isinstance(data.get("users"), dict) else {},
                        "groups": data.get("groups", []) if isinstance(data.get("groups"), list) else [],
                        "private": data.get("private", []) if isinstance(data.get("private"), list) else [],
                        "interactions": data.get("interactions", 0) if isinstance(data.get("interactions"), int) else 0,
                    }
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Local store load failed (%s); starting empty", exc)
        return {"users": {}, "groups": [], "private": [], "interactions": 0}

    def _flush(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._path.with_suffix(".tmp")
            with tmp.open("w", encoding="utf-8") as fh:
                json.dump(self._data, fh, ensure_ascii=False)
            tmp.replace(self._path)  # atomic swap
        except OSError as exc:
            logger.warning("Local store flush failed: %s", exc)

    def _user(self, tid: int) -> dict[str, Any]:
        return self._data.setdefault("users", {}).setdefault(str(tid), {})

    # --- DatabaseClient -------------------------------------------------
    async def verify(self) -> bool:
        return True

    async def is_healthy(self) -> bool:
        return True

    async def close(self) -> None:
        return None

    # --- account / settings API (mirrors RedisStore) --------------------
    async def get_or_create(self, telegram_user_id: int, default_language: str = "en") -> dict[str, Any]:
        async with self._lock:
            user = self._user(telegram_user_id)
            if not user:
                user["language"] = default_language
                now = int(time.time())
                user["created_at"] = now
                user["last_seen"] = now
                self._flush()
            return dict(user)

    async def link_uid(self, telegram_user_id: int, uid: str, default_language: str = "en") -> None:
        async with self._lock:
            user = self._user(telegram_user_id)
            user["uid"] = str(uid)
            user.setdefault("language", default_language)
            user.setdefault("created_at", int(time.time()))
            user["last_seen"] = int(time.time())
            self._flush()

    async def unlink_uid(self, telegram_user_id: int) -> bool:
        async with self._lock:
            user = self._user(telegram_user_id)
            had = "uid" in user
            user.pop("uid", None)
            if had:
                self._flush()
            return had

    async def get_uid(self, telegram_user_id: int) -> str | None:
        async with self._lock:
            return self._user(telegram_user_id).get("uid")

    async def set_language(self, telegram_user_id: int, language: str, default_language: str = "en") -> None:
        async with self._lock:
            self._user(telegram_user_id)["language"] = language
            self._flush()

    async def get_language(self, telegram_user_id: int, default_language: str = "en") -> str:
        async with self._lock:
            return self._user(telegram_user_id).get("language", default_language)

    async def set_setting(self, telegram_user_id: int, key: str, value: str) -> None:
        async with self._lock:
            self._user(telegram_user_id).setdefault("settings", {})[key] = value
            self._flush()

    async def get_setting(self, telegram_user_id: int, key: str, default: str | None = None) -> str | None:
        async with self._lock:
            return self._user(telegram_user_id).get("settings", {}).get(key, default)

    async def get_all_settings(self, telegram_user_id: int) -> dict[str, str]:
        async with self._lock:
            return dict(self._user(telegram_user_id).get("settings", {}))

    # --- HoYoLAB session cookie (stored already-encrypted) ---------------
    async def set_hoyolab_cookie(self, telegram_user_id: int, token: str) -> None:
        async with self._lock:
            self._user(telegram_user_id)["hoyolab_cookie"] = token
            self._flush()

    async def get_hoyolab_cookie(self, telegram_user_id: int) -> str | None:
        async with self._lock:
            return self._user(telegram_user_id).get("hoyolab_cookie")

    async def clear_hoyolab_cookie(self, telegram_user_id: int) -> bool:
        async with self._lock:
            user = self._user(telegram_user_id)
            had = "hoyolab_cookie" in user
            user.pop("hoyolab_cookie", None)
            if had:
                self._flush()
            return had

    # --- registration / tracking ----------------------------------------
    async def register_interaction(self, telegram_user_id: int, chat_type: str | None) -> None:
        async with self._lock:
            user = self._user(telegram_user_id)
            now = int(time.time())
            user.setdefault("created_at", now)
            user["last_seen"] = now
            user["last_chat_type"] = chat_type or "private"
            if chat_type in (None, "private"):
                private: list = self._data.setdefault("private", [])
                if telegram_user_id not in private:
                    private.append(telegram_user_id)
            self._data["interactions"] = int(self._data.get("interactions", 0)) + 1
            self._flush()

    async def register_group(self, chat_id: int) -> None:
        async with self._lock:
            groups: list = self._data.setdefault("groups", [])
            if chat_id not in groups:
                groups.append(chat_id)
                self._flush()

    async def unregister_group(self, chat_id: int) -> None:
        async with self._lock:
            groups: list = self._data.get("groups", [])
            if chat_id in groups:
                groups.remove(chat_id)
                self._flush()

    # --- broadcast recipients -------------------------------------------
    async def all_users(self) -> list[int]:
        async with self._lock:
            return [int(k) for k in self._data.get("users", {}).keys() if str(k).lstrip("-").isdigit()]

    async def all_groups(self) -> list[int]:
        async with self._lock:
            return list(self._data.get("groups", []))

    async def discard_users(self, ids: list[int]) -> None:
        if not ids:
            return
        async with self._lock:
            ids_set = {str(i) for i in ids}
            users: dict = self._data.get("users", {})
            for k in list(users.keys()):
                if k in ids_set:
                    users.pop(k, None)
            private: list = self._data.get("private", [])
            self._data["private"] = [x for x in private if x not in ids]
            self._flush()

    async def discard_groups(self, ids: list[int]) -> None:
        if not ids:
            return
        async with self._lock:
            groups: list = self._data.get("groups", [])
            self._data["groups"] = [x for x in groups if x not in ids]
            self._flush()

    # --- statistics -----------------------------------------------------
    async def count_users(self) -> int:
        async with self._lock:
            return len(self._data.get("users", {}))

    async def count_private_chats(self) -> int:
        async with self._lock:
            return len(self._data.get("private", []))

    async def count_groups(self) -> int:
        async with self._lock:
            return len(self._data.get("groups", []))

    async def count_interactions(self) -> int:
        async with self._lock:
            return int(self._data.get("interactions", 0))
