"""Dynamic character metadata resolution (avatar id -> name / element / rarity / art).

This is the compatibility layer that makes a *newly released* character work without a
source-code change. It is **not** a hardcoded character list: nothing here enumerates
characters, it only knows how to read the upstream metadata files that Enka publishes.

Resolution order (first hit wins), matching the preferred pipeline:

1. **enka.py's in-process metadata** — whatever the library already loaded into
   ``GI_ASSETS``. Free, no I/O, and normally the only step that runs.
2. **Upstream game metadata** — the exact files enka.py itself downloads
   (``enka-py-assets``), then Enka.Network's own ``API-docs`` store. Fetched over HTTP and
   held in a **short-lived, refreshable** cache, so once upstream publishes a new character
   the bot picks it up on its own.
3. **Local snapshot** — a small JSON file written whenever step 2 succeeds
   (``data/character_meta.json``). Purely a fallback for upstream outages; it is refreshed
   from upstream, never authoritative, and its absence is harmless.

Everything is best-effort and returns ``None`` rather than raising: a metadata miss must
degrade the *name* shown on the card, never the command.
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import aiohttp

from bot.utils.logging import get_logger

logger = get_logger(__name__)

# The two upstream metadata sources, in preference order. The first is what enka.py itself
# consumes (so it is always at least as fresh as the library); the second is Enka.Network's
# own published store, used when the first is unreachable.
_SOURCES: tuple[dict[str, str], ...] = (
    {
        "name": "enka-py-assets",
        "characters": "https://raw.githubusercontent.com/seriaati/enka-py-assets/main/data/characters.json",
        "text": "https://raw.githubusercontent.com/seriaati/enka-py-assets/main/data/text_map.json",
    },
    {
        "name": "enka-network-api-docs",
        "characters": "https://raw.githubusercontent.com/EnkaNetwork/API-docs/master/store/characters.json",
        "text": "https://raw.githubusercontent.com/EnkaNetwork/API-docs/master/store/loc.json",
    },
)

_HEADERS = {"User-Agent": "Mozilla/5.0 (MihoyoBot)", "Accept": "application/json"}

# Our language codes -> the codes upstream text maps use, most specific first. Upstream
# sources don't all carry every language (e.g. enka-py-assets has no Chinese), so each entry
# ends with English as a guaranteed fallback rather than failing to resolve a name at all.
_LANG_CANDIDATES: dict[str, tuple[str, ...]] = {
    "en": ("en",),
    "es": ("es", "en"),
    "it": ("it", "en"),
    "ja": ("ja", "en"),
    "zh": ("zh-cn", "zh-tw", "en"),
}

# QualityType -> star rarity. Unknown/new quality types fall through to ``None`` instead of
# raising (enka.py's own CHARACTER_RARITY_MAP raises a KeyError here).
_QUALITY_RARITY = {"QUALITY_ORANGE": 5, "QUALITY_ORANGE_SP": 5, "QUALITY_PURPLE": 4}


# Display name used when *no* source can name a character yet (a release upstream hasn't
# published). Defined here — with its matching predicate — so the string is written once and
# callers can recognise the state instead of pattern-matching a literal.
_PLACEHOLDER_PREFIX = "Character "


def placeholder_name(char_id: str) -> str:
    """Name shown for a character no metadata source resolves yet."""
    return f"{_PLACEHOLDER_PREFIX}{char_id}"


def is_placeholder_name(name: str | None) -> bool:
    """True when a name came from :func:`placeholder_name` rather than real metadata."""
    return (name or "").startswith(_PLACEHOLDER_PREFIX)


@dataclass(slots=True)
class CharacterMeta:
    """Resolved metadata for one character id."""

    id: str
    name: str | None = None
    element: str | None = None
    rarity: int | None = None
    side_icon: str | None = None      # e.g. "UI_AvatarIcon_Side_Odette" (no /ui/, no .png)
    weapon_type: str | None = None
    source: str = "unknown"           # which layer answered; used in logs

    @property
    def art_url(self) -> str | None:
        """Full splash art (gacha) URL derived from the side-icon path."""
        return _icon_url(self.side_icon, "gacha")

    @property
    def icon_url(self) -> str | None:
        """Front portrait icon URL derived from the side-icon path."""
        return _icon_url(self.side_icon, "front")


def _icon_url(side_icon: str | None, kind: str) -> str | None:
    """Derive a CDN URL from a side-icon path, mirroring enka.py's ``Icon`` model."""
    if not side_icon:
        return None
    side = f"https://enka.network/ui/{side_icon}.png"
    if kind == "gacha":
        return side.replace("AvatarIcon_Side", "Gacha_AvatarImg")
    if kind == "front":
        return side.replace("Side_", "")
    return side


