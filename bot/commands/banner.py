"""Banner command: /banner."""

from __future__ import annotations

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from bot.commands.common import get_app, guard, resolve_language
from bot.translations.i18n import t


@guard
async def banner(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    app = get_app(context)
    lang = await resolve_language(update, context)
    board = await app.banner_service.get_banners()

    if not board.available:
        await update.message.reply_text(t("banner.unavailable", lang), parse_mode=ParseMode.HTML)
        return

    lines = [t("banner.title", lang)]
    for b in board.current:
        featured = f" — {', '.join(b.featured)}" if b.featured else ""
        lines.append(t("banner.current", lang, name=f"{b.name}{featured}"))
    for b in board.upcoming:
        featured = f" — {', '.join(b.featured)}" if b.featured else ""
        lines.append(t("banner.upcoming", lang, name=f"{b.name}{featured}"))

    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)
