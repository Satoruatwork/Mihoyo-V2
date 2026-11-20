"""Domain-level exceptions.

API clients map library/HTTP failures into these so the command layer can translate
them into friendly, localized messages. Each exception carries an ``i18n_key`` pointing
at a translation string, so error messaging is centralized and localizable.

The bot must never crash because of an API failure — every one of these is caught by the
command layer and/or the global error handler.
"""

from __future__ import annotations


class BotError(Exception):
    """Base class for all handled, user-facing bot errors.

    Attributes:
        i18n_key: Translation key used to render a friendly message to the user.
        detail: Optional technical detail for logging (never shown to users directly).
    """

    i18n_key: str = "error.generic"

    def __init__(self, detail: str | None = None, *, i18n_key: str | None = None) -> None:
        self.detail = detail
        if i18n_key is not None:
            self.i18n_key = i18n_key
        super().__init__(detail or self.i18n_key)


class InvalidUID(BotError):
    """The supplied UID is malformed (not a plausible Genshin UID)."""

    i18n_key = "error.invalid_uid"


class AccountNotLinked(BotError):
    """The user tried a data command without linking a UID first."""

    i18n_key = "error.not_linked"


class ProfilePrivate(BotError):
    """The player's profile / character showcase is hidden or private."""

    i18n_key = "error.profile_private"


class EmptyShowcase(BotError):
    """The profile is public but has no characters in its showcase."""

    i18n_key = "error.empty_showcase"


class CharacterNotFound(BotError):
    """A requested character is not present in the showcase / data."""

    i18n_key = "error.character_not_found"


class DataUnavailable(BotError):
    """Requested data (abyss, theater, banner, build) is not currently available."""

    i18n_key = "error.data_unavailable"


class RankingUnavailable(BotError):
    """Akasha ranking data is unavailable. Non-fatal: callers usually degrade instead."""

    i18n_key = "error.ranking_unavailable"


class ApiUnavailable(BotError):
    """An upstream API is down, unreachable, or returned an unexpected error."""

    i18n_key = "error.api_unavailable"


class RateLimited(BotError):
    """An upstream API rate-limited the request."""

    i18n_key = "error.rate_limited"


class NetworkError(BotError):
    """A network error or timeout occurred talking to an upstream API."""

    i18n_key = "error.network"


class DatastoreUnavailable(BotError):
    """The primary datastore (Redis) could not be reached for a write.

    Raised by write operations that cannot silently degrade (e.g. linking a UID): the user
    is told to retry, rather than being shown the mysterious generic error.
    """

    i18n_key = "error.datastore_unavailable"
