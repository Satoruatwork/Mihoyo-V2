"""Broadcast business logic: resolve recipients and fan a message out to them.

Framework-agnostic by design (the project keeps Telegram out of ``services/``): the caller
injects an async ``send_fn(chat_id) -> SendOutcome`` that knows how to actually deliver the
message, and this service owns recipient enumeration, throttling, outcome tallying, and
collecting the ids of recipients that should be pruned (blocked/kicked). That keeps the loop
fully unit-testable with a fake ``send_fn`` and no Telegram bot.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from enum import Enum
from typing import Awaitable, Callable

from bot.database.store import RedisStore
from bot.utils.logging import get_logger

logger = get_logger(__name__)


class BroadcastTarget(str, Enum):
    """Which audience a broadcast is sent to."""

    USERS = "users"
    GROUPS = "groups"
    ALL = "all"


class SendOutcome(str, Enum):
    """Result of delivering to a single recipient."""

    SENT = "sent"        # delivered
    BLOCKED = "blocked"  # recipient blocked the bot / deactivated / kicked — safe to prune
    FAILED = "failed"    # transient error (timeout/network) — keep the recipient


@dataclass(slots=True)
class BroadcastResult:
    """Running tally of a broadcast."""

    total: int = 0
    sent: int = 0
    blocked: int = 0
    failed: int = 0
    blocked_ids: list[int] = field(default_factory=list)

    def record(self, chat_id: int, outcome: SendOutcome) -> None:
        if outcome is SendOutcome.SENT:
            self.sent += 1
        elif outcome is SendOutcome.BLOCKED:
            self.blocked += 1
            self.blocked_ids.append(chat_id)
        else:
            self.failed += 1


SendFn = Callable[[int], Awaitable[SendOutcome]]
ProgressFn = Callable[[int, BroadcastResult], Awaitable[None]]


class BroadcastService:
    """Resolves broadcast audiences and drives a throttled fan-out."""

    def __init__(self, users: RedisStore) -> None:
        self._users = users

    async def recipients(self, target: BroadcastTarget) -> list[int]:
        """Return the de-duplicated chat ids for ``target`` (users have +ve ids, groups -ve)."""
        ids: list[int] = []
        if target in (BroadcastTarget.USERS, BroadcastTarget.ALL):
            ids += await self._users.all_users()
        if target in (BroadcastTarget.GROUPS, BroadcastTarget.ALL):
            ids += await self._users.all_groups()
        seen: set[int] = set()
        unique: list[int] = []
        for chat_id in ids:
            if chat_id not in seen:
                seen.add(chat_id)
                unique.append(chat_id)
        return unique

    async def broadcast(
        self,
        chat_ids: list[int],
        send_fn: SendFn,
        *,
        per_second: float = 20.0,
        progress: ProgressFn | None = None,
        progress_every: int = 25,
    ) -> BroadcastResult:
        """Deliver to every id via ``send_fn``, throttled to ``per_second`` messages.

        Telegram permits roughly 30 messages/second across different chats; the default
        keeps a safe margin. ``send_fn`` should not raise (it classifies its own errors into
        a :class:`SendOutcome`), but an unexpected exception is contained and counted as a
        failure rather than aborting the whole run.
        """
        result = BroadcastResult(total=len(chat_ids))
        delay = 1.0 / per_second if per_second > 0 else 0.0
        last = len(chat_ids)
        for i, chat_id in enumerate(chat_ids, 1):
            try:
                outcome = await send_fn(chat_id)
            except Exception as exc:  # noqa: BLE001 - one bad send must not stop the broadcast
                logger.warning("send_fn raised for %s: %s", chat_id, exc)
                outcome = SendOutcome.FAILED
            result.record(chat_id, outcome)

            if progress is not None and i % progress_every == 0:
                try:
                    await progress(i, result)
                except Exception as exc:  # noqa: BLE001 - progress UI is best-effort
                    logger.debug("broadcast progress callback failed: %s", exc)

            if delay and i < last:
                await asyncio.sleep(delay)
        return result
