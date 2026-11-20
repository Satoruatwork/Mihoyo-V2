"""Enumerations shared across the engine.

Kept free of any behavior so they can be imported anywhere without pulling in heavy
dependencies (no PIL, no aiohttp).
"""

from __future__ import annotations

from enum import Enum


class Language(str, Enum):
    """Supported localization codes (mapped to Enka's ``lang`` query values)."""

    EN = "en"
    ES = "es"
    IT = "it"
    JA = "ja"
    ZH = "zh-cn"

    @classmethod
    def parse(cls, value: str | None) -> "Language":
        if not value:
            return cls.EN
        value = value.lower()
        for member in cls:
            if member.value == value or member.name.lower() == value:
                return member
        # Accept common short forms (e.g. "zh").
        if value.startswith("zh"):
            return cls.ZH
        return cls.EN


class Element(str, Enum):
    """Genshin elemental types; ``UNKNOWN`` keeps rendering safe for new/missing data."""

    PYRO = "Pyro"
    HYDRO = "Hydro"
    ELECTRO = "Electro"
    CRYO = "Cryo"
    ANEMO = "Anemo"
    GEO = "Geo"
    DENDRO = "Dendro"
    UNKNOWN = "Unknown"

    @classmethod
    def parse(cls, value: str | None) -> "Element":
        if not value:
            return cls.UNKNOWN
        key = value.strip().capitalize()
        # Enka uses names like "Fire"/"Water"/"Elec"/"Ice"/"Wind"/"Rock"/"Grass".
        alias = {
            "Fire": cls.PYRO, "Water": cls.HYDRO, "Elec": cls.ELECTRO,
            "Ice": cls.CRYO, "Wind": cls.ANEMO, "Rock": cls.GEO, "Grass": cls.DENDRO,
        }
        if key in alias:
            return alias[key]
        for member in cls:
            if member.value == key:
                return member
        return cls.UNKNOWN


class Anchor(str, Enum):
    """Horizontal text/component anchoring used by the layout components."""

    LEFT = "left"
    CENTER = "center"
    RIGHT = "right"
