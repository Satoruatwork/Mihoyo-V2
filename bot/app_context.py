"""Application context: the dependency container shared across all handlers.

Built once at startup and stored on ``Application.bot_data``. Handlers pull services from
here instead of constructing them, which keeps handlers thin and makes wiring/testing easy.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from bot.api.akasha_client import AkashaClient
from bot.api.enka_client import EnkaClient
from bot.api.hoyolab_client import HoyolabRedeemer
from bot.cache.redis_cache import RedisCache
from bot.config import Settings, get_settings
from bot.database.local_store import LocalStore
from bot.database.redis_client import RedisClient
from bot.database.store import RedisStore
from bot.utils.crypto import CookieCipher
from bot.renderer.base import Renderer, get_renderer
from bot.services.abyss_service import AbyssService
from bot.services.account_service import AccountService
from bot.services.banner_service import BannerService
from bot.services.broadcast_service import BroadcastService
from bot.services.build_service import BuildService
from bot.services.artwork_service import ArtworkService
from bot.services.character_service import CharacterService
from bot.services.hoyolab_auth_service import HoyolabAuthService
from bot.services.redemption_service import RedemptionService
from bot.services.stats_service import StatsService
from bot.services.theater_service import TheaterService

# Key under which the context is stored in Application.bot_data.
BOT_DATA_KEY = "app_ctx"


@dataclass
class AppContext:
    settings: Settings
    redis: RedisClient
    users: RedisStore  # primary persistent store (users, UIDs, language, settings, groups, stats)
    account_service: AccountService
    character_service: CharacterService
    abyss_service: AbyssService
    theater_service: TheaterService
    banner_service: BannerService
    build_service: BuildService
    redemption_service: RedemptionService
    hoyolab_auth: HoyolabAuthService
    broadcast_service: BroadcastService
    stats_service: StatsService
    artwork_service: ArtworkService
    akasha: AkashaClient  # held so its pooled HTTP session can be closed on shutdown
    renderer: Renderer
    started_at: float

    async def language_for(self, telegram_user_id: int) -> str:
        """Resolve a user's preferred language (defaulting to the configured default)."""
        return await self.users.get_language(telegram_user_id, self.settings.default_language)

    async def aclose(self) -> None:
        """Release shared resources (Redis pool + pooled HTTP sessions). Never raises."""
        await self.redis.close()
        await self.artwork_service.aclose()
        await self.akasha.aclose()
        # The character metadata resolver is a process-wide singleton (it mirrors enka.py's
        # own singleton assets), so it is closed here rather than held as a field.
        from bot.api.character_metadata import get_metadata_resolver

        await get_metadata_resolver().aclose()


def build_app_context(settings: Settings | None = None) -> AppContext:
    """Construct the full dependency graph."""
    settings = settings or get_settings()

    redis = RedisClient(
        settings.redis_url,
        connect_timeout=settings.redis_connect_timeout,
        socket_timeout=settings.redis_socket_timeout,
        retries=settings.redis_retries,
    )
    # Local fallback keeps logins/settings working (and fast) when Redis is unreachable.
    fallback = LocalStore(settings.local_store_file)
    store = RedisStore(redis.client, fallback=fallback, breaker_cooldown=settings.redis_breaker_cooldown)
    showcase_cache = RedisCache(redis.client, ttl=settings.enka_cache_ttl, prefix="cache")

    enka = EnkaClient(language=settings.default_language)
    akasha = AkashaClient()

    started_at = time.time()

    account_service = AccountService(store, default_language=settings.default_language)
    character_service = CharacterService(enka, akasha, showcase_cache, ttl=settings.enka_cache_ttl)
    abyss_service = AbyssService(character_service)
    theater_service = TheaterService(character_service)
    banner_service = BannerService()
    build_service = BuildService()
    redemption_service = RedemptionService(HoyolabRedeemer(settings.hoyolab_cookie))
    hoyolab_auth = HoyolabAuthService(store, CookieCipher(settings.session_secret))
    broadcast_service = BroadcastService(store)
    stats_service = StatsService(store, redis, started_at)
    artwork_service = ArtworkService()

    return AppContext(
        settings=settings,
        redis=redis,
        users=store,
        account_service=account_service,
        character_service=character_service,
        abyss_service=abyss_service,
        theater_service=theater_service,
        banner_service=banner_service,
        build_service=build_service,
        redemption_service=redemption_service,
        hoyolab_auth=hoyolab_auth,
        broadcast_service=broadcast_service,
        stats_service=stats_service,
        artwork_service=artwork_service,
        akasha=akasha,
        renderer=get_renderer(),
        started_at=started_at,
    )
