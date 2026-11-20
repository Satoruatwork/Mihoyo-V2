"""Account linking business logic: validate UID, link/unlink, resolve stored UID."""

from __future__ import annotations

import re

from bot.database.store import RedisStore
from bot.utils.errors import AccountNotLinked, InvalidUID

# Genshin UID format (as of 2026): 9 or 10 numeric digits. The server region is encoded
# in the leading prefix — a single digit on 9-digit UIDs, two digits on 10-digit UIDs.
#
#   6 / 16 -> America
#   7 / 17 -> Europe
#   8 / 18 -> Asia
#   9 / 19 -> Taiwan / Hong Kong / Macau
#
# To support a new server later, add its prefix(es) here — validation is data-driven,
# never hardcoded to a fixed length.
_REGION_BY_PREFIX: dict[str, str] = {
    "6": "America", "16": "America",
    "7": "Europe", "17": "Europe",
    "8": "Asia", "18": "Asia",
    "9": "TW/HK/MO", "19": "TW/HK/MO",
}

# 9 or 10 ASCII digits, nothing else. (Uses [0-9] rather than \d to exclude unicode digits.)
_UID_RE = re.compile(r"^[0-9]{9,10}$")


def uid_region(uid: str) -> str | None:
    """Return the server region for a UID, or ``None`` if the prefix is unrecognized.

    9-digit UIDs are keyed by their first digit; 10-digit UIDs by their first two digits.
    """
    if len(uid) == 9:
        return _REGION_BY_PREFIX.get(uid[0])
    if len(uid) == 10:
        return _REGION_BY_PREFIX.get(uid[:2])
    return None


def validate_uid(raw: str) -> str:
    """Validate and normalize a Genshin UID.

    Rules (2026 format):
      * 9 or 10 digits — anything shorter or longer is rejected.
      * numeric only — any non-digit character is rejected.
      * the server prefix must be recognized (see :data:`_REGION_BY_PREFIX`).

    Returns the normalized UID string. Raises :class:`InvalidUID` if invalid.
    """
    uid = (raw or "").strip()
    if not _UID_RE.match(uid):
        raise InvalidUID(f"UID must be 9-10 numeric digits: {raw!r}")
    if uid_region(uid) is None:
        raise InvalidUID(f"Unrecognized Genshin server prefix: {raw!r}")
    return uid


class AccountService:
    """Links a Telegram user to a Genshin UID (one-time), stored in the database."""

    def __init__(self, users: RedisStore, default_language: str = "en") -> None:
        self._users = users
        self._default_language = default_language

    async def link(self, telegram_user_id: int, raw_uid: str) -> tuple[str, bool]:
        """Link a UID. Returns (uid, was_relink).

        ``was_relink`` is True if the user already had a (different) UID linked.
        """
        uid = validate_uid(raw_uid)
        previous = await self._users.get_uid(telegram_user_id)
        await self._users.link_uid(telegram_user_id, uid, self._default_language)
        return uid, previous is not None and previous != uid

    async def unlink(self, telegram_user_id: int) -> bool:
        """Unlink the user's UID. Returns True if a UID was present."""
        return await self._users.unlink_uid(telegram_user_id)

    async def get_uid(self, telegram_user_id: int) -> str | None:
        return await self._users.get_uid(telegram_user_id)

    async def require_uid(self, telegram_user_id: int) -> str:
        """Return the linked UID or raise :class:`AccountNotLinked`."""
        uid = await self._users.get_uid(telegram_user_id)
        if not uid:
            raise AccountNotLinked()
        return uid
