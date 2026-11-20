"""Tests for the dynamic character metadata resolver.

The resolver is the fallback that lets a character be named even when enka.py's own metadata
doesn't cover it. What matters here is that it is genuinely *dynamic*: it reads upstream
files, prefers the freshest source, and degrades through a documented chain rather than
consulting any built-in list of characters.
"""

from __future__ import annotations

import json

from bot.api.character_metadata import (
    CharacterMetadataResolver,
    _icon_url,
    _normalize_icon_path,
)

# Shaped exactly like the upstream files (enka-py-assets / Enka.Network API-docs store).
UPSTREAM_CHARACTERS = {
    "10000150": {
        "Element": "Ice",
        "NameTextMapHash": 2417850,
        "QualityType": "QUALITY_ORANGE",
        "SideIconName": "/ui/UI_AvatarIcon_Side_Odette.png",
        "WeaponType": "WEAPON_SWORD_ONE_HAND",
    }
}
UPSTREAM_TEXT = {
    "en": {"2417850": "Odette", "900": "Sword of Test"},
    "ja": {"2417850": "オデット"},
}


def _resolver(tmp_path, *, characters=UPSTREAM_CHARACTERS, text=UPSTREAM_TEXT):
    """A resolver whose 'upstream fetch' is pre-populated (no network in tests)."""
    resolver = CharacterMetadataResolver(ttl=10_000, snapshot_path=tmp_path / "meta.json")
    resolver._characters = dict(characters)
    resolver._text = dict(text)
    resolver._source_name = "test-upstream"
    resolver._fetched_at = float("inf")  # never expires during the test
    return resolver


async def test_resolves_a_character_absent_from_the_library(tmp_path):
    meta = await _resolver(tmp_path).resolve("10000150")

    assert meta is not None
    assert meta.name == "Odette"
    assert meta.element == "Ice"
    assert meta.rarity == 5
    assert meta.side_icon == "UI_AvatarIcon_Side_Odette"


async def test_localizes_the_name_when_the_language_exists(tmp_path):
    assert (await _resolver(tmp_path).resolve("10000150", "ja")).name == "オデット"


async def test_falls_back_to_english_for_a_language_upstream_lacks(tmp_path):
    """Chinese is absent from the upstream text map; a name in English beats no name."""
    assert (await _resolver(tmp_path).resolve("10000150", "zh")).name == "Odette"


async def test_unknown_id_returns_none_rather_than_raising(tmp_path):
    assert await _resolver(tmp_path).resolve("99999999") is None


async def test_unknown_quality_type_does_not_raise(tmp_path):
    """enka.py raises KeyError on an unrecognised QualityType; we degrade to no rarity."""
    characters = {"10000151": {**UPSTREAM_CHARACTERS["10000150"], "QualityType": "QUALITY_NEW"}}
    text = {"en": {"2417850": "Future"}}

    meta = await _resolver(tmp_path, characters=characters, text=text).resolve("10000151")

    assert meta is not None and meta.rarity is None


async def test_resolves_text_map_hashes_for_gear_names(tmp_path):
    """Weapon/artifact names are left as bare hashes when post-processing was skipped."""
    resolver = _resolver(tmp_path)

    assert await resolver.resolve_text("900") == "Sword of Test"
    assert await resolver.resolve_text("not-a-hash") is None
    assert await resolver.resolve_text("") is None


async def test_snapshot_is_written_and_then_serves_as_a_fallback(tmp_path):
    """The local snapshot is a cache of upstream, not an authored character list."""
    snapshot = tmp_path / "meta.json"
    resolver = _resolver(tmp_path)
    resolver._write_snapshot()

    assert json.loads(snapshot.read_text())["10000150"]["names"]["en"] == "Odette"

    # A fresh resolver whose upstream sources are all unreachable still names the character.
    offline = CharacterMetadataResolver(ttl=10_000, snapshot_path=snapshot)

    async def dead(url):
        return None

    offline._get_json = dead
    meta = await offline.resolve("10000150")

    assert meta is not None and meta.name == "Odette"
    assert meta.source == "local snapshot"


async def test_cache_expires_so_new_characters_are_picked_up(tmp_path):
    """A permanently cached character list is exactly what caused the original bug."""
    resolver = CharacterMetadataResolver(ttl=0.0, snapshot_path=tmp_path / "meta.json")
    fetches = []

    async def fake_get_json(url):
        fetches.append(url)
        return UPSTREAM_CHARACTERS if "characters" in url else UPSTREAM_TEXT

    resolver._get_json = fake_get_json

    await resolver._ensure_upstream()
    await resolver._ensure_upstream()

    assert len(fetches) == 4, "a zero TTL must re-fetch, never serve a frozen list"


async def test_invalidate_forces_a_refetch(tmp_path):
    resolver = _resolver(tmp_path)
    calls = []

    async def fake_get_json(url):
        calls.append(url)
        return UPSTREAM_CHARACTERS if "characters" in url else UPSTREAM_TEXT

    resolver._get_json = fake_get_json

    await resolver._ensure_upstream()          # cached; no fetch
    assert calls == []
    resolver.invalidate()
    await resolver._ensure_upstream()
    assert calls, "invalidate() must drop the cached payload"


async def test_unreachable_upstream_is_survivable(tmp_path):
    """Every source down -> None, never an exception into the command path."""
    resolver = CharacterMetadataResolver(ttl=10_000, snapshot_path=tmp_path / "meta.json")

    async def dead(url):
        return None

    resolver._get_json = dead

    assert await resolver.resolve("10000150") is None


# --------------------------------------------------------------------------- URL derivation
def test_icon_paths_are_normalized_across_sources():
    """The two upstream sources spell the same field differently."""
    assert _normalize_icon_path("/ui/UI_AvatarIcon_Side_Odette.png") == "UI_AvatarIcon_Side_Odette"
    assert _normalize_icon_path("UI_AvatarIcon_Side_Ayaka") == "UI_AvatarIcon_Side_Ayaka"
    assert _normalize_icon_path("") is None
    assert _normalize_icon_path(None) is None


def test_art_urls_are_derived_not_stored():
    """Artwork URLs are computed from the icon path, so new characters need no asset entry."""
    side = "UI_AvatarIcon_Side_Odette"

    assert _icon_url(side, "gacha") == "https://enka.network/ui/UI_Gacha_AvatarImg_Odette.png"
    assert _icon_url(side, "front") == "https://enka.network/ui/UI_AvatarIcon_Odette.png"
    assert _icon_url(None, "gacha") is None
