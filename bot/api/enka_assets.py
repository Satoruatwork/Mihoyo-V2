"""Freshness management for enka.py's on-disk game-metadata assets.

``enka.py`` ships no metadata: on first use it downloads a set of JSON files into
``.enka_py/assets/`` (``characters.json``, ``text_map.json``, ``consts.json``, …) and from
then on :meth:`enka.assets.data.AssetData.load` short-circuits — *if the file exists it is
never re-downloaded*. The parsed data is additionally held on the module-level ``GI_ASSETS``
singleton for the lifetime of the process. Only an explicit ``client.update_assets()`` call
refreshes either copy.

The consequence is the bug this module exists to fix: once a deployment has fetched the
metadata, a **newly released character is invisible forever**. Enka.Network happily returns
the new avatar id, but ``GenshinClient._post_process_character`` cannot find it in the stale
``characters.json``, logs to a logger the library disables by default, and returns early —
leaving the character with an empty name, ``Element.NONE``, rarity ``0`` and a blank icon.

:class:`EnkaAssetRefresher` closes that gap:

* **TTL refresh** — assets older than ``ttl`` are updated before a showcase is parsed.
* **Forced refresh** — when a character actually fails to resolve, the caller asks for an
  immediate update (rate-limited by ``force_cooldown`` so a permanently unknown id can't
  turn into a download loop) and re-parses the *already fetched* payload, costing no extra
  Enka.Network request.

Everything here is best-effort: a failed refresh is logged and the run continues with
whatever metadata is already present.
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any

from bot.utils.logging import get_logger

logger = get_logger(__name__)

# The library's own cache location (enka.assets.gi.file_paths.CHARACTER_DATA_PATH). Read via
# the library when importable; this literal is only the fallback for the mtime probe.
_DEFAULT_MARKER = Path(".enka_py/assets/characters.json")


class EnkaAssetRefresher:
    """Keeps enka.py's game metadata fresh so new characters resolve without a redeploy.

    Args:
        ttl: Maximum age, in seconds, of the on-disk metadata before a refresh is issued.
        force_cooldown: Minimum gap between two *forced* refreshes, so an id that upstream
            genuinely doesn't know yet cannot trigger a download on every command.
    """

    def __init__(self, ttl: float = 21_600.0, force_cooldown: float = 900.0) -> None:
        self._ttl = ttl
        self._force_cooldown = force_cooldown
        self._lock = asyncio.Lock()
        self._last_refresh: float = 0.0       # time.monotonic() of the last successful update
        self._last_force: float = 0.0
        self._loaded_at: float = 0.0          # when this process first saw the assets

    # -- introspection -----------------------------------------------------
    @staticmethod
    def _marker_path() -> Path:
        """Path of the character metadata file used as the freshness marker."""
        try:
            from enka.assets.gi.file_paths import CHARACTER_DATA_PATH  # type: ignore

            return Path(CHARACTER_DATA_PATH)
        except Exception:  # noqa: BLE001 - library layout changed / not installed
            return _DEFAULT_MARKER

    def _age_seconds(self) -> float | None:
        """Age of the on-disk metadata, or ``None`` when it hasn't been downloaded yet."""
        try:
            marker = self._marker_path()
            if not marker.exists():
                return None
            return max(0.0, time.time() - marker.stat().st_mtime)
        except OSError:
            return None

    def _is_stale(self) -> bool:
        age = self._age_seconds()
        if age is None:
            # Not downloaded yet: the library's own load() will fetch it. Not "stale".
            return False
        if age > self._ttl:
            return True
        # The file may be young on disk yet already refreshed by us this process; the
        # monotonic guard stops a short TTL from refreshing on every single call.
        return False

    def _refreshed_recently(self) -> bool:
        return self._last_refresh > 0.0 and (time.monotonic() - self._last_refresh) < self._ttl

    # -- refresh -----------------------------------------------------------
    async def ensure_fresh(self, client: Any) -> bool:
        """Refresh the metadata if it is older than the TTL. Returns whether it updated.

        Called before parsing a showcase. Cheap in the common case: a filesystem ``stat``.
        """
        if self._refreshed_recently() or not self._is_stale():
            return False
        age = self._age_seconds()
        logger.info(
            "[ENKA] Game metadata is %.1f h old (ttl %.1f h) — refreshing",
            (age or 0) / 3600.0, self._ttl / 3600.0,
        )
        return await self._update(client, reason="ttl")

    async def force_refresh(self, client: Any, *, reason: str) -> bool:
        """Refresh immediately, unless a forced refresh happened within the cooldown.

        Used when a character id could not be resolved: the most likely explanation is that
        a new character shipped and our metadata predates it.
        """
        now = time.monotonic()
        if self._last_force and (now - self._last_force) < self._force_cooldown:
            logger.info(
                "[ENKA] Metadata refresh suppressed (last forced refresh %.0f s ago, "
                "cooldown %.0f s): %s",
                now - self._last_force, self._force_cooldown, reason,
            )
            return False
        self._last_force = now
        logger.info("[ENKA] Forcing game metadata refresh: %s", reason)
        return await self._update(client, reason=reason)

    async def _update(self, client: Any, *, reason: str) -> bool:
        """Run ``client.update_assets()`` under the lock. Never raises."""
        async with self._lock:
            # Another coroutine may have refreshed while we waited for the lock.
            if reason == "ttl" and self._refreshed_recently():
                return False
            update = getattr(client, "update_assets", None)
            if update is None:
                logger.warning("[ENKA] Client exposes no update_assets(); metadata not refreshed")
                return False
            started = time.perf_counter()
            try:
                await update()
            except Exception as exc:  # noqa: BLE001 - degraded, not fatal
                logger.warning(
                    "[ENKA] Metadata refresh failed (%s: %s) — continuing with existing data",
                    type(exc).__name__, exc,
                )
                return False
            self._last_refresh = time.monotonic()
            logger.info(
                "[ENKA] Game metadata refreshed in %.0f ms (%s)",
                (time.perf_counter() - started) * 1000, reason,
            )
            return True


# Process-wide singleton: enka.py's assets are themselves a module-level singleton, so
# tracking their freshness in one place matches reality and avoids duplicate downloads.
_REFRESHER: EnkaAssetRefresher | None = None


def get_asset_refresher() -> EnkaAssetRefresher:
    """Return the shared :class:`EnkaAssetRefresher`, built from settings on first use."""
    global _REFRESHER
    if _REFRESHER is None:
        try:
            from bot.config import get_settings

            settings = get_settings()
            _REFRESHER = EnkaAssetRefresher(
                ttl=float(settings.enka_assets_ttl),
                force_cooldown=float(settings.enka_assets_force_cooldown),
            )
        except Exception:  # noqa: BLE001 - settings must never block the data path
            _REFRESHER = EnkaAssetRefresher()
    return _REFRESHER
