"""/start and /help handlers."""

from __future__ import annotations

from telegram import Update
from telegram.constants import ParseMode
from telegram.error import BadRequest
from telegram.ext import ContextTypes

from bot.assets.loader import get_asset_loader
from bot.commands.common import get_app, guard, reply, resolve_language, user_id_of
from bot.translations.i18n import t
from bot.utils.logging import get_logger
from bot.utils.text import strip_custom_emoji

logger = get_logger(__name__)

# Welcome image, loaded locally from the assets directory (category, filename).
_WELCOME_IMAGE = ("ui", "welcome.jpg")
# bot_data key caching the uploaded photo's Telegram file_id, so the image is uploaded
# once and reused on subsequent /start calls (no re-upload, no re-download).
_WELCOME_FILE_ID_KEY = "start_welcome_file_id"


@guard
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    app = get_app(context)
    uid = user_id_of(update)
    # Ensure a user row exists so language/settings persist from first contact.
    if uid is not None:
        await app.users.get_or_create(uid, app.settings.default_language)
    lang = await resolve_language(update, context)
    caption = t("start.welcome", lang)
    await _send_welcome_photo(update, context, caption)


async def _send_welcome_photo(
    update: Update, context: ContextTypes.DEFAULT_TYPE, caption: str
) -> None:
    """Send the welcome image with the caption, degrading gracefully.

    The image is resolved from the local assets directory (never re-downloaded). Its
    Telegram ``file_id`` is cached after the first upload so later calls reuse it. If the
    image is missing, we fall back to the original text-only welcome; if premium custom
    emoji aren't allowed, we retry the caption with standard-emoji fallback.
    """
    message = update.effective_message
    if message is None:
        return

    path = get_asset_loader().resolve(*_WELCOME_IMAGE)
    if path is None:
        # No image available — preserve the original text-only behavior.
        logger.info("Welcome image missing; sending text welcome")
        await reply(update, caption)
        return

    cached_file_id = context.application.bot_data.get(_WELCOME_FILE_ID_KEY)

    async def _send(photo, cap: str):
        return await message.reply_photo(photo=photo, caption=cap, parse_mode=ParseMode.HTML)

    try:
        sent = await _send(cached_file_id or path, caption)
    except BadRequest as exc:
        # Most likely the bot can't send premium custom emoji — retry with fallback.
        fallback = strip_custom_emoji(caption)
        if fallback != caption:
            logger.info("Custom emoji not sent in caption (%s); retrying with fallback", exc)
            sent = await _send(cached_file_id or path, fallback)
        else:
            raise

    # Cache the file_id from the largest photo size for reuse on future /start calls.
    if not cached_file_id and sent is not None and sent.photo:
        context.application.bot_data[_WELCOME_FILE_ID_KEY] = sent.photo[-1].file_id


@guard
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    lang = await resolve_language(update, context)
    await reply(update, t("help.text", lang))
