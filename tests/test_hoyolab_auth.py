"""Tests for per-user HoYoLAB session storage + the auth service.

The genshin.py-backed validator is replaced with a fake redeemer so no network is touched.
"""

from __future__ import annotations

from bot.services.hoyolab_auth_service import HoyolabAuthService
from bot.services.redemption_service import RedeemResult, RedeemStatus
from bot.utils.crypto import CookieCipher

_COOKIE = "cookie_token_v2=abc; account_id_v2=1813698313"


class _FakeRedeemer:
    """Stands in for HoyolabRedeemer: validate() returns a preset result."""

    def __init__(self, result: RedeemResult) -> None:
        self._result = result

    async def validate(self) -> RedeemResult:
        return self._result


def _service(store, *, validate_result: RedeemResult, secret: str = "unit-test-secret"):
    factory = lambda cookie: _FakeRedeemer(validate_result)  # noqa: E731
    return HoyolabAuthService(store, CookieCipher(secret), redeemer_factory=factory)


# --- store cookie round-trip -------------------------------------------------


async def test_store_cookie_set_get_clear(store):
    assert await store.get_hoyolab_cookie(1) is None
    await store.set_hoyolab_cookie(1, "ENCRYPTED")
    assert await store.get_hoyolab_cookie(1) == "ENCRYPTED"
    assert await store.clear_hoyolab_cookie(1) is True
    assert await store.get_hoyolab_cookie(1) is None
    assert await store.clear_hoyolab_cookie(1) is False


# --- login / logout ----------------------------------------------------------


async def test_login_success_stores_encrypted_cookie(store):
    ok = RedeemResult(RedeemStatus.SUCCESS, code="", uid="1813698313", nickname="Chronoa", region="Asia")
    svc = _service(store, validate_result=ok)

    result = await svc.login(42, _COOKIE)
    assert result.status is RedeemStatus.SUCCESS
    assert result.nickname == "Chronoa"

    # Stored value is encrypted (not the raw cookie) but decrypts back via the service.
    stored = await store.get_hoyolab_cookie(42)
    assert stored is not None and stored != _COOKIE
    assert await svc.get_cookie(42) == _COOKIE
    assert await svc.is_logged_in(42) is True


async def test_login_failure_stores_nothing(store):
    bad = RedeemResult(RedeemStatus.AUTH_FAILED, code="")
    svc = _service(store, validate_result=bad)

    result = await svc.login(42, _COOKIE)
    assert result.status is RedeemStatus.AUTH_FAILED
    assert await store.get_hoyolab_cookie(42) is None  # nothing persisted on failure
    assert await svc.is_logged_in(42) is False


async def test_empty_cookie_rejected_without_calling_backend(store):
    def _boom(cookie):
        raise AssertionError("validator must not run for an empty cookie")

    svc = HoyolabAuthService(store, CookieCipher("s"), redeemer_factory=_boom)
    result = await svc.login(42, "   ")
    assert result.status is RedeemStatus.AUTH_FAILED


async def test_logout_clears_session(store):
    ok = RedeemResult(RedeemStatus.SUCCESS, code="", uid="1", nickname="x")
    svc = _service(store, validate_result=ok)
    await svc.login(7, _COOKIE)
    assert await svc.logout(7) is True
    assert await svc.get_cookie(7) is None
    assert await svc.logout(7) is False


async def test_disabled_when_secret_missing(store):
    svc = _service(store, validate_result=RedeemResult(RedeemStatus.SUCCESS, code=""), secret="")
    assert svc.enabled is False


async def test_get_cookie_none_when_not_logged_in(store):
    svc = _service(store, validate_result=RedeemResult(RedeemStatus.SUCCESS, code=""))
    assert await svc.get_cookie(999) is None
