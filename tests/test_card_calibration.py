"""Card formatting + layout calibration, measured against the approved reference card.

The numbers asserted here were read off the reference image, not estimated, so a future
tweak that silently drifts the artifact grid or re-breaks the stat formatting will fail.
"""

from __future__ import annotations

from bot.models.artifact import ArtifactStat
from bot.models.weapon import Weapon
from bot.renderer import card_layout
from bot.renderer.pillow_renderer import _stat_value, _weapon_max_level, _weapon_sub_text


# --------------------------------------------------------------------------- stat formatting
def test_substats_are_signed_and_percent_suffixed():
    """Reference renders '+9.7%' / '+72', not the bare 'CRIT Rate 9.7' this used to draw."""
    assert _stat_value(ArtifactStat(name="CRIT Rate", value=9.7, is_percent=True), signed=True) == "+9.7%"
    assert _stat_value(ArtifactStat(name="Elemental Mastery", value=72), signed=True) == "+72"


def test_main_stat_is_unsigned_and_thousands_separated():
    """A main stat is a value, not a gain: '4,780' — with the separator the old code lost."""
    assert _stat_value(ArtifactStat(name="HP", value=4780), signed=False) == "4,780"
    assert _stat_value(ArtifactStat(name="ATK%", value=46.6, is_percent=True), signed=False) == "46.6%"


def test_missing_stat_value_does_not_crash():
    assert _stat_value(ArtifactStat(name="?", value=None), signed=True) == "--"


# --------------------------------------------------------------------------- weapon panel
def test_weapon_secondary_stat_percent_vs_flat():
    assert _weapon_sub_text("CRIT DMG", 22.1) == "22.1%"
    assert _weapon_sub_text("Elemental Mastery", 165) == "165"
    # Enka labels ATK%/HP%/DEF% weapon substats without the "%"; they are never flat.
    assert _weapon_sub_text("ATK", 41.3) == "41.3%"
    assert _weapon_sub_text(None, 22.1) == "22.1%"


def test_weapon_max_level_follows_ascension():
    assert _weapon_max_level(Weapon(name="w", level=90, ascension=6)) == 90
    assert _weapon_max_level(Weapon(name="w", level=70, ascension=4)) == 70
    # Unknown ascension degrades to the current level rather than inventing a cap.
    assert _weapon_max_level(Weapon(name="w", level=55, ascension=99)) == 55


# --------------------------------------------------------------------------- layout geometry
def test_artifact_card_pitch_matches_the_reference():
    """Substat row 1 lands at y=71/187/302/416/531 -> ~115px pitch, not the old 113."""
    tops = card_layout.ARTIFACT_CARD_TOP
    assert len(tops) == 5
    pitches = [tops[i + 1] - tops[i] for i in range(4)]
    assert all(114 <= p <= 116 for p in pitches), pitches
    # The old 113px pitch drifted 8px off by the last card; this must stay tight.
    assert tops[-1] - tops[0] == 460


def test_artifact_icons_share_one_column_and_track_the_cards():
    xs = {box[0] for box in card_layout.ARTIFACT_ICON_BOXES}
    assert xs == {935}, "all five icons sit in one measured column"
    cys = [box[1] for box in card_layout.ARTIFACT_ICON_BOXES]
    assert cys == sorted(cys)
    assert all(114 <= cys[i + 1] - cys[i] <= 117 for i in range(4)), cys


def test_substat_value_column_is_separate_from_the_name_column():
    """Two independent left-aligned columns, so a long name cannot shift its value."""
    assert card_layout.ARTIFACT_SUBSTAT_VALUE_X > card_layout.ARTIFACT_SUBSTAT_X
    # Names must be clipped before they reach the value column.
    assert (card_layout.ARTIFACT_SUBSTAT_X + card_layout.ARTIFACT_SUBSTAT_NAME_MAX_WIDTH
            <= card_layout.ARTIFACT_SUBSTAT_VALUE_X)


def test_main_stat_occupies_two_rows():
    assert card_layout.ARTIFACT_MAIN_VALUE_POS[1] > card_layout.ARTIFACT_MAIN_NAME_POS[1]
    assert card_layout.ARTIFACT_MAIN_NAME_POS[0] == card_layout.ARTIFACT_MAIN_VALUE_POS[0]


def test_substat_rows_are_evenly_spaced():
    ys = card_layout.ARTIFACT_SUBSTAT_YS
    assert len(ys) == 4
    gaps = [ys[i + 1] - ys[i] for i in range(3)]
    assert all(21 <= g <= 23 for g in gaps), gaps


def test_weapon_stat_boxes_are_distinct_and_share_a_baseline():
    main, sub = card_layout.WEAPON_MAIN_STAT_POS, card_layout.WEAPON_SUB_STAT_POS
    assert sub[0] > main[0], "secondary stat sits in the second box"
    assert main[1] == sub[1], "both boxes share one measured baseline"


# --------------------------------------------------------------------------- phase 12
def test_base_stat_rows_match_the_reference_pitch():
    """Measured off the reference: value centres 287..460, pitch ~24.6.

    The previous 283..448 grid drifted up to 9px high by the last row, which is what put
    the numbers on the horizontal rules instead of above them.
    """
    from bot.renderer.slot_manager import get_layout

    layout = get_layout()
    keys = ("hp", "atk", "def", "em", "crit-rate", "crit-dmg",
            "energy-recharge", "elemental-bonus")
    ys = [layout.text_slot(f"stat-{k}").y for k in keys]
    assert ys == sorted(ys)
    assert ys[0] == 287 and ys[-1] == 460
    gaps = [ys[i + 1] - ys[i] for i in range(len(ys) - 1)]
    assert all(24 <= g <= 26 for g in gaps), gaps


def test_set_bonus_icon_has_its_own_slot_inside_the_panel():
    """It must not reuse an artifact slot, and must sit inside the panel's square."""
    from bot.renderer.slot_manager import get_layout

    slot = get_layout().image_slot("artifact-set-image")
    x0, y0, x1, y1 = slot.box
    assert 780 <= x0 and x1 <= 840, slot.box
    assert 495 <= y0 and y1 <= 550, slot.box
    # Distinct from every artifact icon slot.
    others = [get_layout().image_slot(f"artifact-{s}-image").box
              for s in ("flower", "plume", "sands", "goblet", "circlet")]
    assert slot.box not in others
