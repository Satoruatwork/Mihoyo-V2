"""Spiral Abyss commands: /abyss, /preabyss, /abysscard, /preabysscard."""

from __future__ import annotations

import asyncio
import io

from telegram import Update
from telegram.constants import ChatAction, ParseMode
from telegram.ext import ContextTypes

from bot.commands.common import get_app, guard, resolve_language, user_id_of, with_action
from bot.renderer.context import AbyssCardContext
from bot.translations.i18n import t
from bot.utils.timing import atimed


async def _load(update: Update, context: ContextTypes.DEFAULT_TYPE, *, previous: bool):
    app = get_app(context)
    lang = await resolve_language(update, context)
    tg_id = user_id_of(update)
    uid = await app.account_service.require_uid(tg_id)
    showcase = await app.character_service.get_showcase(uid, lang)
    abyss = await app.abyss_service.get_abyss(uid, previous=previous, language=lang)
    return app, lang, showcase, abyss


def _text(abyss, lang: str) -> str:
    title = t("abyss.pre_title" if abyss.is_previous else "abyss.title", lang)
    lines = [title]
    if abyss.max_floor:
        lines.append(t("abyss.max_floor", lang, floor=abyss.max_floor))
    if abyss.total_stars is not None:
        lines.append(t("abyss.stars", lang, stars=abyss.total_stars))
    return "\n".join(lines)


@guard
@with_action()
async def abyss(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _, lang, _showcase, data = await _load(update, context, previous=False)
    await update.message.reply_text(_text(data, lang), parse_mode=ParseMode.HTML)


@guard
@with_action()
async def pre_abyss(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _, lang, _showcase, data = await _load(update, context, previous=True)
    await update.message.reply_text(_text(data, lang), parse_mode=ParseMode.HTML)


@guard
@with_action(ChatAction.UPLOAD_PHOTO)
async def abyss_card(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    app, lang, showcase, data = await _load(update, context, previous=False)
    async with atimed("render.abyss_card"):
        png = await asyncio.to_thread(
            app.renderer.render_abyss_card,
            AbyssCardContext(language=lang, abyss=data, player=showcase.player),
        )
    await update.message.reply_photo(photo=io.BytesIO(png))


@guard
@with_action(ChatAction.UPLOAD_PHOTO)
async def pre_abyss_card(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    app, lang, showcase, data = await _load(update, context, previous=True)
    async with atimed("render.abyss_card"):
        png = await asyncio.to_thread(
            app.renderer.render_abyss_card,
            AbyssCardContext(language=lang, abyss=data, player=showcase.player),
        )
    await update.message.reply_photo(photo=io.BytesIO(png))
