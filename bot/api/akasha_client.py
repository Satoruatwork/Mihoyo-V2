"""Async client for the Akasha System API (akasha.cv).

Akasha provides per-character damage leaderboard rankings. We call the public endpoint
directly with a browser User-Agent — akasha.cv returns **403** to the default
``akasha-py`` UA, which is why rankings previously never resolved. Parsing is **label-based**
(fields are selected by key name, not positional index) so it tolerates layout changes, and
parse failures are logged (raw payload + field + error) instead of being silently swallowed.

Returns a mapping of character id (str) -> :class:`bot.models.ranking.Ranking`.
"""

from __future__ import annotations

import asyncio
from typing import Any

import aiohttp

from bot.models.ranking import Ranking
from bot.utils.logging import get_logger

logger = get_logger(__name__)

_API = "https://akasha.cv/api/getCalculationsForUser/{uid}"
_LEADERBOARD_URL = "https://akasha.cv/leaderboards/{calc_id}"
# akasha.cv rejects the default akasha-py UA (403); a browser UA is required.
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
    ),
    "Accept": "application/json",
    "Referer": "https://akasha.cv/",
}


class AkashaClient:
    """Best-effort Akasha ranking client. Never raises to callers."""

    def __init__(self) -> None:
        # One pooled session reused across ranking requests (avoids a new TCP+TLS
        # handshake per call). Created lazily inside the loop, closed on shutdown.
        self._session: aiohttp.ClientSession | None = None
        self._session_lock = asyncio.Lock()

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            async with self._session_lock:
                if self._session is None or self._session.closed:
                    connector = aiohttp.TCPConnector(limit=16, ttl_dns_cache=300)
                    self._session = aiohttp.ClientSession(
                        headers=_HEADERS,
                        timeout=aiohttp.ClientTimeout(total=20),
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

    async def fetch_rankings(self, uid: str) -> dict[str, Ranking]:
        """Return per-character rankings for a UID, keyed by character id. Empty if unavailable."""
        raw = await self._fetch_raw(uid)
        if raw is None:
            return {}
        return self._parse(raw, uid)

    async def _fetch_raw(self, uid: str) -> list[dict[str, Any]] | None:
        try:
            session = await self._get_session()
            async with session.get(_API.format(uid=uid)) as resp:
                if resp.status != 200:
                    logger.info("Akasha HTTP %s for uid %s", resp.status, uid)
                    return None
                payload = await resp.json(content_type=None)
        except Exception as exc:  # noqa: BLE001 - best effort; degrade silently
            logger.info("Akasha request failed for %s: %s", uid, exc)
            return None

        data = payload.get("data", payload) if isinstance(payload, dict) else payload
        if not isinstance(data, list):
            logger.warning("Akasha payload not a list for %s: %r", uid, str(payload)[:300])
            return None
        return data

    def _parse(self, entries: list[dict[str, Any]], uid: str) -> dict[str, Ranking]:
        """Extract rankings by field label. Logs (raw + field + error) on any failure."""
        out: dict[str, Ranking] = {}
        for entry in entries:
            char_id = _first(entry, "characterId", "character_id")
            if char_id is None:
                logger.debug("Akasha entry missing characterId for %s: %r", uid, str(entry)[:200])
                continue
            char_id = str(char_id)

            best = self._best_calculation(entry, uid)
            if best is None:
                continue

            try:
                rank = _first_int(best, "ranking", "rank")
                total = _first_int(best, "outOf", "out_of", "total")
                category = _first_str(best, "name", "short")
                calc_id = _first_str(best, "calculationId", "calculation_id", "id")
                top_percent = (
                    (rank / total * 100.0)
                    if (rank is not None and total is not None and total != 0)
                    else None
                )
                # Debug aid: if the calc exists but core fields didn't parse, say which.
                for label, value in (("ranking", rank), ("outOf", total), ("name", category)):
                    if value is None:
                        logger.warning(
                            "Akasha parse: '%s' missing for char %s uid %s; calc keys=%s",
                            label, char_id, uid, list(best.keys()),
                        )
                out[char_id] = Ranking(
                    calculation_id=calc_id,
                    calculation_name=category,
                    rank=rank,
                    total_players=total,
                    top_percent=top_percent,
                    leaderboard_url=_LEADERBOARD_URL.format(calc_id=calc_id) if calc_id else None,
                    damage=_first_float(best, "result", "damage"),
                )
            except Exception as exc:  # noqa: BLE001 - never break the flow; log for debugging
                logger.warning(
                    "Akasha parse error for char %s uid %s: %s; raw=%r",
                    char_id, uid, exc, str(best)[:300],
                )
        return out

    @staticmethod
    def _best_calculation(entry: dict[str, Any], uid: str) -> dict[str, Any] | None:
        """Pick the character's best-ranked calculation from the ``calculations`` map/list."""
        calcs = entry.get("calculations")
        items: list[dict[str, Any]] = []
        if isinstance(calcs, dict):
            items = [c for c in calcs.values() if isinstance(c, dict)]
        elif isinstance(calcs, list):
            items = [c for c in calcs if isinstance(c, dict)]
        if not items:
            logger.debug("Akasha: no calculations for entry uid %s: %r", uid, str(entry)[:200])
            return None
        ranked = [c for c in items if _first_int(c, "ranking", "rank") is not None]
        if not ranked:
            return items[0]
        return min(ranked, key=lambda c: _first_int(c, "ranking", "rank"))


def _first(obj: dict[str, Any], *names: str) -> Any:
    for n in names:
        if n in obj and obj[n] is not None:
            return obj[n]
    return None


def _first_str(obj: dict[str, Any], *names: str) -> str | None:
    v = _first(obj, *names)
    return str(v) if v is not None else None


def _first_int(obj: dict[str, Any], *names: str) -> int | None:
    v = _first(obj, *names)
    try:
        return int(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def _first_float(obj: dict[str, Any], *names: str) -> float | None:
    v = _first(obj, *names)
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None
