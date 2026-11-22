"""Persistence interfaces — backend-agnostic contracts for the bot's storage.

Any database backend (Redis, MongoDB, Postgres/Supabase, in-memory) must
implement these protocols. Services depend only on these interfaces, never
on a concrete backend class, which is what makes the storage layer pluggable.

``UserStore`` covers every persistent operation the bot performs today:
user records, language, free-form settings, encrypted HoYoLAB cookies,
registration counters, group tracking and broadcast enumeration.

``DatabaseClient`` covers lifecycle/health checks used at startup and for
``/stats``.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class UserStore(ABC):
    """Abstract persistent user/stats store. Every method is async."""

    # --- user lifecycle -------------------------------------------------
    @abstractmethod
    async def get_or_create(self, telegram_user_id: int, default_language: str = "en") -> dict[str, Any]:
        ...

    @abstractmethod
    async def link_uid(self, telegram_user_id: int, uid: str, default_language: str = "en") -> None:
        ...

    @abstractmethod
    async def unlink_uid(self, telegram_user_id: int) -> bool:
        ...

    @abstractmethod
    async def get_uid(self, telegram_user_id: int) -> str | None:
        ...

    # --- language -------------------------------------------------------
    @abstractmethod
    async def set_language(self, telegram_user_id: int, language: str, default_language: str = "en") -> None:
        ...

    @abstractmethod
    async def get_language(self, telegram_user_id: int, default_language: str = "en") -> str:
        ...

    # --- per-user settings (free-form KV) -------------------------------
    @abstractmethod
    async def set_setting(self, telegram_user_id: int, key: str, value: str) -> None:
        ...

    @abstractmethod
    async def get_setting(self, telegram_user_id: int, key: str, default: str | None = None) -> str | None:
        ...

    @abstractmethod
    async def get_all_settings(self, telegram_user_id: int) -> dict[str, str]:
        ...

    # --- HoYoLAB cookie (encrypted token) -------------------------------
    @abstractmethod
    async def set_hoyolab_cookie(self, telegram_user_id: int, token: str) -> None:
        ...

    @abstractmethod
    async def get_hoyolab_cookie(self, telegram_user_id: int) -> str | None:
        ...

    @abstractmethod
    async def clear_hoyolab_cookie(self, telegram_user_id: int) -> bool:
        ...

    # --- registration / tracking ----------------------------------------
    @abstractmethod
    async def register_interaction(self, telegram_user_id: int, chat_type: str | None) -> None:
        ...

    @abstractmethod
    async def register_group(self, chat_id: int) -> None:
        ...

    @abstractmethod
    async def unregister_group(self, chat_id: int) -> None:
        ...

    # --- broadcast enumeration ------------------------------------------
    @abstractmethod
    async def all_users(self) -> list[int]:
        ...

    @abstractmethod
    async def all_groups(self) -> list[int]:
        ...

    @abstractmethod
    async def discard_users(self, ids: list[int]) -> None:
        ...

    @abstractmethod
    async def discard_groups(self, ids: list[int]) -> None:
        ...

    # --- statistics -----------------------------------------------------
    @abstractmethod
    async def count_users(self) -> int:
        ...

    @abstractmethod
    async def count_private_chats(self) -> int:
        ...

    @abstractmethod
    async def count_groups(self) -> int:
        ...

    @abstractmethod
    async def count_interactions(self) -> int:
        ...


class DatabaseClient(ABC):
    """Abstract database connection/client used for health checks and shutdown."""

    @abstractmethod
    async def verify(self) -> bool:
        """Ping the database. Returns False instead of raising."""

    @abstractmethod
    async def is_healthy(self) -> bool:
        """Lightweight health probe (used by /stats). Never raises."""

    @abstractmethod
    async def close(self) -> None:
        """Release the pool/connections. Never raises."""

    async def self_test(self) -> bool:  # optional
        """Full read/write/delete round-trip. Returns True only if all steps pass."""
        return await self.verify()
