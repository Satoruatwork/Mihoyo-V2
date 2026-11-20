"""HoYoLAB redemption backend built on ``genshin.py``.

Claims a gift code on the bot's configured HoYoLAB account and maps the library's result /
errors onto our framework-agnostic :class:`~bot.services.redemption_service.RedeemResult`.
The whole thing happens server-side — no link, no button, no UID prompt.

``genshin`` is imported lazily so the rest of the bot (and the test suite's non-redeem paths)
never depends on it being importable at module load.
"""

from __future__ import annotations

from typing import Any

from bot.services.account_service import uid_region
from bot.services.redemption_service import RedeemResult, RedeemStatus
from bot.utils.logging import get_logger

logger = get_logger(__name__)

# HoYoverse retcode -> our status. Keyed by retcode because several distinct outcomes share
# one genshin.py class (e.g. -2001 "expired" and -2003 "malformed" are both RedemptionInvalid).
_RETCODE_STATUS: dict[int, RedeemStatus] = {
    -2001: RedeemStatus.EXPIRED,           # code has expired
    -2006: RedeemStatus.EXPIRED,           # reached max usage limit (no longer claimable)
    -2003: RedeemStatus.INVALID,           # incorrectly formatted
    -2004: RedeemStatus.INVALID,           # invalid
    -2014: RedeemStatus.INVALID,           # not activated
    -2008: RedeemStatus.WRONG_REGION,      # region locked
    -2011: RedeemStatus.LEVEL_TOO_LOW,     # AR too low
    -2021: RedeemStatus.LEVEL_TOO_LOW,     # AR too low
    -2016: RedeemStatus.COOLDOWN,          # redemption on cooldown
    -2017: RedeemStatus.ALREADY_REDEEMED,  # already claimed
    -2018: RedeemStatus.ALREADY_REDEEMED,  # already claimed
    -100: RedeemStatus.AUTH_FAILED,        # invalid cookies
    -1071: RedeemStatus.AUTH_FAILED,       # invalid cookies (login expired)
    10001: RedeemStatus.AUTH_FAILED,       # invalid cookies
}


