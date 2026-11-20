"""Tests for the performance optimizations.

Cover the behaviors that must not regress:
  * Enka and Akasha fetches run concurrently (not sequentially) on a cache miss.
  * Static resources (banners/build guides) are read from disk once and cached.
  * HTTP clients reuse a single pooled session instead of one per request.
  * The renderer caches the decoded card template in memory.
"""

from __future__ import annotations

import asyncio
import time

from bot.api.akasha_client import AkashaClient
from bot.models.character import Character
from bot.models.player import PlayerInfo, Showcase
from bot.services.artwork_service import ArtworkService
from bot.services.banner_service import BannerService
from bot.services.build_service import BuildService
from bot.services.character_service import CharacterService


class _SlowEnka:
    def __init__(self, delay: float) -> None:
        self.delay = delay
        self.calls = 0

    async def fetch_showcase(self, uid: str, language: str = "en") -> Showcase:
        self.calls += 1
        await asyncio.sleep(self.delay)
        return Showcase(player=PlayerInfo(uid=uid), characters=[Character(id="1", name="A")])


class _SlowAkasha:
    def __init__(self, delay: float) -> None:
        self.delay = delay
        self.calls = 0

    async def fetch_rankings(self, uid: str) -> dict:
        self.calls += 1
        await asyncio.sleep(self.delay)
        return {}


class _MissCache:
    async def get_json(self, *a, **k):
        return None

    async def set_json(self, *a, **k):
        return None


async def test_enka_and_akasha_run_concurrently():
    enka, akasha = _SlowEnka(0.20), _SlowAkasha(0.20)
    svc = CharacterService(enka, akasha, _MissCache(), ttl=300)
    start = time.perf_counter()
    await svc.get_showcase("800000000", "en")
    elapsed = time.perf_counter() - start
    # Sequential would be ~0.40s; concurrent should be ~0.20s. Allow generous headroom.
    assert elapsed < 0.35, f"fetches did not overlap: {elapsed:.3f}s"
    assert enka.calls == 1 and akasha.calls == 1


async def test_enka_error_still_propagates_when_parallel():
    class _BoomEnka:
        async def fetch_showcase(self, uid, language="en"):
            raise ValueError("boom")

    svc = CharacterService(_BoomEnka(), _SlowAkasha(0.01), _MissCache(), ttl=300)
    try:
        await svc.get_showcase("800000000", "en")
    except ValueError as exc:
        assert str(exc) == "boom"
    else:  # pragma: no cover
        raise AssertionError("Enka error should propagate")


def test_banner_service_reads_disk_once():
    svc = BannerService()
    assert svc._cache is None
    asyncio.run(svc.get_banners())
    first = svc._cache
    assert first is not None
    asyncio.run(svc.get_banners())
    assert svc._cache is first  # same cached object, not re-read


def test_build_service_reads_disk_once():
    svc = BuildService()
    assert svc._cache is None
    asyncio.run(svc.get_guide("Ayaka"))
    assert svc._cache is not None


async def test_akasha_reuses_single_session():
    client = AkashaClient()
    s1 = await client._get_session()
    s2 = await client._get_session()
    assert s1 is s2
    await client.aclose()
    assert client._session is None


async def test_artwork_reuses_single_session():
    svc = ArtworkService()
    s1 = await svc._get_session()
    s2 = await svc._get_session()
    assert s1 is s2
    await svc.aclose()
    assert svc._session is None


def test_renderer_caches_template():
    from bot.renderer.pillow_renderer import PillowRenderer

    r = PillowRenderer()
    assert getattr(r, "_template_cache", None) is None
    base1 = r._template_base()
    assert r._template_cache is not None
    base2 = r._template_base()
    # Each caller gets its own copy, but the cached source is reused (not re-decoded).
    assert base1 is not base2
    assert base1.size == base2.size
