"""API layer: transport + Enka client. Returns raw payloads only — parsing lives in
``enkarender.models`` so the network layer stays independent of the domain model."""

from __future__ import annotations

from enkarender.api.client import EnkaClient
from enkarender.api.http import HttpTransport

__all__ = ["EnkaClient", "HttpTransport"]
