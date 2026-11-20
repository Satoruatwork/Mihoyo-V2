"""Tests for enka.py game-metadata freshness.

The original defect was a cache that could never expire: enka.py writes its metadata once
and ``AssetData.load()`` then short-circuits forever, so a long-lived deployment kept serving
a character list frozen at first boot. These tests pin the properties that prevent that.
"""

from __future__ import annotations

import os
import time

import pytest

from bot.api.enka_assets import EnkaAssetRefresher


class _Client:
    def __init__(self, fail: bool = False) -> None:
        self.calls = 0
        self._fail = fail

    async def update_assets(self) -> None:
        self.calls += 1
        if self._fail:
            raise RuntimeError("github unreachable")


@pytest.fixture
def marker(tmp_path, monkeypatch):
    """Point the freshness probe at a temp file standing in for characters.json."""
    path = tmp_path / "characters.json"
    path.write_text("{}")
    monkeypatch.setattr(EnkaAssetRefresher, "_marker_path", staticmethod(lambda: path))
    return path


async def test_fresh_metadata_is_not_refetched(marker):
    refresher = EnkaAssetRefresher(ttl=3600)
    client = _Client()

    assert await refresher.ensure_fresh(client) is False
    assert client.calls == 0


async def test_metadata_older_than_the_ttl_is_refreshed(marker):
    """The core fix: age alone triggers an update, with no code change or redeploy."""
    old = time.time() - 10_000
    os.utime(marker, (old, old))
    refresher = EnkaAssetRefresher(ttl=3600)
    client = _Client()

    assert await refresher.ensure_fresh(client) is True
    assert client.calls == 1


async def test_ttl_refresh_happens_once_per_period(marker):
    old = time.time() - 10_000
    os.utime(marker, (old, old))
    refresher = EnkaAssetRefresher(ttl=3600)
    client = _Client()

    await refresher.ensure_fresh(client)
    await refresher.ensure_fresh(client)

    assert client.calls == 1, "the monotonic guard must prevent a refresh storm"


async def test_absent_metadata_is_left_to_the_library(marker):
    """First boot: the library's own load() downloads it; forcing an update would be wasteful."""
    marker.unlink()
    client = _Client()

    assert await EnkaAssetRefresher(ttl=1).ensure_fresh(client) is False
    assert client.calls == 0


async def test_force_refresh_bypasses_the_ttl(marker):
    """An unresolved character id must refresh immediately, however young the file is."""
    refresher = EnkaAssetRefresher(ttl=86_400, force_cooldown=0)
    client = _Client()

    assert await refresher.force_refresh(client, reason="unknown id 10000150") is True
    assert client.calls == 1


async def test_force_refresh_is_rate_limited(marker):
    """An id upstream genuinely doesn't know must not download metadata every command."""
    refresher = EnkaAssetRefresher(ttl=86_400, force_cooldown=900)
    client = _Client()

    assert await refresher.force_refresh(client, reason="first") is True
    assert await refresher.force_refresh(client, reason="second") is False
    assert client.calls == 1


async def test_a_failing_refresh_is_survivable(marker):
    """A metadata download failure degrades to stale data; it never breaks the command."""
    refresher = EnkaAssetRefresher(ttl=86_400, force_cooldown=0)
    client = _Client(fail=True)

    assert await refresher.force_refresh(client, reason="unknown id") is False
    assert client.calls == 1


async def test_client_without_update_support_is_handled(marker):
    refresher = EnkaAssetRefresher(ttl=86_400, force_cooldown=0)

    assert await refresher.force_refresh(object(), reason="unknown id") is False
