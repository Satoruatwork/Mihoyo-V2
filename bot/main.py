"""Bot entrypoint: build the Application, wire handlers, and start polling.

Run with::

    python -m bot.main

Requires ``BOT_TOKEN`` in the environment / ``.env``.
"""

from __future__ import annotations

import sys

from telegram import Update
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CallbackQueryHandler,
    ChatMemberHandler,
    CommandHandler,
    ContextTypes,
    TypeHandler,
)

from bot.app_context import BOT_DATA_KEY, build_app_context
from bot.commands import (
    abyss,
    account,
    banner,
    broadcast,
    build_guide,
    characters,
    hoyolab_auth,
    ownership,
    redeem,
    settings_lang,
    start_help,
    stats,
    theater,
    tracking,
)
from bot.config import get_settings
from bot.database.redis_client import mask_url, validate_redis_url
from bot.translations.i18n import t
from bot.utils.logging import configure_logging, get_logger

logger = get_logger(__name__)

# Diagnostic Telegram user id used for the startup store round-trip. Not a real user;
# its keys are written and immediately deleted so live data is never touched.
_DIAG_TID = 0


async def _bootstrap_assets() -> None:
    """Download the card template + font. Never lets an asset failure crash startup."""
    try:
        from bot.assets.bootstrap import ensure_card_assets

        await ensure_card_assets()
        logger.info("Startup step 1/5: asset bootstrap complete")
    except Exception as exc:  # noqa: BLE001 - assets are best-effort (renderer has fallbacks)
        logger.warning(
            "Startup step 1/5: asset bootstrap failed (%s: %s) — continuing with "
            "placeholders/default font", type(exc).__name__, exc, exc_info=True,
        )


async def _store_round_trip(application: Application, redis_ok: bool = True) -> None:
    """Store + read back a Telegram user id, linked UID, language and setting, then clean up.

    Runs immediately after connecting so a broken persistence path is visible in the
    startup logs rather than only when a real user hits a command. Best-effort; never raises.
    ``redis_ok`` is only used to label which backend actually served the round-trip, so the
    log is never misread as "Redis works" when it was really the local fallback.
    """
    app_ctx = application.bot_data[BOT_DATA_KEY]
    store = app_ctx.users
    backend = "Redis" if redis_ok else "LOCAL FALLBACK (not Redis)"
    try:
        await store.get_or_create(_DIAG_TID, app_ctx.settings.default_language)
        await store.link_uid(_DIAG_TID, "800000000", app_ctx.settings.default_language)
        await store.set_language(_DIAG_TID, "en", app_ctx.settings.default_language)
        await store.set_setting(_DIAG_TID, "diag", "1")

        uid = await store.get_uid(_DIAG_TID)
        lang = await store.get_language(_DIAG_TID, app_ctx.settings.default_language)
        setting = await store.get_setting(_DIAG_TID, "diag")
        ok = uid == "800000000" and lang == "en" and setting == "1"
        logger.info(
            "Startup step 4/5: store round-trip via %s | uid=%r language=%r setting=%r -> %s",
            backend, uid, lang, setting, "PASS" if ok else "FAIL",
        )
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "Startup step 4/5: store round-trip FAILED (%s: %s)",
            type(exc).__name__, exc, exc_info=True,
        )
    finally:
        # Clean up the diagnostic keys regardless of outcome.
        try:
            client = app_ctx.redis.client
            await client.delete(f"user:{_DIAG_TID}", f"user:{_DIAG_TID}:settings")
            await client.srem("users", _DIAG_TID)
        except Exception as exc:  # noqa: BLE001
            logger.debug("Diagnostic key cleanup skipped: %s", exc)


