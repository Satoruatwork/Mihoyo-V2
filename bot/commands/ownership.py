"""Universal inline-keyboard ownership guard.

A single callback gate, registered ahead of every other callback handler, ensures only the
user who created an interactive menu can operate it. The owner's Telegram id is carried in
each button's ``callback_data`` (see :mod:`bot.utils.callbacks`). On a mismatch the gate
answers the query with a popup and stops all further processing via
:class:`telegram.ext.ApplicationHandlerStop`, leaving the original message untouched. For
the owner (or callbacks without an encoded owner), the gate does nothing and normal handling
continues exactly as before.
"""

from __future__ import annotations

from telegram import Update
from telegram.ext import ApplicationHandlerStop, ContextTypes

from bot.commands.common import resolve_language, user_id_of
from bot.translations.i18n import t
from bot.utils import callbacks
from bot.utils.logging import get_logger

logger = get_logger(__name__)


async def enforce_callback_owner(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Block non-owners from operating an interactive menu. Owners pass through untouched."""
    query = update.callback_query
    if query is None:
        return

    owner = callbacks.extract_owner(query.data or "")
    if not owner:
        return  # unrestricted / no owner encoded -> let normal handlers run
    if (user_id_of(update) or 0) == owner:
        return  # the original owner -> proceed exactly as before

    # Someone else pressed the button: answer with a popup only and stop all processing.
    try:
        lang = await resolve_language(update, context)
        await query.answer(t("error.not_your_menu", lang), show_alert=True)
    except Exception:  # noqa: BLE001 - always answer, even if localization fails
        try:
            await query.answer()
        except Exception:  # noqa: BLE001
            pass
    raise ApplicationHandlerStop
