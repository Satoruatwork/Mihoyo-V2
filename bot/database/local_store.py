"""Local file-backed fallback store.

A tiny JSON-backed store mirroring the account-critical subset of :class:`RedisStore` (linked
UID, language, per-user settings). It exists so the bot keeps working — logins persist,
``/myuid`` etc. answer — even when the primary Redis datastore is unreachable.

Durability caveat: this file lives on the local disk. On a container platform with an
ephemeral filesystem (e.g. Railway without a mounted volume) it survives restarts but not
redeploys. It is a resilience layer, not a replacement for Redis; fix Redis (or mount a
volume at the data dir) for durable, multi-instance persistence.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from bot.utils.logging import get_logger

logger = get_logger(__name__)


class LocalStore:
    """JSON-file user store with the account/settings methods used by the account flow."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = asyncio.Lock()
        self._data: dict[str, dict[str, Any]] = self._load()

    def _load(self) -> dict[str, dict[str, Any]]:
        try:
            if self._path.exists():
                with self._path.open(encoding="utf-8") as fh:
                    data = json.load(fh)
                return data.get("users", {}) if isinstance(data, dict) else {}
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Local store load failed (%s); starting empty", exc)
        return {}

    def _flush(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._path.with_suffix(".tmp")
            with tmp.open("w", encoding="utf-8") as fh:
                json.dump({"users": self._data}, fh, ensure_ascii=False)
            tmp.replace(self._path)  # atomic swap
        except OSError as exc:
            logger.warning("Local store flush failed: %s", exc)

    def _user(self, tid: int) -> dict[str, Any]:
        return self._data.setdefault(str(tid), {})

    # --- account / settings API (mirrors RedisStore) ---
    async def get_or_create(self, telegram_user_id: int, default_language: str = "en") -> dict[str, Any]:
        async with self._lock:
            user = self._user(telegram_user_id)
            if not user:
                user["language"] = default_language
                self._flush()
            return dict(user)

    async def link_uid(self, telegram_user_id: int, uid: str, default_language: str = "en") -> None:
        async with self._lock:
            user = self._user(telegram_user_id)
            user["uid"] = str(uid)
            user.setdefault("language", default_language)
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

    # --- HoYoLAB session cookie (stored already-encrypted) ---
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