async def _post_init(application: Application) -> None:
    """Build the dependency container and verify Redis before serving traffic.

    Hardened so that *no* initialization failure can prevent the bot from reaching
    ``run_polling``: every step is logged, every exception is captured with a traceback,
    and the app context is always installed so command handlers can run (degraded, if
    Redis is down) instead of KeyError-ing.
    """
    logger.info("=== Bot initialization starting ===")

    # Step 1: assets (best-effort; guarded internally).
    await _bootstrap_assets()

    # Step 2: dependency container (Redis pool, services, API clients, renderer).
    try:
        app_ctx = build_app_context(get_settings())
        application.bot_data[BOT_DATA_KEY] = app_ctx
        # Warm static resources ONCE now so per-command latency excludes them:
        # locale files (JSON) and the render template + common fonts.
        from bot.translations.i18n import preload_locales

        preload_locales()
        app_ctx.renderer.warmup()
        logger.info("Startup step 2/5: dependency container built + static caches warmed")
    except Exception:
        logger.critical(
            "Startup step 2/5: FAILED to build dependency container. The bot cannot "
            "serve commands. Most likely REDIS_URL is malformed — see the error below.",
            exc_info=True,
        )
        # Re-raise: without a context there is nothing to serve, and PTB will surface
        # this clearly instead of the bot silently accepting updates it can't handle.
        raise

    # Step 3: verify Redis + full CRUD self-test (connection/read/write/delete/ping).
    redis_ok = await app_ctx.redis.verify()
    if redis_ok:
        logger.info("Startup step 3/5: Redis (primary datastore) is connected")
        await app_ctx.redis.self_test()
    else:
        logger.error(
            "Startup step 3/5: Redis connection could not be verified — running in "
            "DEGRADED mode. Persistence and stats are unavailable until Redis recovers; "
            "command handlers still run."
        )

    # Step 4: persistence round-trip (user id / uid / language / settings).
    await _store_round_trip(application, redis_ok)

    # Step 5: publish the command menu (best-effort).
    await _set_bot_commands(application)
    logger.info("Startup step 5/5: command menu published")

    # One unambiguous line stating where user data actually lives.
    if redis_ok:
        logger.info("DATABASE STATUS: CONNECTED (Redis) — logins persist across redeploys.")
    else:
        logger.error(
            "DATABASE STATUS: NOT CONNECTED — using the LOCAL FALLBACK file. Logins will "
            "NOT survive a redeploy until REDIS_URL points at a reachable database. "
            "Run scripts/check_redis.py to diagnose."
        )

    # Last line before PTB's updater begins fetching updates.
    logger.info("Bot started successfully — beginning long-polling for updates")


async def _post_shutdown(application: Application) -> None:
    logger.info("Shutdown: closing Redis pool and pooled HTTP sessions")
    app_ctx = application.bot_data.get(BOT_DATA_KEY)
    if app_ctx is not None:
        try:
            await app_ctx.aclose()
            logger.info("Shutdown: resources released")
        except Exception:  # noqa: BLE001
            logger.warning("Shutdown: error releasing resources", exc_info=True)


async def _set_bot_commands(application: Application) -> None:
    """Publish the command list shown in Telegram's UI (best-effort)."""
    commands = [
        ("start", "Start the bot"),
        ("help", "Show help"),
        ("genshinlogin", "Link your Genshin UID"),
        ("genshinlogout", "Unlink your account"),
        ("myuid", "Show your linked UID"),
        ("myinfo", "Show your account info"),
        ("mycharacters", "Browse your showcased characters"),
        ("myc", "Browse your showcased characters"),
        ("inspect", "Inspect another player's showcase"),
        ("abyss", "Spiral Abyss"),
        ("preabyss", "Previous Spiral Abyss"),
        ("abysscard", "Spiral Abyss card"),
        ("preabysscard", "Previous Spiral Abyss card"),
        ("theater", "Imaginarium Theater"),
        ("theatercard", "Imaginarium Theater card"),
        ("hoyologin", "Link your HoYoLAB account (DM only)"),
        ("hoyologout", "Unlink your HoYoLAB account"),
        ("redeem", "Redeem a Genshin gift code"),
        ("banner", "Banner information"),
        ("build_guide", "Build recommendations"),
        ("settings", "Your settings"),
        ("language", "Change language"),
        ("stats", "Bot statistics"),
    ]
    try:
        await application.bot.set_my_commands(commands)
    except Exception as exc:  # noqa: BLE001 - non-critical
        logger.warning("Failed to set bot commands: %s", exc)


