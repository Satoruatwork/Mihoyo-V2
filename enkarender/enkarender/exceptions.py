"""Typed exception hierarchy.

Every failure the engine raises derives from :class:`EnkaRenderError`, so callers can catch
the whole family with one ``except`` while still being able to distinguish transport,
data, asset, and rendering problems when they care to.
"""

from __future__ import annotations


class EnkaRenderError(Exception):
    """Base class for all engine errors."""


# --- API / transport ---
class ApiError(EnkaRenderError):
    """Base for anything that goes wrong talking to the Enka API."""


class NetworkError(ApiError):
    """A transport-level failure (timeout, connection reset, DNS, …)."""


class RateLimited(ApiError):
    """The API returned HTTP 429."""


class ProfileNotFound(ApiError):
    """The UID is well-formed but no public profile/showcase exists."""


class InvalidUID(ApiError):
    """The UID failed local format validation before any request was made."""


# --- data ---
class ParseError(EnkaRenderError):
    """Raw payload could not be mapped into the domain model."""


class EmptyShowcase(EnkaRenderError):
    """The profile is public but exposes no showcased characters."""


# --- assets / rendering ---
class AssetError(EnkaRenderError):
    """An asset could not be resolved, downloaded, or decoded."""


class TemplateNotFound(EnkaRenderError):
    """No template is registered under the requested key."""


class CardTypeNotFound(EnkaRenderError):
    """No card builder is registered under the requested key."""


class RenderError(EnkaRenderError):
    """The rendering pipeline failed to produce an image."""