def _normalize_icon_path(value: Any) -> str | None:
    """Strip the ``/ui/`` prefix and file extension that differ between sources."""
    if not isinstance(value, str) or not value:
        return None
    return value.removeprefix("/ui/").removesuffix(".png").removesuffix(".jpg") or None


class CharacterMetadataResolver:
    """Resolves character ids (and text-map hashes) to display metadata, dynamically.

    Args:
        ttl: Lifetime of the fetched upstream metadata. Kept short enough that a newly
            published character is picked up without a restart, long enough that the files
            aren't re-downloaded per command.
        snapshot_path: Where to persist the last good upstream metadata.
    """

    def __init__(self, ttl: float = 21_600.0, snapshot_path: Path | None = None) -> None:
        self._ttl = ttl
        self._snapshot_path = snapshot_path
        self._lock = asyncio.Lock()
        self._session: aiohttp.ClientSession | None = None
        self._session_lock = asyncio.Lock()

        # Fetched upstream payloads.
        self._characters: dict[str, Any] = {}
        self._text: dict[str, dict[str, str]] = {}
        self._source_name: str = "none"
        self._fetched_at: float = 0.0

    # -- lifecycle ---------------------------------------------------------
    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            async with self._session_lock:
                if self._session is None or self._session.closed:
                    self._session = aiohttp.ClientSession(
                        headers=_HEADERS, timeout=aiohttp.ClientTimeout(total=30)
                    )
        return self._session

    async def aclose(self) -> None:
        """Close the pooled HTTP session (called on shutdown). Never raises."""
        if self._session is not None and not self._session.closed:
            try:
                await self._session.close()
            except Exception:  # noqa: BLE001
                pass
        self._session = None

    def invalidate(self) -> None:
        """Drop the cached upstream payload so the next resolve re-fetches it."""
        self._fetched_at = 0.0

    # -- public API --------------------------------------------------------
    async def resolve(self, char_id: str, language: str = "en") -> CharacterMeta | None:
        """Return metadata for ``char_id``, or ``None`` if no source knows it yet."""
        if not char_id:
            return None

        # 1. enka.py's own in-process metadata (no I/O).
        meta = self._from_library(char_id, language)
        if meta is not None and meta.name:
            return meta

        # 2. Upstream metadata (short-lived cache; refreshed when it expires).
        await self._ensure_upstream()
        meta = self._from_upstream(char_id, language)
        if meta is not None and meta.name:
            return meta

        # 3. Local snapshot of the last known-good upstream data.
        meta = self._from_snapshot(char_id, language)
        if meta is not None and meta.name:
            return meta

        return None

    async def resolve_text(self, text_hash: Any, language: str = "en") -> str | None:
        """Resolve a raw text-map hash (weapon / artifact-set names) to display text.

        enka.py leaves these as bare hash strings whenever it skipped post-processing for a
        character it couldn't find, so resolving them keeps the weapon and artifact panels
        readable for a brand-new character.
        """
        key = str(text_hash or "").strip()
        if not key or not key.isdigit():
            return None
        text = self._text_from_library(key, language)
        if text:
            return text
        await self._ensure_upstream()
        return self._lookup_text(self._text, key, language)

    # -- source 1: enka.py in-process assets --------------------------------
    @staticmethod
    def _library_assets() -> Any | None:
        try:
            from enka.assets.gi.manager import GI_ASSETS  # type: ignore

            return GI_ASSETS
        except Exception:  # noqa: BLE001 - library absent or restructured
            return None

    def _from_library(self, char_id: str, language: str) -> CharacterMeta | None:
        assets = self._library_assets()
        if assets is None:
            return None
        try:
            data = assets.character_data.get(str(char_id))
        except Exception:  # noqa: BLE001 - assets not loaded yet
            return None
        if not isinstance(data, dict):
            return None
        name = self._text_from_library(str(data.get("NameTextMapHash", "")), language)
        return _meta_from_entry(char_id, data, name, source="enka.py assets")

    def _text_from_library(self, text_hash: str, language: str) -> str | None:
        assets = self._library_assets()
        if assets is None or not text_hash:
            return None
        try:
            text_map = assets.text_map.data
        except Exception:  # noqa: BLE001 - not loaded
            return None
        return self._lookup_text(text_map, text_hash, language)

    # -- source 2: upstream metadata ---------------------------------------
    async def _ensure_upstream(self) -> None:
        """Fetch upstream metadata when the cache is empty or expired. Never raises."""
        if self._characters and (time.monotonic() - self._fetched_at) < self._ttl:
            return
        async with self._lock:
            if self._characters and (time.monotonic() - self._fetched_at) < self._ttl:
                return
            for source in _SOURCES:
                characters = await self._get_json(source["characters"])
                if not isinstance(characters, dict) or not characters:
                    continue
                text = await self._get_json(source["text"])
                self._characters = characters
                self._text = text if isinstance(text, dict) else {}
                self._source_name = source["name"]
                self._fetched_at = time.monotonic()
                logger.info(
                    "[ENKA] Loaded upstream character metadata from %s (%d characters)",
                    source["name"], len(characters),
                )
                self._write_snapshot()
                return
            logger.warning("[ENKA] No upstream character metadata source was reachable")

    async def _get_json(self, url: str) -> Any:
        try:
            session = await self._get_session()
            async with session.get(url) as resp:
                if resp.status != 200:
                    logger.info("[ENKA] Metadata source HTTP %s: %s", resp.status, url)
                    return None
                return await resp.json(content_type=None)
        except Exception as exc:  # noqa: BLE001 - best effort
            logger.info("[ENKA] Metadata source unreachable (%s): %s", url, exc)
            return None

    def _from_upstream(self, char_id: str, language: str) -> CharacterMeta | None:
        entry = self._characters.get(str(char_id))
        if not isinstance(entry, dict):
            return None
        name = self._lookup_text(self._text, str(entry.get("NameTextMapHash", "")), language)
        return _meta_from_entry(char_id, entry, name, source=self._source_name)

    # -- source 3: local snapshot ------------------------------------------
    def _write_snapshot(self) -> None:
        """Persist a *minimal* projection of the upstream data (id -> display fields).

        Only what the card needs is stored, so the file stays small and readable; it is
        rewritten on every successful upstream fetch and therefore never goes permanently
        stale the way the library's own cache did.
        """
        if self._snapshot_path is None:
            return
        try:
            entries: dict[str, Any] = {}
            for char_id, entry in self._characters.items():
                if not isinstance(entry, dict):
                    continue
                names = {
                    lang: text
                    for lang in _LANG_CANDIDATES
                    if (text := self._lookup_text(self._text, str(entry.get("NameTextMapHash", "")), lang))
                }
                entries[str(char_id)] = {
                    "names": names,
                    "Element": entry.get("Element"),
                    "QualityType": entry.get("QualityType"),
                    "SideIconName": entry.get("SideIconName"),
                    "WeaponType": entry.get("WeaponType"),
                }
            self._snapshot_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._snapshot_path.with_suffix(".tmp")
            tmp.write_text(json.dumps(entries), encoding="utf-8")
            tmp.replace(self._snapshot_path)
        except Exception as exc:  # noqa: BLE001 - the snapshot is a nicety, not a requirement
            logger.debug("Could not write character metadata snapshot: %s", exc)

    def _from_snapshot(self, char_id: str, language: str) -> CharacterMeta | None:
        if self._snapshot_path is None or not self._snapshot_path.exists():
            return None
        try:
            data = json.loads(self._snapshot_path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001 - corrupt snapshot is not fatal
            logger.debug("Unreadable character metadata snapshot: %s", exc)
            return None
        entry = data.get(str(char_id)) if isinstance(data, dict) else None
        if not isinstance(entry, dict):
            return None
        names = entry.get("names") or {}
        name = next(
            (names[lang] for lang in _LANG_CANDIDATES.get(language, ("en",)) if names.get(lang)),
            names.get("en"),
        )
        return _meta_from_entry(char_id, entry, name, source="local snapshot")

    # -- helpers -----------------------------------------------------------
    @staticmethod
    def _lookup_text(text_map: Any, text_hash: str, language: str) -> str | None:
        """Look a hash up in a ``{lang: {hash: text}}`` map, trying language fallbacks."""
        if not text_hash or not isinstance(text_map, dict):
            return None
        for lang in _LANG_CANDIDATES.get(language, (language, "en")):
            table = text_map.get(lang)
            if isinstance(table, dict):
                value = table.get(text_hash)
                if isinstance(value, str) and value:
                    return value
        return None


def _meta_from_entry(
    char_id: str, entry: dict[str, Any], name: str | None, *, source: str
) -> CharacterMeta:
    quality = entry.get("QualityType")
    return CharacterMeta(
        id=str(char_id),
        name=name or None,
        element=entry.get("Element") or None,
        rarity=_QUALITY_RARITY.get(str(quality)) if quality else None,
        side_icon=_normalize_icon_path(entry.get("SideIconName")),
        weapon_type=entry.get("WeaponType") or None,
        source=source,
    )


_RESOLVER: CharacterMetadataResolver | None = None


def get_metadata_resolver() -> CharacterMetadataResolver:
    """Return the shared resolver, configured from settings on first use."""
    global _RESOLVER
    if _RESOLVER is None:
        try:
            from bot.config import get_settings

            settings = get_settings()
            _RESOLVER = CharacterMetadataResolver(
                ttl=float(settings.enka_metadata_ttl),
                snapshot_path=settings.character_meta_file,
            )
        except Exception:  # noqa: BLE001 - never block the data path on config
            _RESOLVER = CharacterMetadataResolver()
    return _RESOLVER
