"""Redemption command: ``/redeem <code>``.

Claims an official HoYoverse gift code automatically on the bot's configured HoYoLAB
account and returns the final result inside Telegram — no buttons, no links, no website
redirect, no UID/login prompt.

Flow:
  1. Format-validate the code (a malformed code fails instantly, without an API call).
  2. Post a "verifying…" message so the command feels instant.
  3. Redeem on the configured account and wait for HoYoverse's response.
  4. Edit the same message into a premium, Genshin-themed result card.

A per-user in-flight guard prevents a second ``/redeem`` from running while the first is
still processing (no double submissions). The redemption backend lives in
:mod:`bot.api.hoyolab_client` so future redemption commands can reuse it.
"""

from __future__ import annotations

import html

from telegram import Message, Update
from telegram.constants import ChatAction, ParseMode
from telegram.error import BadRequest
from telegram.ext import ContextTypes

from bot.api.hoyolab_client import HoyolabRedeemer
from bot.commands.common import get_app, guard, resolve_language, user_id_of, with_action
from bot.services.redemption_service import RedeemResult, RedeemStatus
from bot.translations.i18n import t
from bot.utils.logging import get_logger
from bot.utils.text import strip_custom_emoji

logger = get_logger(__name__)

# Decorative divider used across every redemption layout.
HR = "━━━━━━━━━━━━━━━━━━"

# Telegram user ids with a redemption currently in flight (process-wide; PTB is single-process).
_IN_FLIGHT: set[int] = set()


def _acquire(user_id: int) -> bool:
    """Claim the in-flight slot for a user. False if they already have one running."""
    if user_id in _IN_FLIGHT:
        return False
    _IN_FLIGHT.add(user_id)
    return True


def _release(user_id: int) -> None:
    _IN_FLIGHT.discard(user_id)


@guard
@with_action(ChatAction.TYPING)
async def redeem(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.message
    user_id = user_id_of(update)
    if message is None or user_id is None:
        return

    app = get_app(context)
    lang = await resolve_language(update, context)

    if not context.args:
        await _send(message, t("redeem.usage", lang))
        return

    # Redemption acts on the user's own linked HoYoLAB account. No session -> ask them to link.
    cookie = await app.hoyolab_auth.get_cookie(user_id)
    if not cookie:
        await _send(message, _panel(lang, "redeem.not_logged_in_h", "redeem.not_logged_in_body"))
        return

    # Prevent duplicate submissions while a redemption is already in progress for this user.
    if not _acquire(user_id):
        await _send(message, _panel(lang, "redeem.in_progress_h", "redeem.in_progress_body"))
        return

    status_msg = await _send(message, t("redeem.loading", lang))
    try:
        result = await app.redemption_service.redeem(
            context.args[0], redeemer=HoyolabRedeemer(cookie)
        )
    finally:
        _release(user_id)

    # Never log the code contents at info level alongside user id — just the outcome.
    logger.info("redeem by user=%s -> %s", user_id, result.status.value)

    text = _render(result, lang)
    if status_msg is not None:
        await _edit(status_msg, text)
    else:
        await _send(message, text)


# --------------------------------------------------------------------------- rendering
def _esc(value: str) -> str:
    """Escape HTML in body text. quote=False keeps apostrophes readable ("Hero's Wit")."""
    return html.escape(value, quote=False)


def _render(result: RedeemResult, lang: str) -> str:
    """Map a :class:`RedeemResult` to a finished premium HTML message (never a link/button)."""
    status = result.status
    if status is RedeemStatus.SUCCESS:
        return _success(result, lang)
    if status is RedeemStatus.INVALID:
        return _panel(lang, "redeem.h_invalid", "redeem.invalid_body", footer_key="redeem.invalid_hint")
    if status is RedeemStatus.EXPIRED:
        return _panel(lang, "redeem.h_expired", "redeem.expired_body", footer_key="redeem.expired_note")
    if status is RedeemStatus.ALREADY_REDEEMED:
        return _panel(lang, "redeem.h_already", "redeem.already_body")
    if status is RedeemStatus.AUTH_FAILED:
        return _panel(lang, "redeem.h_auth", "redeem.auth_body")
    if status in (RedeemStatus.COOLDOWN, RedeemStatus.SERVER_ERROR):
        return _panel(lang, "redeem.h_busy", "redeem.busy_body")

    # WRONG_REGION / LEVEL_TOO_LOW share the generic "Redeem Failed" card + a reason line.
    reason_key = {
        RedeemStatus.WRONG_REGION: "redeem.reason_region",
        RedeemStatus.LEVEL_TOO_LOW: "redeem.reason_level",
    }.get(status, "redeem.reason_generic")
    return _failed(lang, reason_key)


def _success(result: RedeemResult, lang: str) -> str:
    parts = [f"<b>{t('redeem.h_success', lang)}</b>", "", HR, "", t("redeem.success_body", lang), "", HR]
    # Only list rewards the redemption response actually returned — never fabricated.
    if result.rewards:
        parts += ["", f"<b>{t('redeem.rewards_header', lang)}</b>", ""]
        parts += [f"• {_esc(r)}" for r in result.rewards]
        parts += ["", HR]
    parts += ["", t("redeem.success_enjoy", lang)]
    return "\n".join(parts)


def _failed(lang: str, reason_key: str) -> str:
    return "\n".join([
        f"<b>{t('redeem.h_failed', lang)}</b>", "", HR, "",
        t(reason_key, lang), "", t("redeem.failed_norewards", lang), "", HR,
    ])


def _panel(lang: str, header_key: str, body_key: str, *, footer_key: str | None = None) -> str:
    parts = [f"<b>{t(header_key, lang)}</b>", "", HR, "", t(body_key, lang), "", HR]
    if footer_key:
        parts += ["", t(footer_key, lang)]
    return "\n".join(parts)


# --------------------------------------------------------------------------- telegram I/O
async def _send(message: Message, text: str) -> Message | None:
    """Send an HTML reply, degrading to standard emoji if custom emoji are rejected."""
    try:
        return await message.reply_text(text, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
    except BadRequest:
        fallback = strip_custom_emoji(text)
        if fallback != text:
            try:
                return await message.reply_text(
                    fallback, parse_mode=ParseMode.HTML, disable_web_page_preview=True
                )
            except Exception as exc:  # noqa: BLE001
                logger.debug("redeem send fallback failed: %s", exc)
        return None


async def _edit(message: Message, text: str) -> None:
    """Edit a message to the final result, with the same custom-emoji fallback."""
    try:
        await message.edit_text(text, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
        return
    except BadRequest:
        fallback = strip_custom_emoji(text)
        if fallback != text:
            try:
                await message.edit_text(
                    fallback, parse_mode=ParseMode.HTML, disable_web_page_preview=True
                )
                return
            except Exception as exc:  # noqa: BLE001
                logger.debug("redeem edit fallback failed: %s", exc)
    except Exception as exc:  # noqa: BLE001
        logger.debug("redeem edit failed: %s", exc)
