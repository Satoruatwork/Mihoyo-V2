"""Text formatting helpers (pure functions, no PIL dependency)."""

from __future__ import annotations


def ellipsize(text: str, max_chars: int) -> str:
    """Truncate ``text`` to ``max_chars`` characters, appending an ellipsis if cut."""
    if max_chars <= 0 or len(text) <= max_chars:
        return text
    if max_chars == 1:
        return "…"
    return text[: max_chars - 1].rstrip() + "…"


def group_digits(value: int | float) -> str:
    """Format a number with thousands separators (e.g. ``12345`` -> ``12,345``)."""
    if isinstance(value, float):
        return f"{value:,.1f}"
    return f"{value:,}"
