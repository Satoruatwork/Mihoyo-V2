"""Character showcase commands and single-message callback navigation.

Commands:
    /mycharacters (/myc) — browse your own showcase.
    /inspect <UID>       — browse another player's showcase.

The whole interaction lives in **one** Telegram message. ``/mycharacters`` sends a single
photo message (a banner with the character list as its caption and inline buttons). Pressing
a character edits that same message into the character card (``editMessageMedia``); pressing
Back edits it straight back to the list. No new message is ever created for navigation.

State is reconstructed from the pressed button's ``callback_data`` (see
:mod:`bot.utils.callbacks`) plus the cached showcase, so navigation survives restarts. Rendered
card images are cached by Telegram ``file_id`` (per uid/character/language) so re-opening a
character re-uses the already-uploaded image instead of re-rendering + re-uploading.
"""

from __future__ import annotations

import asyncio
import html
import io
import time

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputMediaPhoto,
    Update,
)
from telegram.constants import ChatAction, ParseMode
from telegram.error import BadRequest
from telegram.ext import ContextTypes

from bot.app_context import AppContext
from bot.commands.common import get_app, guard, resolve_language, user_id_of, with_action
from bot.models.character import Character
from bot.models.player import PlayerInfo, Showcase
from bot.renderer.card_data import from_character
from bot.renderer.card_layout import theme_for
from bot.renderer.character_adjustments import adjustment_for
from bot.renderer.character_card_renderer import get_card_renderer
from bot.renderer.context import CharacterCardContext
from bot.translations.i18n import t
from bot.utils import callbacks
from bot.utils.errors import BotError
from bot.utils.logging import get_logger
from bot.utils.text import strip_custom_emoji
from bot.utils.timing import atimed, perf_logger

logger = get_logger(__name__)

PAGE_SIZE = 8       # character buttons per page
COLUMNS = 2

_BANNER_KEY = "__banner__"


class _TTLFileCache:
    """Tiny TTL + size-bounded cache of Telegram ``file_id`` strings.

    Lets navigation re-use already-uploaded images (banner + character cards) instead of
    re-rendering/re-uploading. Entries expire after ``ttl`` seconds and the oldest are
    evicted past ``maxsize`` — so it never grows without bound (file_ids are tiny strings).
    """

    def __init__(self, ttl: float = 900.0, maxsize: int = 256) -> None:
        self._ttl = ttl
        self._max = maxsize
        self._data: dict[object, tuple[float, str]] = {}

    def get(self, key: object) -> str | None:
        entry = self._data.get(key)
        if entry is None:
            return None
        ts, file_id = entry
        if (time.monotonic() - ts) > self._ttl:
            self._data.pop(key, None)
            return None
        return file_id

    def put(self, key: object, file_id: str) -> None:
        self._data[key] = (time.monotonic(), file_id)
        if len(self._data) > self._max:
            # Drop the oldest entries (simple age-based eviction).
            for old_key, _ in sorted(self._data.items(), key=lambda kv: kv[1][0])[
                : len(self._data) - self._max
            ]:
                self._data.pop(old_key, None)


# Process-wide image cache. file_ids are bot-global and reusable across chats/messages.
_FILE_IDS = _TTLFileCache()


def _photo_arg(photo: str | bytes):
    """Return a value usable as a Telegram photo: a file_id string or a fresh BytesIO."""
    return photo if isinstance(photo, str) else io.BytesIO(photo)


def _banner_photo(app: AppContext) -> str | bytes:
    """Return the list banner as a cached file_id, else the raw image bytes to upload once."""
    fid = _FILE_IDS.get(_BANNER_KEY)
    if fid:
        return fid
    try:
        return (app.settings.assets_path / "ui" / "welcome.jpg").read_bytes()
    except OSError:
        # No banner asset present — generate a plain one so the photo message can still send.
        from PIL import Image

        buf = io.BytesIO()
        Image.new("RGB", (1280, 720), (30, 31, 41)).save(buf, format="JPEG")
        return buf.getvalue()


def _remember_banner(msg) -> None:
    try:
        if msg is not None and getattr(msg, "photo", None):
            _FILE_IDS.put(_BANNER_KEY, msg.photo[-1].file_id)
    except Exception:  # noqa: BLE001 - caching is best-effort
        pass


def _remember_state(context: ContextTypes.DEFAULT_TYPE, uid: str, page: int, char_id: str | None) -> None:
    """Persist lightweight per-user navigation state (current uid/page/selected character)."""
    context.user_data["myc"] = {"uid": uid, "page": page, "char": char_id, "ts": time.time()}


