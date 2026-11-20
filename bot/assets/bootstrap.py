"""One-time asset bootstrap: download the character-card template and fonts.

Run at startup. Anything that fails to download is logged and skipped — the renderer
degrades gracefully (placeholder/ default font) rather than crashing.
"""

from __future__ import annotations

from pathlib import Path

import aiohttp

from bot.config import get_settings
from bot.utils.logging import get_logger

logger = get_logger(__name__)

TEMPLATE_URL = "https://i.ibb.co/nN35Wwm3/001bf376c130.jpg"
# Single universal variable font (Latin + Chinese + Japanese kana), OFL licensed.
FONT_URL = "https://cdn.jsdelivr.net/gh/google/fonts@main/ofl/notosanssc/NotoSansSC%5Bwght%5D.ttf"
# Display serif for names and headings on the character card (variable weight), OFL licensed.
SERIF_FONT_URL = (
    "https://cdn.jsdelivr.net/gh/google/fonts@main/ofl/cormorantgaramond/"
    "CormorantGaramond%5Bwght%5D.ttf"
)

TEMPLATE_REL = ("ui", "character_card_template.jpg")
FONT_REL = ("fonts", "NotoSansSC.ttf")
SERIF_FONT_REL = ("fonts", "CormorantGaramond.ttf")


def _target(assets_root: Path, rel: tuple[str, str]) -> Path:
    return assets_root / rel[0] / rel[1]


async def _download(session: aiohttp.ClientSession, url: str, dest: Path) -> bool:
    if dest.exists() and dest.stat().st_size > 0:
        return True
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=60)) as resp:
            resp.raise_for_status()
            data = await resp.read()
        dest.write_bytes(data)
        logger.info("Downloaded %s (%d KB)", dest.name, len(data) // 1024)
        return True
    except Exception as exc:  # noqa: BLE001 - non-fatal; renderer has fallbacks
        logger.warning("Could not download %s: %s", url, exc)
        return False


async def ensure_card_assets() -> None:
    """Ensure the template and fonts exist locally; download them if missing."""
    root = get_settings().assets_path
    headers = {"User-Agent": "Mozilla/5.0 (MihoyoBot)"}
    async with aiohttp.ClientSession(headers=headers) as session:
        await _download(session, TEMPLATE_URL, _target(root, TEMPLATE_REL))
        await _download(session, FONT_URL, _target(root, FONT_REL))
        await _download(session, SERIF_FONT_URL, _target(root, SERIF_FONT_REL))


def template_path() -> Path:
    return _target(get_settings().assets_path, TEMPLATE_REL)


def font_path() -> Path:
    return _target(get_settings().assets_path, FONT_REL)


def serif_font_path() -> Path:
    return _target(get_settings().assets_path, SERIF_FONT_REL)
