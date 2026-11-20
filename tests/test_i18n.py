"""Tests for the localization system."""

from __future__ import annotations

from bot.translations import i18n
from bot.translations.i18n import t


def test_english_lookup():
    assert "UID" in t("account.myuid_none", "en")


def test_all_locales_load_and_are_supported():
    for code, _label in i18n.available_languages():
        assert i18n.is_supported(code)
        # Every registered locale must resolve a known key.
        assert t("start.welcome", code)


def test_missing_key_falls_back_to_key_name():
    assert t("this.key.does.not.exist", "en") == "this.key.does.not.exist"


def test_missing_translation_falls_back_to_english(monkeypatch):
    # Force a locale to lack a key and confirm English is used.
    i18n.clear_cache()
    real_load = i18n._load_locale.__wrapped__  # type: ignore[attr-defined]

    def fake_load(code: str):
        data = dict(real_load(code))
        if code == "es":
            data.pop("common.back", None)
        return data

    monkeypatch.setattr(i18n, "_load_locale", fake_load)
    # Spanish is missing the key -> should equal the English value.
    assert i18n.t("common.back", "es") == real_load("en")["common.back"]


def test_unsupported_language_normalizes_to_english():
    assert i18n.normalize("xx") == "en"
    assert i18n.normalize(None) == "en"


def test_format_kwargs():
    out = t("account.myuid", "en", uid="123456789")
    assert "123456789" in out
