"""Settings and language commands: /settings, /language.

Language selection uses inline buttons whose ``callback_data`` is ``lang:<code>``. The
callback persists the choice and confirms in the newly-selected language.
"""

from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from bot.commands.common import get_app, guard, resolve_language, user_id_of
from bot.translations import i18n
from bot.translations.i18n import t

LANG_CALLBACK_PREFIX = "lang"


def _language_keyboard(owner: int = 0) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for code, label in i18n.available_languages():
        row.append(InlineKeyboardButton(label, callback_data=f"{LANG_CALLBACK_PREFIX}:{code}:{owner}"))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    return InlineKeyboardMarkup(rows)


def _callback_owner(data: str) -> int:
    """Extract the owner user id (trailing segment) from a lang callback payload."""
    parts = data.split(":")
    if len(parts) > 2 and parts[2].isdigit():
        return int(parts[2])
    return 0


@guard
async def language(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    lang = await resolve_language(update, context)
    owner = user_id_of(update) or 0
    await update.message.reply_text(
        t("language.choose", lang), reply_markup=_language_keyboard(owner), parse_mode=ParseMode.HTML
    )


async def on_language_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Persist the chosen language and confirm in that language."""
    query = update.callback_query
    if query is None:
        return
    app = get_app(context)
    tg_id = user_id_of(update)
    data = query.data or ""
    parts = data.split(":")
    code = parts[1] if len(parts) > 1 else ""

    # Ownership is enforced centrally by the universal gate (bot.commands.ownership).
    if not i18n.is_supported(code) or tg_id is None:
        await query.answer()
        return

    await app.users.set_language(tg_id, code, app.settings.default_language)
    label = dict(i18n.available_languages()).get(code, code)
    try:
        await query.edit_message_text(t("language.set", code, language=label), parse_mode=ParseMode.HTML)
    except Exception:  # noqa: BLE001 - ignore identical-content edit errors
        pass
    await query.answer()


@guard
async def settings(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    app = get_app(context)
    lang = await resolve_language(update, context)
    tg_id = user_id_of(update)

    linked_uid = await app.account_service.get_uid(tg_id) if tg_id else None
    label = dict(i18n.available_languages()).get(lang, lang)

    lines = [t("settings.title", lang), t("settings.language_row", lang, language=label)]
    if linked_uid:
        lines.append(t("settings.linked_row", lang, uid=linked_uid))
    else:
        lines.append(t("settings.not_linked_row", lang))

    owner = tg_id or 0
    markup = InlineKeyboardMarkup(
        [[InlineKeyboardButton(
            t("settings.change_language", lang),
            callback_data=f"{LANG_CALLBACK_PREFIX}:__menu__:{owner}",
        )]]
    )
    await update.message.reply_text("\n".join(lines), reply_markup=markup, parse_mode=ParseMode.HTML)


async def on_settings_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the 'change language' button on the settings card -> show the language menu."""
    query = update.callback_query
    if query is None:
        return
    lang = await resolve_language(update, context)
    # Preserve the menu owner so the reopened language keyboard stays owner-restricted.
    owner = _callback_owner(query.data or "")
    try:
        await query.edit_message_text(
            t("language.choose", lang), reply_markup=_language_keyboard(owner), parse_mode=ParseMode.HTML
        )
    except Exception:  # noqa: BLE001
        pass
    await query.answer()
