"""Automatic user/group registration and session tracking.

A low-priority (group=-1) TypeHandler registers the user and chat on every update, so a
user is recorded the first time they interact and stats stay current. A ChatMemberHandler
tracks the bot being added to / removed from groups. Both are best-effort and never raise,
so they can't interfere with normal command handling.
"""

from __future__ import annotations

from typing import Awaitable

from telegram import Update
from telegram.constants import ChatMemberStatus, ChatType
from telegram.ext import ContextTypes

from bot.commands.common import get_app
from bot.utils.logging import get_logger

logger = get_logger(__name__)

_GROUP_TYPES = (ChatType.GROUP, ChatType.SUPERGROUP)
_PRESENT = (ChatMemberStatus.MEMBER, ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER)
_ABSENT = (ChatMemberStatus.LEFT, ChatMemberStatus.BANNED)


def _fire(context: ContextTypes.DEFAULT_TYPE, coro: Awaitable[None]) -> None:
    """Run a best-effort coroutine in the background so it never delays the command.

    Tracking writes to Redis; if Redis is slow/unreachable we must not make the user wait
    for it. PTB's ``application.create_task`` schedules and supervises the task (swallowing
    any error) without blocking this handler.
    """
    context.application.create_task(coro)


async def track(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Register the interacting user and (if applicable) the group. Never blocks or raises."""
    try:
        app = get_app(context)
        user = update.effective_user
        chat = update.effective_chat
        chat_type = chat.type if chat else None
        # Fire-and-forget: registration is best-effort and off the command's critical path.
        if user is not None and not user.is_bot:
            _fire(context, app.users.register_interaction(user.id, chat_type))
        if chat is not None and chat.type in _GROUP_TYPES:
            _fire(context, app.users.register_group(chat.id))
    except Exception as exc:  # noqa: BLE001 - tracking must never disrupt handling
        logger.debug("track failed: %s", exc)


async def on_my_chat_member(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Register/unregister a group when the bot is added to or removed from it."""
    try:
        app = get_app(context)
        cmu = update.my_chat_member
        if cmu is None:
            return
        chat = cmu.chat
        if chat.type not in _GROUP_TYPES:
            return
        status = cmu.new_chat_member.status
        if status in _PRESENT:
            await app.users.register_group(chat.id)
            logger.info("Bot added to group %s", chat.id)
        elif status in _ABSENT:
            await app.users.unregister_group(chat.id)
            logger.info("Bot removed from group %s", chat.id)
    except Exception as exc:  # noqa: BLE001
        logger.debug("on_my_chat_member failed: %s", exc)
