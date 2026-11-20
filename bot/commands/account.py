"""Account commands: /genshinlogin, /genshinlogout, /myuid, /myinfo."""

from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from bot.commands.common import get_app, guard, reply, resolve_language, user_id_of, with_action
from bot.translations.i18n import t


@guard
async def genshin_login(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    app = get_app(context)
    lang = await resolve_language(update, context)
    uid = user_id_of(update)
    if uid is None:
        return

    if not context.args:
        await reply(update, t("account.login_usage", lang))
        return

    linked_uid, was_relink = await app.account_service.link(uid, context.args[0])
    key = "account.relinked" if was_relink else "account.linked"
    await reply(update, t(key, lang, uid=linked_uid))


@guard
async def genshin_logout(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    app = get_app(context)
    lang = await resolve_language(update, context)
    uid = user_id_of(update)
    if uid is None:
        return
    removed = await app.account_service.unlink(uid)
    await reply(update, t("account.logout_success" if removed else "account.logout_none", lang))


@guard
async def my_uid(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    app = get_app(context)
    lang = await resolve_language(update, context)
    uid = user_id_of(update)
    if uid is None:
        return
    linked = await app.account_service.get_uid(uid)
    if linked:
        await reply(update, t("account.myuid", lang, uid=linked))
    else:
        await reply(update, t("account.myuid_none", lang))


@guard
@with_action()
async def my_info(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    app = get_app(context)
    lang = await resolve_language(update, context)
    uid = user_id_of(update)
    if uid is None:
        return

    # Requires a linked account; raises AccountNotLinked (handled by @guard) otherwise.
    linked = await app.account_service.require_uid(uid)
    showcase = await app.character_service.get_showcase(linked, lang)
    p = showcase.player

    lines = [t("account.myinfo_title", lang)]
    if p.nickname:
        lines.append(t("account.myinfo_nickname", lang, nickname=p.nickname))
    lines.append(t("account.myinfo_uid", lang, uid=p.uid))
    if p.level:
        lines.append(t("account.myinfo_level", lang, level=p.level))
    if p.world_level:
        lines.append(t("account.myinfo_world_level", lang, world_level=p.world_level))
    if p.signature:
        lines.append(t("account.myinfo_signature", lang, signature=p.signature))
    if p.achievements is not None:
        lines.append(t("account.myinfo_achievements", lang, achievements=p.achievements))
    if p.abyss_floor is not None and p.abyss_chamber is not None:
        lines.append(t("account.myinfo_abyss", lang, floor=p.abyss_floor, chamber=p.abyss_chamber))

    await reply(update, "\n".join(lines))
