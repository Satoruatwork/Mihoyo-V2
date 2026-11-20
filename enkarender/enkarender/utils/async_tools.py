"""Async concurrency helpers."""

from __future__ import annotations

import asyncio
from typing import Awaitable, Callable, Iterable, TypeVar

K = TypeVar("K")
V = TypeVar("V")
T = TypeVar("T")


async def gather_map(
    keys: Iterable[K],
    coro_factory: Callable[[K], Awaitable[V]],
    *,
    limit: int | None = None,
) -> dict[K, V]:
    """Run ``coro_factory(key)`` for every key concurrently, returning ``{key: result}``.

    Keys whose coroutine raises or returns ``None`` are omitted from the result, so the
    caller always gets a clean mapping of successes. ``limit`` caps in-flight coroutines
    via a semaphore (useful to avoid opening hundreds of sockets at once).
    """
    keys = list(dict.fromkeys(keys))  # de-duplicate, preserve order
    semaphore = asyncio.Semaphore(limit) if limit else None

    async def _run(key: K) -> tuple[K, V | None]:
        if semaphore is None:
            return key, await _safe(coro_factory(key))
        async with semaphore:
            return key, await _safe(coro_factory(key))

    pairs = await asyncio.gather(*(_run(k) for k in keys))
    return {k: v for k, v in pairs if v is not None}


async def _safe(coro: Awaitable[V]) -> V | None:
    try:
        return await coro
    except Exception:  # noqa: BLE001 - a single failure must not abort the batch
        return None


async def run_in_thread(func: Callable[..., T], *args, **kwargs) -> T:
    """Run a blocking callable in the default thread pool (keeps the loop responsive)."""
    return await asyncio.to_thread(func, *args, **kwargs)
