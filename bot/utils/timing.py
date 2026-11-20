"""Lightweight performance timing helpers.

Emit step/total timings to the dedicated ``bot.perf`` logger so the exact bottleneck of a
command is visible in the logs, e.g.::

    bot.perf | showcase.enka_fetch: 480 ms
    bot.perf | showcase.akasha_fetch: 620 ms
    bot.perf | my_characters total: 1210 ms

These helpers only measure and log — they never alter control flow or results, so they are
safe to wrap around any step without changing behavior. Timing is cheap
(``perf_counter``) and logged at INFO on the ``bot.perf`` logger, which can be silenced
independently by raising that logger's level.
"""

from __future__ import annotations

import time
from contextlib import asynccontextmanager, contextmanager

from bot.utils.logging import get_logger

perf_logger = get_logger("bot.perf")


@contextmanager
def timed(label: str):
    """Sync context manager: log ``label: N ms`` when the block exits."""
    start = time.perf_counter()
    try:
        yield
    finally:
        perf_logger.info("%s: %.0f ms", label, (time.perf_counter() - start) * 1000)


@asynccontextmanager
async def atimed(label: str):
    """Async context manager: log ``label: N ms`` when the block exits."""
    start = time.perf_counter()
    try:
        yield
    finally:
        perf_logger.info("%s: %.0f ms", label, (time.perf_counter() - start) * 1000)
