"""Tests for callback_data encoding/decoding."""

from __future__ import annotations

import pytest

from bot.utils import callbacks
from bot.utils.callbacks import MAX_CALLBACK_BYTES


def test_encode_decode_roundtrip():
    data = callbacks.encode(callbacks.ACTION_CHAR, uid="901211014", char_id="10000046", page=3)
    cb = callbacks.decode(data)
    assert cb.action == callbacks.ACTION_CHAR
    assert cb.uid == "901211014"
    assert cb.char_id == "10000046"
    assert cb.page == 3


def test_encode_decode_owner_roundtrip():
    data = callbacks.encode(callbacks.ACTION_CHAR, uid="901211014", char_id="10000046", page=3, owner=123456789)
    cb = callbacks.decode(data)
    assert cb.owner == 123456789


def test_legacy_payload_has_zero_owner():
    # 4-field (pre-fix) data decodes with owner 0 -> treated as unrestricted.
    cb = callbacks.decode("char|901211014|10000046|0")
    assert cb.owner == 0


def test_extract_owner_character_format():
    data = callbacks.encode(callbacks.ACTION_PAGE, uid="901211014", page=2, owner=42)
    assert callbacks.extract_owner(data) == 42


def test_extract_owner_language_format():
    assert callbacks.extract_owner("lang:es:987654321") == 987654321
    assert callbacks.extract_owner("lang:__menu__:987654321") == 987654321


def test_extract_owner_unrestricted_or_legacy():
    assert callbacks.extract_owner("char|901211014|10000046|0") == 0  # legacy 4-field
    assert callbacks.extract_owner("lang:es:0") == 0
    assert callbacks.extract_owner("") == 0
    assert callbacks.extract_owner("noop") == 0


def test_encode_within_telegram_limit():
    data = callbacks.encode(
        callbacks.ACTION_CHAR, uid="1901234567", char_id="10000046", page=99, owner=9999999999
    )
    assert len(data.encode("utf-8")) <= MAX_CALLBACK_BYTES


def test_encode_rejects_oversized_payload():
    with pytest.raises(ValueError):
        callbacks.encode(callbacks.ACTION_CHAR, uid="9" * 40, char_id="1" * 40, page=1)


def test_decode_malformed_is_noop():
    cb = callbacks.decode("garbage-without-separators")
    assert cb.action == "garbage-without-separators" or cb.action == callbacks.ACTION_NOOP
    # Non-integer page degrades to 0.
    assert callbacks.decode("page|uid|char|notanint").page == 0


def test_decode_empty_is_noop():
    cb = callbacks.decode("")
    assert cb.action == callbacks.ACTION_NOOP
