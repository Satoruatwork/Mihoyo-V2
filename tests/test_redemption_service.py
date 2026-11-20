"""Tests for redemption: code validation, service delegation, HoYoLAB error mapping, and the
premium (link-free, button-free) response layouts."""

from __future__ import annotations

import genshin.errors as ge
import pytest

from bot.api.hoyolab_client import HoyolabRedeemer
from bot.commands.redeem import _IN_FLIGHT, _acquire, _panel, _release, _render
from bot.services.redemption_service import (
    RedeemResult,
    RedeemStatus,
    RedemptionService,
    normalize_code,
)

# --- code normalization ------------------------------------------------------


@pytest.mark.parametrize(
    "raw, expected",
    [("genshingift", "GENSHINGIFT"), ("  GA6PH4NPZ8V9  ", "GA6PH4NPZ8V9"), ("AB12", "AB12")],
)
def test_normalize_code_accepts_valid(raw, expected):
    assert normalize_code(raw) == expected


@pytest.mark.parametrize("raw", ["", "  ", "ab", "has space", "sym!bol", "toolongcodevalue12345x"])
def test_normalize_code_rejects_invalid(raw):
    assert normalize_code(raw) is None


# --- service delegation ------------------------------------------------------


async def test_service_rejects_bad_format_without_calling_backend():
    class _Boom:
        async def redeem(self, code):
            raise AssertionError("backend must not be called for a malformed code")

    result = await RedemptionService(_Boom()).redeem("!!bad!!")
    assert result.status is RedeemStatus.INVALID


async def test_service_delegates_and_passes_result_through():
    class _Fake:
        async def redeem(self, code):
            return RedeemResult(RedeemStatus.SUCCESS, code=code, uid="1813698313", nickname="Chronoa")

    result = await RedemptionService(_Fake()).redeem("genshingift")
    assert result.status is RedeemStatus.SUCCESS
    assert result.code == "GENSHINGIFT" and result.nickname == "Chronoa"


async def test_service_contains_backend_exceptions():
    class _Boom:
        async def redeem(self, code):
            raise RuntimeError("network down")

    result = await RedemptionService(_Boom()).redeem("GENSHINGIFT")
    assert result.status is RedeemStatus.SERVER_ERROR


async def test_default_service_reports_auth_failed():
    # No backend wired -> the session is treated as unconfigured.
    result = await RedemptionService().redeem("GENSHINGIFT")
    assert result.status is RedeemStatus.AUTH_FAILED


async def test_service_uses_per_call_redeemer():
    class _Default:
        async def redeem(self, code):
            raise AssertionError("per-call redeemer should take precedence")

    class _PerUser:
        async def redeem(self, code):
            return RedeemResult(RedeemStatus.SUCCESS, code=code, uid="9", nickname="me")

    result = await RedemptionService(_Default()).redeem("genshingift", redeemer=_PerUser())
    assert result.status is RedeemStatus.SUCCESS
    assert result.nickname == "me"


def test_render_not_logged_in_panel_points_to_hoyologin():
    text = _panel("en", "redeem.not_logged_in_h", "redeem.not_logged_in_body")
    assert "hoyologin" in text.lower()
    _no_links(text)


# --- HoYoLAB backend ---------------------------------------------------------


async def test_redeemer_without_cookie_is_auth_failed():
    result = await HoyolabRedeemer("").redeem("GENSHINGIFT")
    assert result.status is RedeemStatus.AUTH_FAILED


def _exc(retcode: int, message: str = "", cls=ge.GenshinException):
    return cls({"retcode": retcode, "message": message or "x"})


@pytest.mark.parametrize(
    "retcode, expected",
    [
        (-2001, RedeemStatus.EXPIRED),
        (-2006, RedeemStatus.EXPIRED),
        (-2003, RedeemStatus.INVALID),
        (-2004, RedeemStatus.INVALID),
        (-2008, RedeemStatus.WRONG_REGION),
        (-2011, RedeemStatus.LEVEL_TOO_LOW),
        (-2016, RedeemStatus.COOLDOWN),
        (-2017, RedeemStatus.ALREADY_REDEEMED),
        (-2018, RedeemStatus.ALREADY_REDEEMED),
        (-100, RedeemStatus.AUTH_FAILED),
        (10001, RedeemStatus.AUTH_FAILED),
    ],
)
def test_map_exception_by_retcode(retcode, expected):
    result = HoyolabRedeemer.map_exception(_exc(retcode), "GENSHINGIFT")
    assert result.status is expected