async def _on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Global error handler — last line of defence so the bot never crashes."""
    logger.exception("Unhandled exception", exc_info=context.error)
    try:
        if isinstance(update, Update) and update.effective_message is not None:
            await update.effective_message.reply_text(t("error.generic", "en"))
    except Exception:  # noqa: BLE001
        pass


def _register_handlers(application: Application) -> None:
    # --- universal ownership gate (group=-2: runs before tracking and all callback
    #     handlers; blocks non-owners from operating another user's inline keyboard) ---
    application.add_handler(CallbackQueryHandler(ownership.enforce_callback_owner), group=-2)

    # --- tracking (group=-1 so it runs first, then command handlers in group 0 also run) ---
    application.add_handler(TypeHandler(Update, tracking.track), group=-1)
    application.add_handler(
        ChatMemberHandler(tracking.on_my_chat_member, ChatMemberHandler.MY_CHAT_MEMBER)
    )

    # --- simple commands ---
    application.add_handler(CommandHandler("start", start_help.start))
    application.add_handler(CommandHandler("help", start_help.help_command))
    application.add_handler(CommandHandler("stats", stats.stats))

    # --- account ---
    application.add_handler(CommandHandler("genshinlogin", account.genshin_login))
    application.add_handler(CommandHandler("genshinlogout", account.genshin_logout))
    application.add_handler(CommandHandler("myuid", account.my_uid))
    application.add_handler(CommandHandler("myinfo", account.my_info))

    # --- characters (with /myc alias) ---
    application.add_handler(CommandHandler(["mycharacters", "myc"], characters.my_characters))
    application.add_handler(CommandHandler("inspect", characters.inspect))

    # --- abyss ---
    application.add_handler(CommandHandler("abyss", abyss.abyss))
    application.add_handler(CommandHandler("preabyss", abyss.pre_abyss))
    application.add_handler(CommandHandler("abysscard", abyss.abyss_card))
    application.add_handler(CommandHandler("preabysscard", abyss.pre_abyss_card))

    # --- theater ---
    application.add_handler(CommandHandler("theater", theater.theater))
    application.add_handler(CommandHandler("theatercard", theater.theater_card))

    # --- HoYoLAB account linking + redemption ---
    application.add_handler(CommandHandler("hoyologin", hoyolab_auth.hoyologin))
    application.add_handler(CommandHandler("hoyologout", hoyolab_auth.hoyologout))
    application.add_handler(CommandHandler("hoyostatus", hoyolab_auth.hoyostatus))
    application.add_handler(CommandHandler("redeem", redeem.redeem))

    # --- admin (owner-only; intentionally NOT published in the command menu) ---
    application.add_handler(CommandHandler("broadcast", broadcast.broadcast))

    # --- misc ---
    application.add_handler(CommandHandler("banner", banner.banner))
    application.add_handler(CommandHandler("build_guide", build_guide.build_guide))
    application.add_handler(CommandHandler("settings", settings_lang.settings))
    application.add_handler(CommandHandler("language", settings_lang.language))

    # --- callback queries (order matters: most specific first) ---
    application.add_handler(
        CallbackQueryHandler(settings_lang.on_settings_menu_callback, pattern=r"^lang:__menu__")
    )
    application.add_handler(CallbackQueryHandler(settings_lang.on_language_callback, pattern=r"^lang:"))
    application.add_handler(
        CallbackQueryHandler(characters.on_callback, pattern=r"^(list|char|page|back|noop)\|")
    )

    application.add_error_handler(_on_error)


def _validate_environment(settings) -> None:
    """Fail fast with a clear, actionable message if required config is missing/invalid."""
    if not settings.bot_token:
        logger.critical(
            "BOT_TOKEN is not set. On the deployment platform set the BOT_TOKEN env var "
            "(from @BotFather); locally, copy .env.example to .env and set it."
        )
        sys.exit(1)
    if not settings.redis_url:
        logger.critical(
            "REDIS_URL is not set. Redis is the primary datastore; set the REDIS_URL env "
            "var to your Upstash 'Redis' connection URL "
            "(rediss://default:<password>@<host>:6379)."
        )
        sys.exit(1)

    ok, message = validate_redis_url(settings.redis_url)
    if not ok:
        logger.critical("REDIS_URL is invalid: %s", message)
        sys.exit(1)
    logger.info("Environment validated: BOT_TOKEN present, REDIS_URL=%s", mask_url(settings.redis_url))


def build_application() -> Application:
    settings = get_settings()
    _validate_environment(settings)

    application = (
        ApplicationBuilder()
        .token(settings.bot_token)
        .post_init(_post_init)
        .post_shutdown(_post_shutdown)
        .build()
    )
    _register_handlers(application)
    logger.info("Registered command/callback handlers")
    return application


def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    logger.info("Starting Genshin Impact Telegram bot")
    try:
        application = build_application()
        # run_polling drives initialize -> _post_init -> updater start_polling (blocking).
        # "Bot started successfully" is logged at the tail of _post_init, immediately
        # before the updater begins fetching updates.
        logger.info("Handing control to run_polling()")
        application.run_polling(allowed_updates=Update.ALL_TYPES)
    except SystemExit:
        raise
    except Exception:
        logger.critical("Fatal error during startup/polling", exc_info=True)
        raise
    finally:
        logger.info("Bot process shutting down")


if __name__ == "__main__":
    main()
