"""Logging helpers.

A tiny wrapper so every module logs under the ``enkarender`` namespace with a consistent
format, and applications can raise/lower the whole engine's verbosity with one call.
"""

from __future__ import annotations

import logging

_ROOT = "enkarender"
_configured = False


def configure(level: int | str = logging.INFO) -> None:
    """Attach a stream handler to the ``enkarender`` logger once (idempotent)."""
    global _configured
    logger = logging.getLogger(_ROOT)
    if not _configured:
        handler = logging.StreamHandler()
        handler.setFormatter(
            logging.Formatter("%(asctime)s | %(levelname)-7s | %(name)s | %(message)s")
        )
        logger.addHandler(handler)
        logger.propagate = False
        _configured = True
    logger.setLevel(level)


def get_logger(name: str) -> logging.Logger:
    """Return a child logger under the ``enkarender`` namespace."""
    return logging.getLogger(f"{_ROOT}.{name}")
