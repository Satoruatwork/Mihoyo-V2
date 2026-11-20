"""Character showcase business logic.

Aggregates Enka showcase data with best-effort Akasha rankings, caches the combined result
per UID in Redis (as JSON, so it persists across restarts and respects rate limits), and
exposes helpers the command layer uses for the browsing flow. No Telegram or rendering here.
"""

from __future__ import annotations

import asyncio
import time

from bot.api.akasha_client import AkashaClient
from bot.api.character_metadata import is_placeholder_name
from bot.api.enka_client import EnkaClient
from bot.cache.redis_cache import RedisCache
from bot.models.character import Character
from bot.models.player import Showcase
from bot.models.ranking import Ranking
from bot.models.serialize import showcase_from_dict, showcase_to_dict
from bot.utils.errors import CharacterNotFound
from bot.utils.logging import get_logger
from bot.utils.timing import atimed

logger = get_logger(__name__)
perf_logger = get_logger("bot.perf")

_CACHE_NS = "showcase"
_MEM_MAX = 64  # showcases kept in the in-process cache
_UNRESOLVED_TTL = 60  # seconds to cache a showcase that still has an unnamed character


class CharacterService:
    """Fetches, enriches, and caches player showcases.

    Two cache tiers sit in front of the (Enka + Akasha) fetch:
      1. a tiny in-process memory cache — instant, and keeps rapid inline navigation fast
         even when Redis is unavailable (no per-click network round-trip);
      2. the shared Redis cache — survives restarts and is shared across workers.
    """

    def __init__(
        self,
        enka: EnkaClient,
        akasha: AkashaClient,
        cache: RedisCache,
        ttl: int = 300,
    ) -> None:
        self._enka = enka
        self._akasha = akasha
        self._cache = cache
        self._ttl = ttl
        self._mem: dict[str, tuple[float, Showcase]] = {}

    def _mem_get(self, key: str) -> Showcase | None:
        entry = self._mem.get(key)
        if entry is None:
            return None
        ts, showcase = entry
        if (time.monotonic() - ts) > self._ttl:
            self._mem.pop(key, None)
            return None
        return showcase

    def _mem_put(self, key: str, showcase: Showcase) -> None:
        self._mem[key] = (time.monotonic(), showcase)
        if len(self._mem) > _MEM_MAX:
            for old, _ in sorted(self._mem.items(), key=lambda kv: kv[1][0])[
                : len(self._mem) - _MEM_MAX
            ]:
                self._mem.pop(old, None)

    async def get_showcase(self, uid: str, language: str = "en") -> Showcase:
        """Return a cached (or freshly fetched + enriched) showcase for a UID.

        Checks the in-memory cache first (instant), then Redis, then fetches. On a cache miss
        the Enka showcase fetch and the (independent) Akasha ranking fetch are issued
        **concurrently**, so a fresh lookup costs roughly ``max(enka, akasha)`` not the sum.
        """
        cache_key = f"{language}:{uid}"

        # Tier 1: in-process memory (instant; works even when Redis is down).
        cached_mem = self._mem_get(cache_key)
        if cached_mem is not None:
            perf_logger.info("showcase memory cache HIT %s", cache_key)
            return cached_mem
        perf_logger.info("showcase memory cache MISS %s", cache_key)

        # Tier 2: shared Redis cache.
        async with atimed("showcase.cache_read"):
            cached = await self._cache.get_json(_CACHE_NS, cache_key)
        if cached is not None:
            try:
                showcase = showcase_from_dict(cached)
                self._mem_put(cache_key, showcase)
                return showcase
            except Exception as exc:  # noqa: BLE001 - corrupt cache -> refetch
                logger.debug("Discarding unreadable cached showcase for %s: %s", uid, exc)

        showcase, rankings = await self._fetch_concurrently(uid, language)
        self._attach_rankings(showcase, rankings)
        self._mem_put(cache_key, showcase)

        async with atimed("showcase.cache_write"):
            await self._cache.set_json(
                _CACHE_NS, cache_key, showcase_to_dict(showcase), ttl=self._cache_ttl_for(showcase)
            )
        return showcase

    def _cache_ttl_for(self, showcase: Showcase) -> int:
        """TTL for caching a showcase — shortened while any character is unnamed.

        A character whose metadata upstream hasn't published yet resolves to a placeholder
        name. Caching that for the full TTL would keep showing the placeholder long after
        upstream caught up, so those results are held only briefly.
        """
        if any(is_placeholder_name(c.name) for c in showcase.characters):
            ttl = min(self._ttl, _UNRESOLVED_TTL)
            logger.info(
                "[MYCHARACTERS] Showcase contains unresolved character(s); caching for %ds "
                "instead of %ds so newly published metadata is picked up promptly",
                ttl, self._ttl,
            )
            return ttl
        return self._ttl

    async def _fetch_concurrently(
        self, uid: str, language: str
    ) -> tuple[Showcase, dict[str, Ranking]]:
        """Fetch the Enka showcase and Akasha rankings in parallel.

        The Enka result is authoritative: any Enka domain error (private profile, empty
        showcase, rate limit, …) propagates unchanged. Akasha is best-effort — a failure or
        slow response yields empty rankings and never affects the showcase.
        """
        async def _enka() -> Showcase:
            async with atimed("showcase.enka_fetch"):
                return await self._enka.fetch_showcase(uid, language)

        async def _akasha() -> dict[str, Ranking]:
            async with atimed("showcase.akasha_fetch"):
                logger.info("[AKASHA] Fetching ranking data for UID %s", uid)
                try:
                    rankings = await self._akasha.fetch_rankings(uid)
                except Exception as exc:  # noqa: BLE001 - rankings must never break the flow
                    logger.info("[AKASHA] Unavailable for UID %s: %s", uid, exc)
                    return {}
                logger.info("[AKASHA] Rankings received for %d character(s)", len(rankings))
                return rankings

        showcase_res, rankings_res = await asyncio.gather(
            _enka(), _akasha(), return_exceptions=True
        )
        # Enka error is authoritative — re-raise it (Akasha result is discarded).
        if isinstance(showcase_res, BaseException):
            raise showcase_res
        rankings = {} if isinstance(rankings_res, BaseException) else rankings_res
        return showcase_res, rankings

    @staticmethod
    def _attach_rankings(showcase: Showcase, rankings: dict[str, Ranking]) -> None:
        """Attach Akasha rankings where they exist.

        Enka availability and Akasha availability are independent: Akasha only ranks builds
        it has a damage calculation for, so a character Enka resolves perfectly well may
        legitimately have no ranking — especially a newly released one. Those characters keep
        ``ranking is None`` and the card renders an explicit "unavailable" state rather than
        inventing a placement.
        """
        for character in showcase.characters:
            ranking = rankings.get(character.id)
            if ranking is not None and ranking.available:
                character.ranking = ranking
            else:
                logger.info(
                    "[AKASHA] Ranking unavailable for character: %s (id %s)",
                    character.name, character.id,
                )

    async def get_character(self, uid: str, char_id: str, language: str = "en") -> Character:
        """Return a single character from the (cached) showcase."""
        showcase = await self.get_showcase(uid, language)
        character = showcase.get_character(char_id)
        if character is None:
            raise CharacterNotFound(f"{char_id} not in showcase for {uid}")
        return character
