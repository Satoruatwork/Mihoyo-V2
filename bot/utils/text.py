"""Text helpers for Telegram message formatting."""

from __future__ import annotations

import re

# Matches an HTML custom-emoji tag: <tg-emoji emoji-id="123">😀</tg-emoji>
# (Bot API v9.4, Feb 2026: usable by bots whose owner has Telegram Premium.)
_TG_EMOJI_RE = re.compile(r"<tg-emoji[^>]*>(.*?)</tg-emoji>", re.DOTALL)


def strip_custom_emoji(text: str) -> str:
    """Replace ``<tg-emoji ...>X</tg-emoji>`` with its fallback ``X``.

    Used to gracefully degrade a message when the bot cannot send premium custom
    emoji (e.g. the owner has no Telegram Premium subscription): the standard emoji
    written as the tag's content is kept, and the wrapper is removed.
    """
    return _TG_EMOJI_RE.sub(r"\1", text)


def has_custom_emoji(text: str) -> bool:
    return bool(_TG_EMOJI_RE.search(text))
