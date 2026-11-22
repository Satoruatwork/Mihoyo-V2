"""Circuit breaker for database clients — skip a known-down backend for a cooldown."""

from __future__ import annotations

import time


class CircuitBreaker:
    """Skip a known-down backend for ``cooldown`` seconds."""

    def __init__(self, cooldown: float = 30.0) -> None:
        self._cooldown = cooldown
        self._open_until = 0.0

    def is_open(self) -> bool:
        return time.monotonic() < self._open_until

    def record_failure(self) -> None:
        self._open_until = time.monotonic() + self._cooldown

    def record_success(self) -> None:
        self._open_until = 0.0
