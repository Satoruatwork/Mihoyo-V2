"""HoYoLAB account linking: /hoyologin, /hoyologout, /hoyostatus.

``/hoyologin <cookie>`` authenticates a user's own HoYoLAB session so that account-bound
commands (today ``/redeem``) act on *their* account. Security-first:
  * login is **private-chat only** — never accept a credential where a group can see it,
  * the message containing the cookie is **deleted immediately** after it's read,
  * the cookie is validated before storage and only ever persisted **encrypted**.
"""

from __future__ import annotations

import html

from telegram import Update
from telegram.constants import ChatType, ParseMode
from telegram.error import BadRequest
from telegram.ext import ContextTypes

from bot.commands.common import get_app, guard, resolve_language, user_id_of
from bot.services.redemption_service import RedeemStatus
from bot.translations.i18n import t
from bot.utils.logging import get_logger
from bot.utils.text import strip_custom_emoji

logger = get_logger(__name__)

HR = "━━━━━━━━━━━━━━━━━━"


async def _send(context: ContextTypes.DEFAULT_TYPE, chat_id: int, text: str) -> None:
    """Send an HTML message, degrading premium custom emoji to standard ones if rejected."""
    try:
        await context.bot.send_message(
            chat_id=chat_id, text=text, parse_mode=ParseMode.HTML, disable_web_page_preview=True
        )
        return
    except BadRequest:
        fallback = strip_custom_emoji(text)
        if fallback != text:
            try:
                await context.bot.send_message(
                    chat_id=chat_id, text=fallback, parse_mode=ParseMode.HTML,
                    disable_web_page_preview=True,
                )
                return
            except Exception as exc:  # noqa: BLE001
                logger.debug("hoyolab_auth send fallback failed: %s", exc)
    except Exception as exc:  # noqa: BLE001
        logger.debug("hoyolab_auth send failed: %s", exc)


@guard
async def hoyologin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    app = get_app(context)
    lang = await resolve_language(update, context)
    user_id = user_id_of(update)
    chat = update.effective_chat
    message = update.message
    if user_id is None or chat is None or message is None:
        return

    # Never accept a credential outside a private chat.
    if chat.type != ChatType.PRIVATE:
        await _send(context, chat.id, t("hoyolab.login_dm_only", lang))
        return

    if not app.hoyolab_auth.enabled:
        await _send(context, chat.id, t("hoyolab.login_disabled", lang))
        return

    if not context.args:
        await _send(context, chat.id, t("hoyolab.login_usage", lang))
        return

    cookie = " ".join(context.args).strip()
    # Remove the message that contains the cookie as soon as we've captured it.
    try:
        await message.delete()
    except Exception as exc:  # noqa: BLE001 - best-effort; proceed regardless
        logger.debug("could not delete /hoyologin message: %s", exc)

    result = await app.hoyolab_auth.login(user_id, cookie)
    if result.status is RedeemStatus.SUCCESS:
        await _send(context, chat.id, _success_panel(result, lang))
    else:
        await _send(context, chat.id, _panel(lang, "hoyolab.login_failed_h", "hoyolab.login_failed_body"))


@guard
async def hoyologout(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    app = get_app(context)
    lang = await resolve_language(update, context)
    user_id = user_id_of(update)
    chat = update.effective_chat
    if user_id is None or chat is None:
        return
    removed = await app.hoyolab_auth.logout(user_id)
    await _send(context, chat.id, t("hoyolab.logout_done" if removed else "hoyolab.logout_none", lang))


@guard
async def hoyostatus(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    app = get_app(context)
    lang = await resolve_language(update, context)
    user_id = user_id_of(update)
    chat = update.effective_chat
    if user_id is None or chat is None:
        return
    logged_in = await app.hoyolab_auth.is_logged_in(user_id)
    await _send(context, chat.id, t("hoyolab.status_in" if logged_in else "hoyolab.status_out", lang))


# --------------------------------------------------------------------------- rendering
def _success_panel(result, lang: str) -> str:
    lines = [f"<b>{t('hoyolab.login_success_h', lang)}</b>", "", HR, ""]
    if result.nickname:
        lines += [f"<b>{t('hoyolab.f_traveler', lang)}</b>", html.escape(result.nickname, quote=False), ""]
    if result.uid:
        lines += [f"<b>{t('hoyolab.f_uid', lang)}</b>", f"<code>{html.escape(result.uid)}</code>", ""]
    if result.region:
        lines += [f"<b>{t('hoyolab.f_region', lang)}</b>", html.escape(result.region, quote=False), ""]
    lines += [HR, "", t("hoyolab.login_success_note", lang)]
    return "\n".join(lines)


def _panel(lang: str, header_key: str, body_key: str) -> str:
    return "\n".join([f"<b>{t(header_key, lang)}</b>", "", HR, "", t(body_key, lang), "", HR])
