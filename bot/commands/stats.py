"""/stats command — live bot statistics."""

from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from bot.commands.common import get_app, guard, reply, resolve_language
from bot.translations.i18n import t


def _format_uptime(seconds: int) -> str:
    days, rem = divmod(max(0, seconds), 86400)
    hours, rem = divmod(rem, 3600)
    minutes, _ = divmod(rem, 60)
    parts = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    parts.append(f"{minutes}m")
    return " ".join(parts)


@guard
async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    app = get_app(context)
    lang = await resolve_language(update, context)
    snap = await app.stats_service.snapshot()

    redis_state = t("stats.redis_ok", lang) if snap.redis_ok else t("stats.redis_down", lang)
    lines = [
        t("stats.title", lang),
        t("stats.users", lang, count=snap.users),
        t("stats.groups", lang, count=snap.groups),
        t("stats.private", lang, count=snap.private_chats),
        t("stats.redis", lang, status=redis_state),
        t("stats.uptime", lang, uptime=_format_uptime(snap.uptime_seconds)),
        t("stats.version", lang, version=snap.version),
    ]
    await reply(update, "\n".join(lines))
