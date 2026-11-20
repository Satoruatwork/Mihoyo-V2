"""Owner-only broadcast command: ``/broadcast [--users|--groups|--all] <message>``.

Sends a message to every chat the bot knows about — Raiden-style. Two ways to use it:

  * ``/broadcast <text>``            — send plain text to the audience.
  * reply to any message with        — copy that message (text, photo, album, sticker,
    ``/broadcast``                     formatting, …) to the audience via ``copy_message``.

An optional leading flag picks the audience (default: users only):
  ``--users`` (default) · ``--groups`` · ``--all``.

Only Telegram ids in ``settings.admin_id_set`` may run it. The handler shows a live status
message, throttles delivery, and prunes chats that have blocked/removed the bot.
"""

from __future__ import annotations

from telegram import Message, Update
from telegram.constants import ChatAction, ParseMode
from telegram.error import Forbidden, RetryAfter, TelegramError
from telegram.ext import ContextTypes

from bot.app_context import AppContext
from bot.commands.common import get_app, guard, reply, resolve_language, user_id_of, with_action
from bot.services.broadcast_service import BroadcastResult, BroadcastTarget, SendOutcome
from bot.translations.i18n import t
from bot.utils.logging import get_logger

logger = get_logger(__name__)

_TARGET_FLAGS = {
    "--users": BroadcastTarget.USERS,
    "--groups": BroadcastTarget.GROUPS,
    "--all": BroadcastTarget.ALL,
}


def _parse_target(args: list[str]) -> tuple[BroadcastTarget, list[str]]:
    """Split an optional leading ``--users/--groups/--all`` flag off the message args."""
    if args and args[0].lower() in _TARGET_FLAGS:
        return _TARGET_FLAGS[args[0].lower()], args[1:]
    return BroadcastTarget.USERS, list(args)


@guard
@with_action(ChatAction.TYPING)
async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    app = get_app(context)
    lang = await resolve_language(update, context)
    tg_id = user_id_of(update)
    if tg_id is None:
        return

    # Owner gate — silently useless to everyone else.
    if tg_id not in app.settings.admin_id_set:
        await reply(update, t("broadcast.not_authorized", lang))
        return

    target, rest = _parse_target(list(context.args or []))
    source: Message | None = update.message.reply_to_message if update.message else None
    text = " ".join(rest).strip()

    if source is None and not text:
        await reply(update, t("broadcast.usage", lang))
        return

    chat_ids = await app.broadcast_service.recipients(target)
    if not chat_ids:
        await reply(update, t("broadcast.empty", lang))
        return

    status = await _send_status(update, t("broadcast.starting", lang, count=len(chat_ids)))
    send_fn = _make_send_fn(context.bot, source, text)

    async def _progress(done: int, result: BroadcastResult) -> None:
        await _edit(status, t("broadcast.progress", lang, done=done, total=result.total))

    result = await app.broadcast_service.broadcast(chat_ids, send_fn, progress=_progress)
    await _prune_dead(app, result)

    logger.info(
        "Broadcast by %s -> target=%s total=%d sent=%d blocked=%d failed=%d",
        tg_id, target.value, result.total, result.sent, result.blocked, result.failed,
    )
    await _edit(
        status,
        t("broadcast.summary", lang, total=result.total, sent=result.sent,
          blocked=result.blocked, failed=result.failed),
    )


def _make_send_fn(bot, source: Message | None, text: str):
    """Build the per-recipient sender, mapping Telegram errors to a :class:`SendOutcome`."""

    async def _deliver(chat_id: int) -> None:
        if source is not None:
            await bot.copy_message(
                chat_id=chat_id, from_chat_id=source.chat_id, message_id=source.message_id
            )
        else:
            # Plain text (no parse mode) so an admin's stray '<' can never break delivery.
            await bot.send_message(chat_id=chat_id, text=text, disable_web_page_preview=True)

    async def send(chat_id: int) -> SendOutcome:
        try:
            await _deliver(chat_id)
            return SendOutcome.SENT
        except Forbidden:
            # Blocked by user, account deactivated, or bot kicked from the group.
            return SendOutcome.BLOCKED
        except RetryAfter as exc:
            # Flood control — wait out the cooldown, then try this recipient once more.
            import asyncio

            await asyncio.sleep(float(getattr(exc, "retry_after", 1)) + 0.5)
            try:
                await _deliver(chat_id)
                return SendOutcome.SENT
            except Forbidden:
                return SendOutcome.BLOCKED
            except Exception:  # noqa: BLE001
                return SendOutcome.FAILED
        except TelegramError:
            return SendOutcome.FAILED
        except Exception:  # noqa: BLE001 - never let one recipient abort the run
            return SendOutcome.FAILED

    return send


async def _prune_dead(app: AppContext, result: BroadcastResult) -> None:
    """Drop chats that blocked/removed the bot so counts and future broadcasts stay clean."""
    if not result.blocked_ids:
        return
    users = [cid for cid in result.blocked_ids if cid >= 0]
    groups = [cid for cid in result.blocked_ids if cid < 0]
    await app.users.discard_users(users)
    await app.users.discard_groups(groups)


async def _send_status(update: Update, text: str) -> Message | None:
    """Send the initial status message we later edit with progress + the final summary."""
    msg = update.message
    if msg is None:
        return None
    try:
        return await msg.reply_text(
            text, parse_mode=ParseMode.HTML, disable_web_page_preview=True
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("Could not send broadcast status message: %s", exc)
        return None


async def _edit(message: Message | None, text: str) -> None:
    """Edit the status message in place. Best-effort (ignores 'not modified' etc.)."""
    if message is None:
        return
    try:
        await message.edit_text(text, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
    except Exception as exc:  # noqa: BLE001
        logger.debug("Broadcast status edit skipped: %s", exc)
