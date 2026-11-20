"""Pixel coordinate map + element themes for the character profile card.

All coordinates target the fixed 1280x720 template. They are intentionally kept as data so
the renderer never computes layout — it only draws live values at these positions. Tune the
numbers here to align with the template; the renderer reads them verbatim.
"""

from __future__ import annotations

CARD_SIZE = (1280, 720)

# --- Element themes -------------------------------------------------------------------
# `bg`: background tint applied behind the character / across the card so the whole card
#       takes on the element's colour ("green character -> green background").
# `accent`: borders / accent lines / labels. `glow`: portrait backdrop glow.
ELEMENT_THEMES: dict[str, dict[str, tuple[int, int, int]]] = {
    "PYRO": {"bg": (168, 54, 40), "accent": (255, 120, 70), "glow": (255, 90, 50)},
    "HYDRO": {"bg": (30, 92, 168), "accent": (80, 180, 255), "glow": (60, 150, 255)},
    "ELECTRO": {"bg": (108, 60, 168), "accent": (190, 120, 255), "glow": (170, 90, 255)},
    "CRYO": {"bg": (96, 150, 180), "accent": (170, 230, 255), "glow": (150, 220, 255)},
    "ANEMO": {"bg": (30, 140, 118), "accent": (90, 220, 180), "glow": (70, 210, 165)},
    "GEO": {"bg": (170, 120, 30), "accent": (240, 190, 70), "glow": (235, 175, 55)},
    "DENDRO": {"bg": (70, 140, 30), "accent": (150, 220, 80), "glow": (130, 210, 60)},
}
DEFAULT_THEME = {"bg": (60, 62, 82), "accent": (200, 180, 120), "glow": (150, 150, 170)}

# Enka reports elements by their in-data names (Fire/Water/…); map to canonical elements.
_ELEMENT_ALIASES = {
    "FIRE": "PYRO", "PYRO": "PYRO",
    "WATER": "HYDRO", "HYDRO": "HYDRO",
    "ELECTRIC": "ELECTRO", "ELECTRO": "ELECTRO",
    "ICE": "CRYO", "CRYO": "CRYO",
    "WIND": "ANEMO", "ANEMO": "ANEMO",
    "ROCK": "GEO", "GEO": "GEO",
    "GRASS": "DENDRO", "DENDRO": "DENDRO",
}


def canonical_element(element: str | None) -> str | None:
    """Normalize any element spelling (e.g. 'Fire') to a canonical key (e.g. 'PYRO')."""
    if not element:
        return None
    key = element.strip().upper()
    if key in _ELEMENT_ALIASES:
        return _ELEMENT_ALIASES[key]
    for canon in ELEMENT_THEMES:
        if canon in key:
            return canon
    return None


def theme_for(element: str | None) -> dict[str, tuple[int, int, int]]:
    canon = canonical_element(element)
    return ELEMENT_THEMES.get(canon, DEFAULT_THEME) if canon else DEFAULT_THEME


# --- Portrait -------------------------------------------------------------------------
# Inner window of the character frame (left, top, right, bottom). The baked frame is a
# rounded "stadium" (pill), NOT an ellipse — the art is clipped to a rounded rectangle whose
# corner radius is half its width so it fills the frame instead of leaving gaps at the sides.
PORTRAIT_BOX = (158, 116, 344, 596)

# --- Header ---------------------------------------------------------------------------
# Measured against the approved reference card: its name glyphs occupy y=33..63 (cap height
# ~30px) and run out to x=377 — wider than the 250px cap this used to impose. NAME_POS is a
# text top-left, which for this font sits ~17px above the cap line.
NAME_POS = (118, 17)             # top-left anchor, big
NAME_MAX_WIDTH = 262
RARITY_STARS_POS = (120, 74)     # header rarity stars (top-left)
TITLE_POS = (120, 96)

# --- Left rail: 6 constellation node centres (top emblem = C1, then 5 below) -----------
CONSTELLATION_NODES = [(58, 165), (58, 233), (58, 295), (58, 357), (58, 418), (58, 480)]
CONSTELLATION_NODE_RADIUS = 26
FRIENDSHIP_POS = (120, 560)      # value drawn after the "Friendship" pill label

