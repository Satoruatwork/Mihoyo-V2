"""Cache interface — backend-agnostic JSON cache contract."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class Cache(ABC):
    """Namespaced JSON cache with TTL. All operations are async and Best-effort."""

    @abstractmethod
    async def get_json(self, namespace: str, key: str) -> Any | None:
        """Return cached value or None on miss/error."""

    @abstractmethod
    async def set_json(self, namespace: str, key: str, value: Any, ttl: int | None = None) -> None:
        """Cache a JSON-serialisable value with an optional TTL override."""

    @abstractmethod
    async def invalidate(self, namespace: str, key: str) -> None:
        """Remove a cached entry (no-op if missing)."""
