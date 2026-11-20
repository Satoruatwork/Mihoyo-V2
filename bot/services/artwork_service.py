"""Character artwork retrieval + local caching.

Akasha has no image API, so we use Enka's official character art (the same source
akasha.cv relies on): ``character.icon.gacha`` (full splash) with a fallback to the front
icon. Downloaded art is cached on disk (``assets/characters/<key>.png``) so new characters
work automatically and repeat renders don't re-download. Everything is best-effort: on any
failure the service returns ``None`` and the renderer shows the empty portrait frame.
"""

from __future__ import annotations

import asyncio
import io
from pathlib import Path

import aiohttp
from PIL import Image

from bot.config import get_settings
from bot.models.character import Character
from bot.utils.logging import get_logger

logger = get_logger(__name__)

_HEADERS = {"User-Agent": "Mozilla/5.0 (MihoyoBot)"}


class ArtworkService:
    def __init__(self) -> None:
        self._cache_dir = get_settings().assets_path / "characters"
        # A single pooled session is reused for every artwork/icon download instead of
        # opening a fresh TCP+TLS connection per image. Created lazily inside the running
        # event loop and closed on shutdown.
        self._session: aiohttp.ClientSession | None = None
        self._session_lock = asyncio.Lock()

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            async with self._session_lock:
                if self._session is None or self._session.closed:
                    connector = aiohttp.TCPConnector(limit=32, ttl_dns_cache=300)
                    self._session = aiohttp.ClientSession(
                        headers=_HEADERS,
                        timeout=aiohttp.ClientTimeout(total=30),
                        connector=connector,
                    )
        return self._session

    async def aclose(self) -> None:
        """Close the shared HTTP session (called on shutdown). Never raises."""
        if self._session is not None and not self._session.closed:
            try:
                await self._session.close()
            except Exception:  # noqa: BLE001
                pass
        self._session = None

    @staticmethod
    def _stem(key: str | None) -> str:
        """Filename stem of an art key/URL ('' when the key carries no filename)."""
        if not key:
            return ""
        return key.rsplit("/", 1)[-1].removesuffix(".png").removesuffix(".jpg")

    def _candidate_urls(self, character: Character) -> list[str]:
        """Prefer full splash art, then the front portrait icon.

        Keys without a filename are skipped: they would produce a URL like
        ``https://enka.network/ui/.png`` that is guaranteed to 404 and would waste a request
        on every render.
        """
        urls: list[str] = []
        # character.art / character.icon are reduced to filename keys in the mapper; we also
        # accept a full URL if present. Reconstruct Enka CDN URLs from the stored key.
        for key in (character.art, character.icon):
            if not key or not self._stem(key):
                continue
            urls.append(key if key.startswith("http") else f"https://enka.network/ui/{key}")
        return urls

    def _cache_file(self, character: Character) -> Path:
        stem = (
            self._stem(character.art)
            or self._stem(character.icon)
            or (character.id or "unknown")
        )
        return self._cache_dir / f"{stem}.png"

    async def get_portrait(self, character: Character) -> Image.Image | None:
        """Return the character's artwork as an RGBA image, or None if unavailable."""
        cache_file = self._cache_file(character)
        if cache_file.exists():
            try:
                return Image.open(cache_file).convert("RGBA")
            except Exception:  # noqa: BLE001 - corrupt cache -> refetch
                pass

        for url in self._candidate_urls(character):
            img = await self._download_image(url)
            if img is not None:
                try:
                    self._cache_dir.mkdir(parents=True, exist_ok=True)
                    img.save(cache_file)
                except Exception as exc:  # noqa: BLE001 - caching is non-critical
                    logger.debug("Could not cache portrait %s: %s", cache_file, exc)
                return img
        # Artwork is decoration, not identity: the card still renders (empty portrait frame)
        # with the character's name, stats, weapon and artifacts intact.
        logger.info(
            "No artwork available for character %s (id %s) — rendering without a portrait",
            character.name, character.id,
        )
        return None

    async def get_image(self, url: str | None) -> Image.Image | None:
        """Fetch any icon URL as an RGBA image, cached on disk by filename. None on failure."""
        if not url:
            return None
        fname = url.rsplit("/", 1)[-1] or "icon.png"
        if not fname.lower().endswith(".png"):
            fname += ".png"
        cache_file = self._cache_dir / fname
        if cache_file.exists():
            try:
                return Image.open(cache_file).convert("RGBA")
            except Exception:  # noqa: BLE001
                pass
        img = await self._download_image(url)
        if img is not None:
            try:
                self._cache_dir.mkdir(parents=True, exist_ok=True)
                img.save(cache_file)
            except Exception as exc:  # noqa: BLE001
                logger.debug("Could not cache icon %s: %s", cache_file, exc)
        return img

    async def get_images(self, urls) -> dict[str, Image.Image]:
        """Fetch many icon URLs concurrently; returns {url: image} for those that succeed."""
        import asyncio

        unique = [u for u in dict.fromkeys(urls) if u]
        results = await asyncio.gather(*(self.get_image(u) for u in unique), return_exceptions=True)
        out: dict[str, Image.Image] = {}
        for url, res in zip(unique, results):
            if isinstance(res, Image.Image):
                out[url] = res
        return out

    async def _download_image(self, url: str) -> Image.Image | None:
        try:
            session = await self._get_session()
            async with session.get(url) as resp:
                resp.raise_for_status()
                data = await resp.read()
            return Image.open(io.BytesIO(data)).convert("RGBA")
        except Exception as exc:  # noqa: BLE001 - best effort
            logger.debug("Artwork download failed (%s): %s", url, exc)
            return None
