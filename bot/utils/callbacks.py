"""Compact encoding/decoding for Telegram inline-button ``callback_data``.

Telegram limits ``callback_data`` to 64 bytes. We encode navigation state as a
pipe-delimited string so the character-showcase flow can switch pages and open/close
character views **without rerunning the command** — the full state is reconstructable
from the button that was pressed (combined with the cached showcase).

Format::

    <action>|<uid>|<char_id>|<page>|<owner>

``owner`` is the Telegram user id that created the menu, so only that user may operate it.
Empty fields are allowed (rendered as an empty segment). Example::

    char|901211014|10000046|0|42  -> open character 10000046 for UID, from page 0, owner 42
    list|901211014||2|42          -> show character list page 2, owner 42
    noop||||                      -> disabled / decorative button
"""

from __future__ import annotations

from dataclasses import dataclass

SEP = "|"
MAX_CALLBACK_BYTES = 64

# Navigation actions.
ACTION_LIST = "list"      # show the character-selection list (a given page)
ACTION_CHAR = "char"      # open a specific character's build
ACTION_PAGE = "page"      # change page within the list
ACTION_BACK = "back"      # return to the list from a character view
ACTION_NOOP = "noop"      # decorative / disabled button


@dataclass(frozen=True)
class Callback:
    """Decoded callback payload."""

    action: str
    uid: str = ""
    char_id: str = ""
    page: int = 0
    owner: int = 0  # Telegram user id allowed to operate this menu (0 = unrestricted/legacy)


def encode(action: str, *, uid: str = "", char_id: str = "", page: int = 0, owner: int = 0) -> str:
    """Encode a callback payload into a ``callback_data`` string.

    Raises:
        ValueError: if the encoded payload exceeds Telegram's 64-byte limit.
    """
    data = SEP.join([action, str(uid), str(char_id), str(page), str(owner)])
    if len(data.encode("utf-8")) > MAX_CALLBACK_BYTES:
        raise ValueError(f"callback_data too long ({len(data)} chars): {data!r}")
    return data


def extract_owner(data: str) -> int:
    """Return the owner user id carried by any project callback payload, or 0.

    Owner is always the final segment of the payload. Character-menu payloads are
    ``|``-delimited and language/settings payloads are ``:``-delimited, so we read the last
    token after whichever separator the payload uses. Payloads without a numeric trailing
    owner (legacy or non-owned) yield 0, i.e. unrestricted. Used by the universal ownership
    gate so the check works for every inline keyboard without per-handler logic.
    """
    if not data:
        return 0
    if SEP in data:
        token = data.rsplit(SEP, 1)[-1]
    elif ":" in data:
        token = data.rsplit(":", 1)[-1]
    else:
        return 0
    return int(token) if token.isdigit() else 0


def decode(data: str) -> Callback:
    """Decode a ``callback_data`` string into a :class:`Callback`.

    Tolerates malformed input by returning a NOOP callback rather than raising, so a
    stale or corrupt button can never crash the handler.
    """
    parts = (data or "").split(SEP)
    # Pad to 5 fields so unpacking is always safe (legacy 4-field data -> owner 0).
    parts += [""] * (5 - len(parts))
    action, uid, char_id, page_raw, owner_raw = parts[:5]
    try:
        page = int(page_raw) if page_raw else 0
    except ValueError:
        page = 0
    try:
        owner = int(owner_raw) if owner_raw else 0
    except ValueError:
        owner = 0
    return Callback(action=action or ACTION_NOOP, uid=uid, char_id=char_id, page=page, owner=owner)
