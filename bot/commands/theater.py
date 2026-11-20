"""Imaginarium Theater commands: /theater, /theatercard."""

from __future__ import annotations

import asyncio
import io

from telegram import Update
from telegram.constants import ChatAction, ParseMode
from telegram.ext import ContextTypes

from bot.commands.common import get_app, guard, resolve_language, user_id_of, with_action
from bot.renderer.context import TheaterCardContext
from bot.translations.i18n import t
from bot.utils.timing import atimed


async def _load(update: Update, context: ContextTypes.DEFAULT_TYPE):
    app = get_app(context)
    lang = await resolve_language(update, context)
    tg_id = user_id_of(update)
    uid = await app.account_service.require_uid(tg_id)
    showcase = await app.character_service.get_showcase(uid, lang)
    theater = await app.theater_service.get_theater(uid, language=lang)
    return app, lang, showcase, theater


@guard
@with_action()
async def theater(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _, lang, _showcase, data = await _load(update, context)
    if not data.available:
        await update.message.reply_text(t("theater.unavailable", lang), parse_mode=ParseMode.HTML)
        return
    lines = [t("theater.title", lang)]
    if data.act is not None:
        lines.append(t("theater.act", lang, act=data.act))
    if data.stars is not None:
        lines.append(t("abyss.stars", lang, stars=data.stars))
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)


@guard
@with_action(ChatAction.UPLOAD_PHOTO)
async def theater_card(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    app, lang, showcase, data = await _load(update, context)
    async with atimed("render.theater_card"):
        png = await asyncio.to_thread(
            app.renderer.render_theater_card,
            TheaterCardContext(language=lang, theater=data, player=showcase.player),
        )
    await update.message.reply_photo(photo=io.BytesIO(png))
