"""Redemption business logic.

Validates a gift code and delegates the actual claim to a pluggable :class:`Redeemer`
backend, returning a structured :class:`RedeemResult` the command layer renders. No Telegram
and no HoYoLAB library here — the concrete backend (``bot.api.hoyolab_client``) owns that, so
the service stays trivially unit-testable and future redemption commands can reuse it.

The redemption happens entirely server-side on the bot's configured HoYoLAB account: there is
no link, button, UID prompt, or browser step. The service never raises — every outcome
(including a backend failure) is a result object with a status.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Protocol

from bot.utils.logging import get_logger

logger = get_logger(__name__)

# HoYoverse gift codes are ASCII letters + digits (commonly 8–16 chars). Accept 4–20 to stay
# tolerant of future formats; anything with spaces/symbols is rejected as malformed.
_CODE_RE = re.compile(r"^[A-Za-z0-9]{4,20}$")


class RedeemStatus(str, Enum):
    """Outcome of a redemption attempt. Each value maps to a response layout."""

    SUCCESS = "success"                 # 🎉 claimed; rewards delivered to in-game mail
    INVALID = "invalid"                 # ❌ code doesn't exist / malformed
    EXPIRED = "expired"                 # ❌ code expired or fully used up
    ALREADY_REDEEMED = "already"        # ℹ️ already claimed on this account
    WRONG_REGION = "wrong_region"       # ❌ code not valid for the account's region
    LEVEL_TOO_LOW = "level_too_low"     # ❌ Adventure Rank too low for this code
    COOLDOWN = "cooldown"               # 🚫 redemption on cooldown / rate-limited
    AUTH_FAILED = "auth_failed"         # ⚠️ configured session missing/expired/invalid
    SERVER_ERROR = "server_error"       # 🚫 upstream unreachable / unexpected error


@dataclass(slots=True)
class RedeemResult:
    """Structured result the command layer renders. No Telegram/UI concerns, no links."""

    status: RedeemStatus
    code: str
    uid: str | None = None
    region: str | None = None
    nickname: str | None = None
    rewards: list[str] = field(default_factory=list)
    detail: str | None = None  # technical note for logs; never shown to users


def normalize_code(raw: str) -> str | None:
    """Return an upper-cased, trimmed code, or ``None`` if the format is implausible."""
    code = (raw or "").strip()
    if not _CODE_RE.match(code):
        return None
    return code.upper()


class Redeemer(Protocol):
    """Pluggable redemption backend. Implementations should not raise (they classify their
    own errors into a :class:`RedeemResult`); the service guards against it anyway."""

    async def redeem(self, code: str) -> RedeemResult: ...


class _UnconfiguredRedeemer:
    """Default backend when none is wired: reports that the session isn't configured."""

    async def redeem(self, code: str) -> RedeemResult:
        return RedeemResult(status=RedeemStatus.AUTH_FAILED, code=code, detail="no redeemer configured")


class RedemptionService:
    """Validates codes and delegates redemption to a :class:`Redeemer` backend."""

    def __init__(self, redeemer: Redeemer | None = None) -> None:
        self._redeemer = redeemer or _UnconfiguredRedeemer()

    async def redeem(self, raw_code: str, *, redeemer: Redeemer | None = None) -> RedeemResult:
        """Validate ``raw_code`` then redeem it. Never raises.

        ``redeemer`` overrides the default backend for this call — the command layer passes a
        redeemer built from the requesting user's own session so the code lands on *their*
        account.
        """
        code = normalize_code(raw_code)
        if code is None:
            return RedeemResult(status=RedeemStatus.INVALID, code=(raw_code or "").strip())
        backend = redeemer or self._redeemer
        try:
            return await backend.redeem(code)
        except Exception as exc:  # noqa: BLE001 - a backend hiccup must never crash the command
            logger.warning("Redeem backend failed for code=%s: %s", code, exc)
            return RedeemResult(status=RedeemStatus.SERVER_ERROR, code=code, detail=str(exc))
