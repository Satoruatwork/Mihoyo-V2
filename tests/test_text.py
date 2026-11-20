"""Tests for custom-emoji text helpers and locale integrity."""

from __future__ import annotations

import glob
import json

from bot.utils.text import has_custom_emoji, strip_custom_emoji


def test_strip_single_custom_emoji():
    src = '<tg-emoji emoji-id="123">👋</tg-emoji> Hi'
    assert strip_custom_emoji(src) == "👋 Hi"


def test_strip_multiple_and_preserves_other_html():
    src = 'A <tg-emoji emoji-id="1">✨</tg-emoji> <b>Lauma</b> <tg-emoji emoji-id="2">💫</tg-emoji>'
    assert strip_custom_emoji(src) == "A ✨ <b>Lauma</b> 💫"


def test_strip_noop_when_absent():
    src = "plain <b>text</b> only"
    assert strip_custom_emoji(src) == src


def test_has_custom_emoji():
    assert has_custom_emoji('<tg-emoji emoji-id="9">🌟</tg-emoji>')
    assert not has_custom_emoji("no emoji here")


def test_welcome_message_uses_custom_emoji_in_all_locales():
    # The Lauma welcome should carry custom emoji, and stripping must leave clean text.
    for f in glob.glob("bot/translations/locales/*.json"):
        data = json.load(open(f, encoding="utf-8"))
        welcome = data["start.welcome"]
        assert has_custom_emoji(welcome), f"{f} welcome missing custom emoji"
        # Fallback must not leave any dangling tg-emoji fragments.
        assert "tg-emoji" not in strip_custom_emoji(welcome)