# --------------------------------------------------------------------------- commands
@guard
@with_action(ChatAction.UPLOAD_PHOTO)
async def my_characters(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handler for **both** ``/mycharacters`` and its ``/myc`` alias.

    The two commands are registered against this single function (see
    :func:`bot.main._register_handlers`), so there is exactly one implementation, one data
    pipeline and one output format — ``/myc`` cannot drift from ``/mycharacters``.
    """
    app = get_app(context)
    lang = await resolve_language(update, context)
    tg_id = user_id_of(update)
    if tg_id is None:
        return
    # require_uid raises AccountNotLinked (handled by @guard) when no UID is linked, and
    # InvalidUID for a malformed stored value — the two are reported differently.
    uid = await app.account_service.require_uid(tg_id)
    logger.info("[MYCHARACTERS] UID: %s", uid)
    await _open_showcase(update, app, uid, viewer_uid=uid, owner=tg_id, lang=lang)


@guard
@with_action(ChatAction.UPLOAD_PHOTO)
async def inspect(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    app = get_app(context)
    lang = await resolve_language(update, context)
    if not context.args:
        await update.message.reply_text(t("inspect.usage", lang), parse_mode=ParseMode.HTML)
        return
    from bot.services.account_service import validate_uid

    uid = validate_uid(context.args[0])  # raises InvalidUID -> handled by @guard
    tg_id = user_id_of(update)
    viewer_uid = await app.account_service.get_uid(tg_id) if tg_id else None
    await _open_showcase(update, app, uid, viewer_uid=viewer_uid, owner=tg_id or 0, lang=lang)


async def _open_showcase(
    update: Update, app: AppContext, uid: str, *, viewer_uid: str | None, owner: int, lang: str
) -> None:
    """Send the initial one-message showcase: a banner photo whose caption is the list."""
    showcase = await app.character_service.get_showcase(uid, lang)
    text, markup = _render_list(showcase, uid, page=0, lang=lang, viewer_uid=viewer_uid, owner=owner)
    photo = _banner_photo(app)
    sent = await update.message.reply_photo(
        photo=_photo_arg(photo), caption=text, parse_mode=ParseMode.HTML, reply_markup=markup
    )
    _remember_banner(sent)


# --------------------------------------------------------------------------- callback router
async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle inline-button presses for the character-browsing flow (edits one message)."""
    query = update.callback_query
    if query is None:
        return

    started = time.perf_counter()
    # Answer FIRST — before any Redis/API work — so the button never spins and Telegram can
    # never reject a late answer as "query too old" (the cause of the intermittent error).
    try:
        await query.answer()
    except Exception:  # noqa: BLE001
        pass

    perf_logger.info("callback received: %s", query.data)
    app = get_app(context)
    cb = callbacks.decode(query.data or "")
    lang = "en"
    try:
        if cb.action == callbacks.ACTION_NOOP:
            return

        async with atimed("callback.redis_read"):
            lang = await resolve_language(update, context)

        if cb.action == callbacks.ACTION_CHAR:
            await _show_character(app, context, query, cb, lang)
        else:  # BACK / LIST / PAGE all resolve to showing the list
            await _show_list(app, context, query, cb, lang)
        perf_logger.info("callback processed: %s", cb.action)
    except BotError as exc:
        await _try_alert(query, t(exc.i18n_key, lang))
    except Exception:  # noqa: BLE001 - never crash on a button press
        logger.exception("Callback failed")
        await _try_alert(query, t("error.generic", lang))
    finally:
        perf_logger.info(
            "my_characters callback total: %.0f ms", (time.perf_counter() - started) * 1000
        )


async def _try_alert(query, text: str) -> None:
    """Best-effort error popup. The query is already answered, so this may be a no-op."""
    try:
        await query.answer(text, show_alert=True)
    except Exception:  # noqa: BLE001
        pass


# --------------------------------------------------------------------------- views (edit in place)
async def _show_character(app: AppContext, context, query, cb, lang: str) -> None:
    """Edit the current message into the character card (media + caption + Back)."""
    async with atimed("callback.showcase_get"):
        showcase = await app.character_service.get_showcase(cb.uid, lang)
    character = showcase.get_character(cb.char_id)
    if character is None:
        await _try_alert(query, t("error.character_not_found", lang))
        return

    caption = _build_caption(character, showcase.player, lang)
    back_kb = InlineKeyboardMarkup(
        [[InlineKeyboardButton(
            t("common.back", lang),
            callback_data=callbacks.encode(callbacks.ACTION_BACK, uid=cb.uid, page=cb.page, owner=cb.owner),
        )]]
    )

    key = (cb.uid, cb.char_id, lang)
    file_id = _FILE_IDS.get(key)
    if file_id is not None:
        perf_logger.info("card image cache HIT %s", key)
        photo: str | bytes = file_id
    else:
        perf_logger.info("card image cache MISS %s", key)
        photo = await _render_card_png(app, character, showcase.player, lang)

    result = await _edit_media(query, photo, caption, back_kb)
    _cache_result_file_id(key, result)
    _remember_state(context, cb.uid, cb.page, cb.char_id)


async def _show_list(app: AppContext, context, query, cb, lang: str) -> None:
    """Edit the current message back into the character list at ``cb.page``."""
    tg_id = query.from_user.id if query.from_user else None
    viewer_uid = await app.account_service.get_uid(tg_id) if tg_id else None

    async with atimed("callback.showcase_get"):
        showcase = await app.character_service.get_showcase(cb.uid, lang)
    text, markup = _render_list(
        showcase, cb.uid, page=cb.page, lang=lang, viewer_uid=viewer_uid, owner=cb.owner
    )

    msg = query.message
    is_photo = bool(msg is not None and getattr(msg, "photo", None))

    if is_photo and cb.action == callbacks.ACTION_PAGE:
        # The banner is already shown; only the caption + buttons change (cheapest edit).
        await _safe_edit(query.edit_message_caption(
            caption=text, parse_mode=ParseMode.HTML, reply_markup=markup
        ))
    elif is_photo:
        # Coming back from a character card: swap the media back to the banner.
        result = await _edit_media(query, _banner_photo(app), text, markup)
        _remember_banner(result)
    else:
        # Legacy text message (created before this version): edit text in place.
        await _safe_edit(query.edit_message_text(
            text, reply_markup=markup, parse_mode=ParseMode.HTML
        ))
    _remember_state(context, cb.uid, cb.page, None)


async def _render_card_png(app: AppContext, character: Character, player: PlayerInfo | None, lang: str) -> bytes:
    """Render a character card to PNG bytes (assets prefetched concurrently; render off-loop)."""
    icon_urls: list[str] = []
    if character.weapon and character.weapon.icon:
        icon_urls.append(character.weapon.icon)
    icon_urls += [tal.icon for tal in character.talents if tal.icon]
    icon_urls += [n.icon for n in character.constellations if n.icon]
    icon_urls += [a.icon for a in character.artifacts if a.icon]
    async with atimed("artwork.prefetch"):
        portrait, icons = await asyncio.gather(
            app.artwork_service.get_portrait(character),
            app.artwork_service.get_images(icon_urls),
        )
    # Production path: normalize -> slot-driven renderer -> 1536x864 PNG. The renderer does
    # no I/O; every asset above is already resolved by the artwork service.
    async with atimed("render.profile_card"):
        try:
            data = from_character(
                character, portrait=portrait, icons=icons,
                glow=theme_for(character.element)["glow"],
                adjustment=adjustment_for(character.id), player=player,
            )
            return await asyncio.to_thread(get_card_renderer().render, data)
        except Exception:  # noqa: BLE001 - never fail a card on a rendering bug
            logger.exception("[RENDERER] New renderer failed, using fallback renderer")
            return await asyncio.to_thread(
                app.renderer.render_profile_card,
                CharacterCardContext(
                    language=lang, character=character, player=player,
                    portrait=portrait, icons=icons,
                ),
            )


async def _edit_media(query, photo: str | bytes, caption: str, markup: InlineKeyboardMarkup):
    """editMessageMedia with the given photo/caption/markup, with graceful fallbacks.

    Falls back to a stripped (standard-emoji) caption if custom emoji are rejected, and — only
    if the message genuinely can't be edited into media (e.g. a legacy text message) — to
    sending a photo so the user still gets a result.
    """
    def media(cap: str) -> InputMediaPhoto:
        return InputMediaPhoto(media=_photo_arg(photo), caption=cap, parse_mode=ParseMode.HTML)

    try:
        return await query.edit_message_media(media=media(caption), reply_markup=markup)
    except BadRequest as exc:
        fallback = strip_custom_emoji(caption)
        if fallback != caption:
            try:
                return await query.edit_message_media(media=media(fallback), reply_markup=markup)
            except BadRequest as exc2:
                exc = exc2
        logger.info("edit_message_media failed (%s); sending photo fallback", exc)
        return await query.message.reply_photo(
            photo=_photo_arg(photo), caption=strip_custom_emoji(caption),
            parse_mode=ParseMode.HTML, reply_markup=markup,
        )


def _cache_result_file_id(key, result) -> None:
    """Remember the Telegram file_id of an edited/sent photo so we can reuse it later."""
    try:
        if result is not None and getattr(result, "photo", None):
            _FILE_IDS.put(key, result.photo[-1].file_id)
    except Exception:  # noqa: BLE001
        pass


async def _safe_edit(coro) -> None:
    """Await an edit coroutine, swallowing 'message is not modified'-style errors."""
    try:
        await coro
    except BadRequest as exc:
        logger.debug("edit ignored: %s", exc)
    except Exception as exc:  # noqa: BLE001
        logger.debug("edit failed: %s", exc)


def _build_caption(character: Character, player: PlayerInfo | None, lang: str = "en") -> str:
    """Build the profile-card caption.

    Akasha ranks only the builds it has a damage calculation for, so a character can be fully
    resolved by Enka and still have no placement — a newly released one always will, until
    akasha.cv adds it. That state is shown as an explicit "not available" rather than as a
    fabricated ``#--`` / ``--%``, which read like a real (zero) result. The layout, emoji and
    ordering are unchanged.
    """
    r = character.ranking
    unavailable = t("characters.unavailable", lang)
    # When a value exists the line reads exactly as it always did ("Rank: #2,147",
    # "Top 0.8%"); only the missing case changes, dropping the now-meaningless "#" and "%".
    rank_line = f"Rank: #{r.rank:,}" if (r and r.rank is not None) else f"Rank: {unavailable}"
    top_line = (
        f"Top {r.top_percent:.1f}%" if (r and r.top_percent is not None) else f"Top: {unavailable}"
    )
    category = r.calculation_name if (r and r.calculation_name) else unavailable
    name = html.escape(character.name or unavailable)
    nickname = html.escape(player.nickname if (player and player.nickname) else "--")
    category = html.escape(category)
    return (
        f'<tg-emoji emoji-id="4911241630633165627">⚔️</tg-emoji> {name}\n\n'
        f'<tg-emoji emoji-id="5255835635704408236">👤</tg-emoji> {nickname}\n\n'
        f"Akasha.cv Overview\n\n"
        f'<tg-emoji emoji-id="5413566144986503832">🏆</tg-emoji> {rank_line}\n\n'
        f'<tg-emoji emoji-id="4958489311726011319">✨</tg-emoji> {top_line}\n\n'
        f'<tg-emoji emoji-id="5818800359518247381">🏅</tg-emoji> Category: {category}'
    )


# --------------------------------------------------------------------------- list rendering
def _render_list(
    showcase: Showcase, uid: str, *, page: int, lang: str, viewer_uid: str | None, owner: int = 0
) -> tuple[str, InlineKeyboardMarkup]:
    chars = showcase.characters
    if not chars:
        raise _empty_showcase_error()

    total_pages = max(1, (len(chars) + PAGE_SIZE - 1) // PAGE_SIZE)
    page = max(0, min(page, total_pages - 1))
    start = page * PAGE_SIZE
    page_chars = chars[start : start + PAGE_SIZE]

    is_own = viewer_uid is not None and viewer_uid == uid
    title = t("characters.title", lang) if is_own else t("characters.title_other", lang, uid=uid)
    text = f"{title}\n{t('characters.page', lang, current=page + 1, total=total_pages)}"

    # Character buttons, arranged in rows of COLUMNS.
    rows: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for c in page_chars:
        label = f"{c.name} (Lv.{c.level} C{c.constellation})"
        row.append(
            InlineKeyboardButton(
                label,
                callback_data=callbacks.encode(
                    callbacks.ACTION_CHAR, uid=uid, char_id=c.id, page=page, owner=owner
                ),
            )
        )
        if len(row) == COLUMNS:
            rows.append(row)
            row = []
    if row:
        rows.append(row)

    # Pagination row (only when more than one page).
    if total_pages > 1:
        nav: list[InlineKeyboardButton] = []
        if page > 0:
            nav.append(
                InlineKeyboardButton(
                    t("common.prev", lang),
                    callback_data=callbacks.encode(callbacks.ACTION_PAGE, uid=uid, page=page - 1, owner=owner),
                )
            )
        if page < total_pages - 1:
            nav.append(
                InlineKeyboardButton(
                    t("common.next", lang),
                    callback_data=callbacks.encode(callbacks.ACTION_PAGE, uid=uid, page=page + 1, owner=owner),
                )
            )
        if nav:
            rows.append(nav)

    return text, InlineKeyboardMarkup(rows)


def _empty_showcase_error() -> BotError:
    from bot.utils.errors import EmptyShowcase

    return EmptyShowcase()
