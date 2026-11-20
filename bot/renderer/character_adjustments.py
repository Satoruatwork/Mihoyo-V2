"""Optional per-character portrait corrections.

The automatic fitter in :mod:`bot.renderer.image_fitter` is the default and handles every
character on its own — this file exists only for the rare case where a specific piece of
splash art still sits wrong after trimming and cover-fitting.

It is deliberately a *data* file, loaded from JSON, and empty by default. A character absent
from it (which includes every future release) renders through the automatic path, so a new
character never requires a code change.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from bot.renderer.image_fitter import DEFAULT_ADJUSTMENT, Adjustment
from bot.utils.logging import get_logger

logger = get_logger(__name__)

ADJUSTMENTS_FILE = Path(__file__).resolve().parent / "character_adjustments.json"


@lru_cache(maxsize=1)
def _adjustments() -> dict[str, Adjustment]:
    if not ADJUSTMENTS_FILE.exists():
        return {}
    try:
        raw = json.loads(ADJUSTMENTS_FILE.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 - a bad override file must not break rendering
        logger.warning("Ignoring unreadable character adjustments: %s", exc)
        return {}
    out: dict[str, Adjustment] = {}
    for char_id, entry in (raw or {}).items():
        if isinstance(entry, dict):
            out[str(char_id)] = Adjustment(
                scale=float(entry.get("scale", 1.0)),
                x_offset=int(entry.get("x_offset", 0)),
                y_offset=int(entry.get("y_offset", 0)),
            )
    if out:
        logger.info("Loaded %d character portrait adjustment(s)", len(out))
    return out


def adjustment_for(character_id: str) -> Adjustment:
    """Correction for a character, or the neutral default (the normal case)."""
    return _adjustments().get(str(character_id), DEFAULT_ADJUSTMENT)
