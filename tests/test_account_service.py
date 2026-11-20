"""Tests for UID validation and the account service."""

from __future__ import annotations

import pytest

from bot.services.account_service import AccountService, uid_region, validate_uid
from bot.utils.errors import AccountNotLinked, InvalidUID


@pytest.mark.parametrize(
    "uid",
    [
        # 9-digit (single-digit prefix)
        "601234567",  # America
        "712345678",  # Europe
        "812345678",  # Asia
        "901211014",  # TW/HK/MO
        # 10-digit (two-digit prefix)
        "1601234567",  # America
        "1712345678",  # Europe
        "1812345678",  # Asia
        "1901234567",  # TW/HK/MO
    ],
)
def test_validate_uid_accepts_valid(uid):
    assert validate_uid(uid) == uid


@pytest.mark.parametrize(
    "uid",
    [
        "",  # empty
        "123",  # too short
        "12345678",  # 8 digits
        "12345678901",  # 11 digits
        "abcdefghi",  # non-numeric
        "90121101a",  # trailing letter
        "123456789",  # 9-digit but CN prefix 1 (not in supported set)
        "512345678",  # 9-digit prefix 5 (unsupported)
        "1000000000",  # 10-digit prefix 10 (unsupported)
        "1500000000",  # 10-digit prefix 15 (unsupported)
        "2012345678",  # 10-digit prefix 20 (unsupported)
    ],
)
def test_validate_uid_rejects_invalid(uid):
    with pytest.raises(InvalidUID):
        validate_uid(uid)


@pytest.mark.parametrize(
    "uid, region",
    [
        ("601234567", "America"),
        ("1601234567", "America"),
        ("712345678", "Europe"),
        ("1712345678", "Europe"),
        ("812345678", "Asia"),
        ("1812345678", "Asia"),
        ("901211014", "TW/HK/MO"),
        ("1901234567", "TW/HK/MO"),
    ],
)
def test_uid_region(uid, region):
    assert uid_region(uid) == region


def test_uid_whitespace_is_stripped():
    assert validate_uid("  901211014  ") == "901211014"


async def test_link_and_relink(store):
    service = AccountService(store)

    uid, relink = await service.link(111, "901211014")
    assert uid == "901211014"
    assert relink is False

    # Relinking to a different UID reports was_relink=True.
    uid2, relink2 = await service.link(111, "600000000")
    assert uid2 == "600000000"
    assert relink2 is True


async def test_require_uid_raises_when_not_linked(store):
    service = AccountService(store)
    with pytest.raises(AccountNotLinked):
        await service.require_uid(999)


async def test_unlink(store):
    service = AccountService(store)
    await service.link(222, "901211014")
    assert await service.unlink(222) is True
    # Second unlink returns False (nothing to remove).
    assert await service.unlink(222) is False
