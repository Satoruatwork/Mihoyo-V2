"""Tests for the cookie encryption helper."""

from __future__ import annotations

from bot.utils.crypto import CookieCipher


def test_roundtrip():
    c = CookieCipher("a-long-random-secret")
    token = c.encrypt("cookie_token_v2=abc; account_id_v2=1")
    assert token != "cookie_token_v2=abc; account_id_v2=1"  # actually encrypted
    assert c.decrypt(token) == "cookie_token_v2=abc; account_id_v2=1"


def test_disabled_without_secret():
    c = CookieCipher("")
    assert c.available is False
    assert c.decrypt("anything") is None


def test_decrypt_garbage_returns_none():
    c = CookieCipher("secret")
    assert c.decrypt("not-a-valid-token") is None
    assert c.decrypt(None) is None


def test_wrong_secret_cannot_decrypt():
    token = CookieCipher("secret-one").encrypt("data")
    # A different secret derives a different key -> decrypt fails softly.
    assert CookieCipher("secret-two").decrypt(token) is None


def test_session_secret_falls_back_to_bot_token():
    from bot.config import Settings

    # No dedicated secret -> derive the key from BOT_TOKEN so login works out of the box.
    s = Settings(bot_token="123456:ABCDEF", hoyolab_secret="")
    assert s.session_secret == "123456:ABCDEF"
    assert CookieCipher(s.session_secret).available is True

    # An explicit HOYOLAB_SECRET takes precedence.
    s2 = Settings(bot_token="123456:ABCDEF", hoyolab_secret="dedicated-key")
    assert s2.session_secret == "dedicated-key"
