"""Localization loader.

Translations live in ``locales/<code>.json`` as flat key -> string maps. Lookups fall
back **per key** to English, so a partially-translated locale still works. Adding a new
language means dropping a new JSON file and registering it in :data:`LANGUAGES`.

Public API:
    - ``t(key, lang, **kwargs)`` — translate a key, formatting with ``kwargs``.
    - ``available_languages()`` — list of (code, display_name) for menus.
    - ``is_supported(code)`` — whether a language code is known.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from bot.config import get_settings
from bot.utils.logging import get_logger

logger = get_logger(__name__)

DEFAULT_LANG = "en"

# Registered languages: code -> human-readable label (with flag) shown in menus.
# To add a language: create locales/<code>.json and add an entry here.
LANGUAGES: dict[str, str] = {
    "en": "English 🇺🇸",
    "es": "Español 🇪🇸",
    "it": "Italiano 🇮🇹",
    "ja": "日本語 🇯🇵",
    "zh": "简体中文 🇨🇳",
}


@lru_cache(maxsize=None)
def _load_locale(code: str) -> dict[str, str]:
    """Load and cache one locale file. Missing/broken files -> empty dict."""
    path: Path = get_settings().translations_path / f"{code}.json"
    if not path.exists():
        logger.warning("Locale file missing: %s", path)
        return {}
    try:
        with path.open(encoding="utf-8") as fh:
            data = json.load(fh)
        if not isinstance(data, dict):
            logger.error("Locale %s is not a JSON object", code)
            return {}
        return {str(k): str(v) for k, v in data.items()}
    except (OSError, json.JSONDecodeError) as exc:
        logger.error("Failed to load locale %s: %s", code, exc)
        return {}


def is_supported(code: str | None) -> bool:
    return bool(code) and code in LANGUAGES


def available_languages() -> list[tuple[str, str]]:
    """Return [(code, label), ...] for building a language menu."""
    return list(LANGUAGES.items())


def normalize(code: str | None) -> str:
    """Return a supported language code, defaulting to English."""
    return code if is_supported(code) else DEFAULT_LANG


def t(key: str, lang: str | None = None, /, **kwargs: object) -> str:
    """Translate ``key`` into ``lang``.

    Resolution order: requested language -> English -> the key itself (so a missing
    string is visible in logs/UI rather than crashing). ``kwargs`` are used for
    ``str.format`` interpolation; formatting errors degrade to the unformatted string.
    """
    lang = normalize(lang)
    value = _load_locale(lang).get(key)
    if value is None and lang != DEFAULT_LANG:
        value = _load_locale(DEFAULT_LANG).get(key)
    if value is None:
        logger.debug("Missing translation for key %r", key)
        value = key
    if kwargs:
        try:
            return value.format(**kwargs)
        except (KeyError, IndexError, ValueError):
            return value
    return value


def preload_locales() -> None:
    """Load and cache every registered locale once (call at startup).

    Locales are already memoized by :func:`_load_locale`; this just warms the cache so the
    first translation lookup in a command doesn't pay the file-read + JSON-parse cost.
    """
    for code in LANGUAGES:
        _load_locale(code)


def clear_cache() -> None:
    """Clear the locale cache (useful in tests / hot-reload)."""
    _load_locale.cache_clear()