class HoyolabRedeemer:
    """Redeems codes on a single configured HoYoLAB account via ``genshin.py``.

    The account's UID / nickname are fetched once (best-effort) and cached so the success
    card can show whose account the code landed on. All network work is confined here.
    """

    def __init__(self, cookie: str) -> None:
        self._cookie = (cookie or "").strip()
        self._client: Any = None
        self._account: tuple[str | None, str | None] | None = None

    # -- client lifecycle --------------------------------------------------
    def _build_client(self) -> Any:
        import genshin  # lazy: only needed when actually redeeming

        client = genshin.Client(game=genshin.Game.GENSHIN)
        client.set_cookies(self._cookie)
        return client

    async def _get_client(self) -> Any:
        if self._client is None:
            self._client = self._build_client()
        return self._client

    async def _account_info(self, client: Any) -> tuple[str | None, str | None]:
        """Return (uid, nickname) for the configured account, cached. Best-effort → (None, None)."""
        if self._account is not None:
            return self._account
        try:
            accounts = await client.get_game_accounts()
            account = next((a for a in accounts if str(getattr(a, "uid", "") or "").strip()), None)
            if account is not None:
                self._account = (str(account.uid), getattr(account, "nickname", None) or None)
                return self._account
        except Exception as exc:  # noqa: BLE001 - enrichment is optional
            logger.debug("HoYoLAB account info fetch failed: %s", exc)
        return (None, None)

    # -- login validation --------------------------------------------------
    async def validate(self) -> RedeemResult:
        """Check the cookie authenticates and resolve the account it belongs to.

        Returns ``SUCCESS`` with uid/nickname/region when the session is valid, else
        ``AUTH_FAILED`` (or ``SERVER_ERROR`` if the library is missing). Used by the login
        flow to verify a cookie *before* storing it. Never raises.
        """
        if not self._cookie:
            return RedeemResult(status=RedeemStatus.AUTH_FAILED, code="", detail="empty cookie")
        try:
            import genshin  # noqa: F401
        except ImportError:
            return RedeemResult(status=RedeemStatus.SERVER_ERROR, code="", detail="genshin.py not installed")
        try:
            client = await self._get_client()
        except Exception as exc:  # noqa: BLE001
            return RedeemResult(status=RedeemStatus.AUTH_FAILED, code="", detail=str(exc))

        uid, nickname = await self._account_info(client)
        if not uid:
            return RedeemResult(status=RedeemStatus.AUTH_FAILED, code="", detail="no game account / invalid cookie")
        return RedeemResult(
            status=RedeemStatus.SUCCESS, code="", uid=uid, nickname=nickname, region=uid_region(uid)
        )

    # -- redemption --------------------------------------------------------
    async def redeem(self, code: str) -> RedeemResult:
        if not self._cookie:
            return RedeemResult(status=RedeemStatus.AUTH_FAILED, code=code, detail="cookie not configured")

        try:
            import genshin  # noqa: F401 - availability check before building the client
        except ImportError:
            return RedeemResult(status=RedeemStatus.SERVER_ERROR, code=code, detail="genshin.py not installed")

        try:
            client = await self._get_client()
        except Exception as exc:  # noqa: BLE001 - malformed cookie / client init failure
            logger.warning("HoYoLAB client init failed: %s", exc)
            return RedeemResult(status=RedeemStatus.AUTH_FAILED, code=code, detail=str(exc))

        uid, nickname = await self._account_info(client)
        region = uid_region(uid) if uid else None

        try:
            import genshin

            await client.redeem_code(code, game=genshin.Game.GENSHIN)
        except Exception as exc:  # noqa: BLE001 - classified below
            return self.map_exception(exc, code, uid=uid, nickname=nickname, region=region)

        return RedeemResult(
            status=RedeemStatus.SUCCESS, code=code, uid=uid, nickname=nickname, region=region
        )

    # -- error mapping (pure; unit-tested without the network) -------------
    @staticmethod
    def map_exception(
        exc: Exception, code: str, *,
        uid: str | None = None, nickname: str | None = None, region: str | None = None,
    ) -> RedeemResult:
        """Translate a ``genshin.py`` exception into a :class:`RedeemResult`."""
        import genshin.errors as ge

        retcode = getattr(exc, "retcode", None)
        message = (getattr(exc, "msg", "") or str(exc)).lower()
        base = dict(code=code, uid=uid, nickname=nickname, region=region,
                    detail=f"{type(exc).__name__}:{retcode}")

        # 1) Precise retcode mapping (handles expired-vs-invalid sharing one class).
        if isinstance(retcode, int) and retcode in _RETCODE_STATUS:
            return RedeemResult(status=_RETCODE_STATUS[retcode], **base)

        # 2) Class-based fallback for anything without a mapped retcode.
        if isinstance(exc, ge.RedemptionClaimed):
            return RedeemResult(status=RedeemStatus.ALREADY_REDEEMED, **base)
        if isinstance(exc, ge.RedemptionCooldown):
            return RedeemResult(status=RedeemStatus.COOLDOWN, **base)
        if isinstance(exc, ge.RedemptionRegionLock):
            return RedeemResult(status=RedeemStatus.WRONG_REGION, **base)
        if isinstance(exc, ge.RedeemGameLevelTooLow):
            return RedeemResult(status=RedeemStatus.LEVEL_TOO_LOW, **base)
        if isinstance(exc, ge.CookieException):
            return RedeemResult(status=RedeemStatus.AUTH_FAILED, **base)
        if "expired" in message:
            return RedeemResult(status=RedeemStatus.EXPIRED, **base)
        if isinstance(exc, ge.RedemptionInvalid):
            return RedeemResult(status=RedeemStatus.INVALID, **base)

        # 3) Anything else — treat as a temporary/unknown upstream problem.
        return RedeemResult(status=RedeemStatus.SERVER_ERROR, **base)