def test_map_exception_expired_shares_class_with_invalid():
    # -2001 (expired) and -2003 (invalid) are both RedemptionInvalid; retcode must decide.
    assert HoyolabRedeemer.map_exception(_exc(-2001, cls=ge.RedemptionInvalid), "C").status is RedeemStatus.EXPIRED
    assert HoyolabRedeemer.map_exception(_exc(-2003, cls=ge.RedemptionInvalid), "C").status is RedeemStatus.INVALID


def test_map_exception_unknown_is_server_error():
    assert HoyolabRedeemer.map_exception(_exc(-9999, "weird"), "C").status is RedeemStatus.SERVER_ERROR


async def test_redeemer_success_path_with_injected_client():
    class _Account:
        uid = 1813698313
        nickname = "Chronoa"

    class _FakeClient:
        async def get_game_accounts(self):
            return [_Account()]

        async def redeem_code(self, code, game=None, **kw):
            return None  # success

    r = HoyolabRedeemer("cookie_token_v2=abc; account_id_v2=1")
    r._client = _FakeClient()  # inject so no network / real genshin.Client is built
    result = await r.redeem("genshingift")
    assert result.status is RedeemStatus.SUCCESS
    assert result.uid == "1813698313"
    assert result.nickname == "Chronoa"
    assert result.region == "Asia"  # derived from the 18-prefixed UID


async def test_redeemer_maps_failure_from_injected_client():
    class _FakeClient:
        async def get_game_accounts(self):
            return []

        async def redeem_code(self, code, game=None, **kw):
            raise ge.RedemptionClaimed({"retcode": -2017, "message": "already"})

    r = HoyolabRedeemer("cookie=1")
    r._client = _FakeClient()
    result = await r.redeem("genshingift")
    assert result.status is RedeemStatus.ALREADY_REDEEMED


# --- rendering: premium, no links, no buttons --------------------------------


def _no_links(text: str) -> None:
    lowered = text.lower()
    assert "http" not in lowered
    assert "button" not in lowered
    assert "open redemption" not in lowered


def test_render_success_lists_returned_rewards():
    result = RedeemResult(
        RedeemStatus.SUCCESS, code="GENSHINGIFT",
        rewards=["Primogems ×60", "Hero's Wit ×5"],
    )
    text = _render(result, "en")
    assert isinstance(text, str)  # no (text, markup) tuple
    for expected in ("Redemption Successful", "Rewards Received",
                     "Primogems ×60", "Hero's Wit ×5", "Enjoy your adventure"):
        assert expected in text
    _no_links(text)


def test_render_success_omits_rewards_block_when_none_returned():
    text = _render(RedeemResult(RedeemStatus.SUCCESS, code="GENSHINGIFT"), "en")
    assert "Redemption Successful" in text
    assert "Rewards Received" not in text  # never fabricate rewards we didn't get back
    _no_links(text)


def test_render_success_escapes_reward_text():
    text = _render(RedeemResult(RedeemStatus.SUCCESS, code="X", rewards=["<b>hax"]), "en")
    assert "&lt;b&gt;hax" in text
    assert "<b>hax" not in text


@pytest.mark.parametrize(
    "status, marker",
    [
        (RedeemStatus.INVALID, "Redeem Failed"),
        (RedeemStatus.EXPIRED, "Redeem Failed"),
        (RedeemStatus.ALREADY_REDEEMED, "Already Redeemed"),
        (RedeemStatus.AUTH_FAILED, "Authentication Failed"),
        (RedeemStatus.COOLDOWN, "Temporary Error"),
        (RedeemStatus.SERVER_ERROR, "Temporary Error"),
        (RedeemStatus.WRONG_REGION, "Redeem Failed"),
        (RedeemStatus.LEVEL_TOO_LOW, "Redeem Failed"),
    ],
)
def test_render_all_layouts(status, marker):
    text = _render(RedeemResult(status, code="GENSHINGIFT"), "en")
    assert marker in text
    _no_links(text)


def test_render_invalid_shows_official_hint():
    text = _render(RedeemResult(RedeemStatus.INVALID, code="BADCODE"), "en")
    assert "official HoYoverse redeem codes" in text


def test_render_expired_shows_expired_copy():
    text = _render(RedeemResult(RedeemStatus.EXPIRED, code="GENSHINGIFT"), "en")
    assert "expired" in text.lower()
    assert "Better luck on the next code" in text


# --- duplicate-submission guard ---------------------------------------------


def test_in_flight_guard_blocks_second_submission():
    _IN_FLIGHT.discard(777)
    try:
        assert _acquire(777) is True      # first submission claims the slot
        assert _acquire(777) is False     # duplicate while in progress is blocked
        _release(777)
        assert _acquire(777) is True      # freed after completion
    finally:
        _release(777)
