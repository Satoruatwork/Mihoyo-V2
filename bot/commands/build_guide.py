"""Build guide command: /build_guide [character name]."""

from __future__ import annotations

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from bot.commands.common import get_app, guard, resolve_language
from bot.translations.i18n import t


@guard
async def build_guide(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    app = get_app(context)
    lang = await resolve_language(update, context)

    name = " ".join(context.args).strip() if context.args else None
    guide = await app.build_service.get_guide(name)

    if not guide:
        await update.message.reply_text(t("build_guide.unavailable", lang), parse_mode=ParseMode.HTML)
        return

    lines = [t("build_guide.title", lang)]
    if name:
        lines.append(f"<b>{name}</b>")
    if guide.get("roles"):
        lines.append("Roles: " + ", ".join(guide["roles"]))
    if guide.get("weapons"):
        lines.append("Weapons: " + ", ".join(guide["weapons"]))
    if guide.get("artifacts"):
        lines.append("Artifacts: " + ", ".join(guide["artifacts"]))
    main_stats = guide.get("main_stats") or {}
    for slot, stat in main_stats.items():
        lines.append(f"{slot.capitalize()}: {stat}")
    if guide.get("substats"):
        lines.append("Substats: " + ", ".join(guide["substats"]))
    if guide.get("talent_priority"):
        lines.append("Talents: " + " > ".join(guide["talent_priority"]))
    if guide.get("notes"):
        lines.append("")
        lines.append(guide["notes"])

    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)
