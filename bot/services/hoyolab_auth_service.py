"""Per-user HoYoLAB session management.

Validates a user-supplied cookie against HoYoLAB, stores it **encrypted** against the
Telegram user, and hands the decrypted cookie back when a redemption runs. This is the shared
backend for every account-authenticated command (today ``/redeem``; future check-in / notes /
etc. reuse ``get_cookie``).

Nothing here talks to Telegram. Cookies are only ever persisted through :class:`CookieCipher`,
so a missing/disabled cipher means logins are refused rather than stored in the clear.
"""

from __future__ import annotations

from typing import Callable

from bot.api.hoyolab_client import HoyolabRedeemer
from bot.database.store import RedisStore
from bot.services.redemption_service import RedeemResult, RedeemStatus
from bot.utils.crypto import CookieCipher
from bot.utils.logging import get_logger

logger = get_logger(__name__)

# Factory so tests can inject a fake redeemer instead of the genshin.py-backed one.
RedeemerFactory = Callable[[str], HoyolabRedeemer]


class HoyolabAuthService:
    def __init__(
        self,
        users: RedisStore,
        cipher: CookieCipher,
        redeemer_factory: RedeemerFactory | None = None,
    ) -> None:
        self._users = users
        self._cipher = cipher
        self._redeemer_factory = redeemer_factory or (lambda cookie: HoyolabRedeemer(cookie))

    @property
    def enabled(self) -> bool:
        """True when session storage is configured (HOYOLAB_SECRET set)."""
        return self._cipher.available

    async def login(self, telegram_user_id: int, cookie: str) -> RedeemResult:
        """Validate ``cookie`` and, on success, store it encrypted. Returns the validation
        result (SUCCESS carries the resolved uid/nickname/region; otherwise a failure status).
        """
        cookie = (cookie or "").strip()
        if not cookie:
            return RedeemResult(status=RedeemStatus.AUTH_FAILED, code="", detail="empty cookie")

        result = await self._redeemer_factory(cookie).validate()
        if result.status is RedeemStatus.SUCCESS:
            await self._users.set_hoyolab_cookie(telegram_user_id, self._cipher.encrypt(cookie))
            logger.info("HoYoLAB login stored for user=%s (uid=%s)", telegram_user_id, result.uid)
        return result

    async def logout(self, telegram_user_id: int) -> bool:
        """Remove the stored session. Returns True if one was present."""
        return await self._users.clear_hoyolab_cookie(telegram_user_id)

    async def get_cookie(self, telegram_user_id: int) -> str | None:
        """Return the user's decrypted cookie, or None if not logged in / unreadable."""
        token = await self._users.get_hoyolab_cookie(telegram_user_id)
        return self._cipher.decrypt(token) if token else None

    async def is_logged_in(self, telegram_user_id: int) -> bool:
        return await self._users.get_hoyolab_cookie(telegram_user_id) is not None
