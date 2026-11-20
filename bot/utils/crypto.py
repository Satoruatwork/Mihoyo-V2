"""Symmetric encryption for credentials stored at rest (HoYoLAB session cookies).

A single :class:`CookieCipher` is built from the ``HOYOLAB_SECRET`` config value and used to
encrypt each user's cookie before it is written to the store, and to decrypt it when a
redemption runs. If no secret is configured the cipher is *unavailable* and the login flow
refuses to store anything — credentials are never persisted in plaintext.
"""

from __future__ import annotations

import base64
import hashlib

from bot.utils.logging import get_logger

logger = get_logger(__name__)

try:  # cryptography is an optional import so the rest of the bot loads without it.
    from cryptography.fernet import Fernet
except ImportError:  # pragma: no cover - depends on environment
    Fernet = None  # type: ignore[assignment]


class CookieCipher:
    """Fernet-based encrypt/decrypt keyed off a configured secret.

    The Fernet key is derived deterministically from the secret (SHA-256 → urlsafe base64),
    so the same secret always yields the same key across restarts — stored cookies remain
    decryptable as long as ``HOYOLAB_SECRET`` is unchanged.
    """

    def __init__(self, secret: str) -> None:
        self._fernet = None
        secret = (secret or "").strip()
        if secret and Fernet is not None:
            key = base64.urlsafe_b64encode(hashlib.sha256(secret.encode("utf-8")).digest())
            self._fernet = Fernet(key)

    @property
    def available(self) -> bool:
        """True when a secret is configured (and cryptography is installed)."""
        return self._fernet is not None

    def encrypt(self, plaintext: str) -> str:
        if self._fernet is None:
            raise RuntimeError("CookieCipher is not configured (HOYOLAB_SECRET unset)")
        return self._fernet.encrypt(plaintext.encode("utf-8")).decode("ascii")

    def decrypt(self, token: str | None) -> str | None:
        """Return the plaintext, or ``None`` if the cipher is off or the token is unreadable
        (wrong/rotated secret, corruption). Never raises."""
        if self._fernet is None or not token:
            return None
        try:
            return self._fernet.decrypt(token.encode("ascii")).decode("utf-8")
        except Exception as exc:  # noqa: BLE001 - any decode failure is a miss, not a crash
            logger.debug("cookie decrypt failed: %s", exc)
            return None
