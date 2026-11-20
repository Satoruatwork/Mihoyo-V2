"""Shared helpers for command handlers: context access, language, error handling."""

from __future__ import annotations

import functools
import time
from typing import Awaitable, Callable

from telegram import Update
from telegram.constants import ChatAction, ParseMode
from telegram.error import BadRequest
from telegram.ext import ContextTypes

from bot.app_context import BOT_DATA_KEY, AppContext
from bot.translations.i18n import t
from bot.utils.errors import BotError
from bot.utils.logging import get_logger
from bot.utils.text import strip_custom_emoji
from bot.utils.timing import perf_logger

logger = get_logger(__name__)

HandlerFn = Callable[[Update, ContextTypes.DEFAULT_TYPE], Awaitable[None]]


def get_app(context: ContextTypes.DEFAULT_TYPE) -> AppContext:
    """Return the shared :class:`AppContext` from ``bot_data``."""
    return context.application.bot_data[BOT_DATA_KEY]


def with_action(action: str = ChatAction.TYPING) -> Callable[[HandlerFn], HandlerFn]:
    """Decorator: show a chat action (``typing``/``upload_photo``) while the handler runs.

    Makes network/render-heavy commands *feel* instant — Telegram shows the bot "typing" (or
    "sending photo") the moment the command arrives, so the wait for an Enka fetch or a render
    is visible activity rather than dead air. Best-effort: a failed action never blocks.
    """

    def decorator(handler: HandlerFn) -> HandlerFn:
        @functools.wraps(handler)
        async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
            chat = update.effective_chat
            if chat is not None:
                try:
                    await context.bot.send_chat_action(chat_id=chat.id, action=action)
                except Exception:  # noqa: BLE001 - purely cosmetic
                    pass
            await handler(update, context)

        return wrapper

    return decorator


def user_id_of(update: Update) -> int | None:
    return update.effective_user.id if update.effective_user else None


async def resolve_language(update: Update, context: ContextTypes.DEFAULT_TYPE) -> str:
    """Resolve the effective user's preferred language."""
    app = get_app(context)
    uid = user_id_of(update)
    if uid is None:
        return app.settings.default_language
    return await app.language_for(uid)


def error_text(exc: Exception, lang: str) -> str:
    """Map any exception to a localized, user-facing message."""
    if isinstance(exc, BotError):
        return t(exc.i18n_key, lang)
    return t("error.generic", lang)


def guard(handler: HandlerFn) -> HandlerFn:
    """Decorator: catch errors, log them, and reply with a localized message.

    Ensures a handler can never crash the bot — expected :class:`BotError`s become friendly
    localized replies; anything unexpected is logged and shown as a generic error.
    """

    @functools.wraps(handler)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        start = time.perf_counter()
        try:
            await handler(update, context)
        except BotError as exc:
            lang = await _safe_lang(update, context)
            logger.info("Handled BotError in %s: %s", handler.__name__, exc.detail or exc)
            await reply(update, error_text(exc, lang))
        except Exception:  # noqa: BLE001 - last-resort guard; never crash
            lang = await _safe_lang(update, context)
            logger.exception("Unexpected error in %s", handler.__name__)
            await reply(update, t("error.generic", lang))
        finally:
            perf_logger.info("%s total: %.0f ms", handler.__name__, (time.perf_counter() - start) * 1000)

    return wrapper


async def _safe_lang(update: Update, context: ContextTypes.DEFAULT_TYPE) -> str:
    try:
        return await resolve_language(update, context)
    except Exception:  # noqa: BLE001
        return "en"


async def reply(update: Update, text: str, **kwargs) -> None:
    """Reply to a message or callback query with HTML formatting by default.

    If the text contains premium custom emoji (``<tg-emoji>`` tags) and the bot is not
    allowed to send them (e.g. the owner has no Telegram Premium), Telegram rejects the
    send with a BadRequest; we transparently retry with the standard-emoji fallback so
    the user always receives the message.
    """
    kwargs.setdefault("parse_mode", ParseMode.HTML)
    kwargs.setdefault("disable_web_page_preview", True)

    target = None
    if update.message is not None:
        target = update.message
    elif update.callback_query is not None and update.callback_query.message is not None:
        target = update.callback_query.message
    if target is None:
        return

    try:
        await target.reply_text(text, **kwargs)
    except BadRequest as exc:
        fallback = strip_custom_emoji(text)
        if fallback != text:
            logger.info("Custom emoji not sent (%s); retrying with fallback emoji", exc)
            await target.reply_text(fallback, **kwargs)
        else:
            raise