# --- Icon boxes (centre, size) for dynamically-fetched icons --------------------------
WEAPON_ICON_BOX = (445, 168, 78)          # (cx, cy, diameter)
TALENT_ICON_BOXES = [(428, 565, 44), (492, 565, 44), (557, 565, 44)]
SET_ICON_BOX = (774, 500, 30)             # (cx, cy, diameter) — square slot, top-right of panel
# Measured from the reference: icon centres sit at cx=935 and cy 100/216/333/445/560 (card
# pitch exactly 115 — the old 113 drifted up to 12px off on the first card and never
# re-converged). Measured centres (100/216/333/445/560) carry a couple of px of blob-detection
# jitter, so the grid is regularised to the exact 115 pitch its endpoints imply.
ARTIFACT_ICON_BOXES = [                    # (cx, cy, diameter) per card
    (935, 100, 66), (935, 215, 66), (935, 330, 66), (935, 445, 66), (935, 560, 66),
]

# --- Top level/constellation/rarity bar ----------------------------------------------
LEVEL_VALUE_POS = (450, 62)      # centered under LEVEL
CONSTELLATION_VALUE_POS = (603, 66)  # centered in the circle (e.g. "6")
RARITY_BAR_STARS_POS = (770, 66)     # centered under RARITY

# --- Weapon panel ---------------------------------------------------------------------
WEAPON_ICON_CENTER = (445, 168)
WEAPON_ICON_RADIUS = 42
WEAPON_NAME_POS = (525, 138)
WEAPON_NAME_MAX_WIDTH = 300
# The two boxes hold the weapon's base ATK and its secondary stat (measured: the glyphs sit
# at x=565 and x=672, both centred on y=174, just right of each box's baked icon).
WEAPON_MAIN_STAT_POS = (565, 174)
WEAPON_SUB_STAT_POS = (672, 174)
WEAPON_LEVEL_POS = (515, 213)    # left anchor for "Lv. 90" (baked "Lv. /" masked first)
WEAPON_REFINE_POS = (818, 177)   # centered in the dark "R" box (e.g. "R5")

# --- Base stats (right-aligned values per row) ----------------------------------------
BASE_STAT_VALUE_X = 825          # right edge for values
BASE_STAT_ROWS_Y = {            # y baseline per labelled row (order matches template)
    "hp": 283,
    "atk": 307,
    "defense": 331,
    "elemental_mastery": 355,
    "crit_rate": 379,
    "crit_dmg": 402,
    "energy_recharge": 425,
    "elemental_bonus": 448,
}

# --- Talents (levels under each of the 3 icons) ---------------------------------------
TALENT_LEVEL_POS = [(428, 600), (492, 600), (557, 600)]  # NA, Skill, Burst

# --- Set bonus ------------------------------------------------------------------------
SET_NAME_POS = (615, 523)   # left anchor (baked "SET NAME" masked first)
SET_2PC_POS = (662, 552)
SET_4PC_POS = (662, 598)

# --- Artifacts (5 cards) --------------------------------------------------------------
# Every value below is measured off the approved reference card rather than estimated.
# Card pitch is ~115px (substat row 1 lands at y=71/187/302/416/531), so the previous
# 113px pitch accumulated an 8px error by the fifth card.
ARTIFACT_CARD_TOP = [68, 183, 298, 413, 528]
ARTIFACT_CARD_REF_TOP = 68              # the y the offsets below were measured against

# The main stat is TWO lines in the reference — name at y=100..107, value at y=120..130 —
# not the single "HP 4780" line this used to draw. Positions are row centres (anchor "lm").
ARTIFACT_MAIN_NAME_POS = (988, 104)
ARTIFACT_MAIN_VALUE_POS = (988, 125)
ARTIFACT_MAIN_MAX_WIDTH = 108

ARTIFACT_STARS_POS = (900, 150)

# Substats are two LEFT-aligned columns, not one run-on string. Proven left-aligned rather
# than right-aligned because the short "+72" row starts at the same x=1208 as "+9.7%" and
# simply ends earlier (1227 vs 1241).
ARTIFACT_SUBSTAT_X = 1105               # substat name column
ARTIFACT_SUBSTAT_VALUE_X = 1208         # substat value column
ARTIFACT_SUBSTAT_NAME_MAX_WIDTH = 98    # keeps names clear of the value column
ARTIFACT_SUBSTAT_VALUE_MAX_WIDTH = 56
ARTIFACT_SUBSTAT_YS = [76, 98, 119, 141]  # row centres (anchor "lm")

# --- Bottom summary bar (7 values under labels) ---------------------------------------
BOTTOM_BAR_Y = 678
BOTTOM_BAR_VALUE_X = [78, 190, 320, 440, 535, 665, 808]
# order: CRIT Rate, CRIT DMG, Energy Recharge, ATK, DEF, Elemental Mastery, Elemental Bonus

# --- Akasha ranking badge (drawn only when ranking data exists) -----------------------
RANKING_BADGE_BOX = (378, 640, 838, 712)   # a premium badge strip along the bottom-center
