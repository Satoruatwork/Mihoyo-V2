"""The normalized object the card renderer consumes.

This is the contract between the data pipeline and the renderer. Everything here is already
resolved and *already formatted as display strings* — the renderer decides where text goes,
never what it should say. Keeping formatting on this side means the base-stat panel and the
bottom summary are guaranteed to agree, because both read the same fields.

The renderer performs no API calls; :func:`from_character` adapts a domain
:class:`~bot.models.character.Character` (plus pre-fetched images) into this shape.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from bot.renderer.card_layout import canonical_element
from bot.renderer.image_fitter import DEFAULT_ADJUSTMENT, Adjustment

# Element -> the FIGHT_PROP key holding its damage bonus.
_ELEM_DMG_PROP = {
    "PYRO": "FIGHT_PROP_FIRE_ADD_HURT",
    "HYDRO": "FIGHT_PROP_WATER_ADD_HURT",
    "ELECTRO": "FIGHT_PROP_ELEC_ADD_HURT",
    "CRYO": "FIGHT_PROP_ICE_ADD_HURT",
    "ANEMO": "FIGHT_PROP_WIND_ADD_HURT",
    "GEO": "FIGHT_PROP_ROCK_ADD_HURT",
    "DENDRO": "FIGHT_PROP_GRASS_ADD_HURT",
}
_ASCENSION_MAX_LEVEL = {0: 20, 1: 40, 2: 50, 3: 60, 4: 70, 5: 80, 6: 90}
# Weapon secondary stats are percentages except EM (Enka names ATK% just "ATK").
_FLAT_SUB_STATS = ("elemental mastery",)


def _num(value: float | None) -> str:
    return "--" if value is None else f"{value:,.0f}"


def _pct(value: float | None) -> str:
    return "--" if value is None else f"{value:.1f}%"


@dataclass(slots=True)
class CharacterInfo:
    id: str = ""
    name: str = ""
    element: str | None = None
    rarity: int | None = None
    level: int = 1
    constellation: int = 0
    friendship: int | None = None
    max_level: int = 90
    weapon_type: str = ""


@dataclass(slots=True)
class WeaponInfo:
    name: str = ""
    rarity: int | None = None
    base_attack: str = ""
    secondary_stat: str = ""
    secondary_stat_name: str = ""
    level_text: str = ""
    refinement_text: str = ""


@dataclass(slots=True)
class TalentInfo:
    level_text: str = ""
    level: int = 1
    image: object | None = None


@dataclass(slots=True)
class ArtifactInfo:
    rarity: int | None = None
    level: int = 0
    main_stat: str = ""
    main_value: str = ""
    substats: list[tuple[str, str]] = field(default_factory=list)
    image: object | None = None


@dataclass(slots=True)
class SetInfo:
    name: str = ""
    two_piece: str = ""
    four_piece: str = ""
    image: object | None = None
    count: int = 0
    # Any other equipped sets, as (name, pieces), so a 4+1 or 2+2 build is shown honestly.
    others: list[tuple[str, int]] = field(default_factory=list)


@dataclass(slots=True)
class ConstellationInfo:
    unlocked: bool = False
    image: object | None = None


@dataclass(slots=True)
class StatBlock:
    """Formatted stat strings. One source for both the panel and the bottom summary."""

    hp: str = "--"
    atk: str = "--"
    defense: str = "--"
    em: str = "--"
    crit_rate: str = "--"
    crit_dmg: str = "--"
    energy_recharge: str = "--"
    elemental_bonus: str = "--"
    elemental_bonus_name: str = "DMG Bonus"
    crit_value: str = "--"

    def rows(self):
        """(slot-key, value) for the base-stats panel."""
        return (
            ("hp", self.hp), ("atk", self.atk), ("def", self.defense), ("em", self.em),
            ("crit-rate", self.crit_rate), ("crit-dmg", self.crit_dmg),
            ("energy-recharge", self.energy_recharge),
            ("elemental-bonus", self.elemental_bonus),
        )

    def summary_rows(self):
        """(slot-key, value) for the bottom bar — the same values, never recomputed."""
        return (
            ("crit-rate", self.crit_rate), ("crit-dmg", self.crit_dmg),
            ("er", self.energy_recharge), ("atk", self.atk), ("def", self.defense),
            ("em", self.em), ("elemental-bonus", self.elemental_bonus),
        )


@dataclass(slots=True)
class CardData:
    """Everything one card needs. Fully resolved; the renderer only positions it."""

    character: CharacterInfo = field(default_factory=CharacterInfo)
    weapon: WeaponInfo | None = None
    stats: StatBlock = field(default_factory=StatBlock)
    talents: dict[str, TalentInfo] = field(default_factory=dict)
    artifacts: dict[str, ArtifactInfo | None] = field(default_factory=dict)
    artifact_set: SetInfo | None = None
    constellations: list[ConstellationInfo] = field(default_factory=list)
    player_name: str = ""
    player_uid: str = ""
    portrait: object | None = None
    weapon_image: object | None = None
    glow: tuple[int, int, int] = (60, 62, 82)
    character_adjustment: Adjustment = DEFAULT_ADJUSTMENT


def _weapon_sub_text(name: str | None, value: float) -> str:
    label = (name or "").strip().lower()
    is_flat = any(label == flat or label.endswith(f" {flat}") for flat in _FLAT_SUB_STATS)
    return f"{value:,.0f}" if is_flat else f"{value:.1f}%"


def _elemental_bonus(stats, element: str | None) -> float:
    """The character's own elemental damage bonus, as a percentage."""
    canon = canonical_element(element)
    extra = getattr(stats, "extra", None) or {}
    key = _ELEM_DMG_PROP.get(canon or "")
    value = extra.get(key) if key else None
    if value is None:
        # No element-specific bonus present: fall back to the largest bonus reported.
        bonuses = [v for k, v in extra.items() if k.endswith("_ADD_HURT")]
        value = max(bonuses) if bonuses else 0.0
    # Enka reports these as fractions (0.466 == 46.6%).
    return float(value) * 100.0 if value <= 5 else float(value)


def from_character(character, *, portrait=None, icons=None, glow=(60, 62, 82),
                   adjustment: Adjustment = DEFAULT_ADJUSTMENT, player=None) -> CardData:
    """Adapt a domain character (+ pre-fetched images) into renderer-ready data."""
    icons = icons or {}
    canon = canonical_element(character.element)
    stats = character.stats

    block = StatBlock(
        hp=_num(stats.hp), atk=_num(stats.atk), defense=_num(stats.defense),
        em=_num(stats.elemental_mastery), crit_rate=_pct(stats.crit_rate),
        crit_dmg=_pct(stats.crit_dmg), energy_recharge=_pct(stats.energy_recharge),
        elemental_bonus=_pct(_elemental_bonus(stats, character.element)),
        # Dynamic per §"ELEMENTAL DAMAGE": never a hardcoded "Pyro DMG Bonus".
        elemental_bonus_name=f"{(canon or 'Elemental').title()} DMG Bonus",
        # CRIT Value (2 x CRIT Rate + CRIT DMG): derived from the same live stats.
        crit_value=f"{2 * stats.crit_rate + stats.crit_dmg:.1f}",
    )

    weapon = None
    if character.weapon is not None:
        w = character.weapon
        max_level = _ASCENSION_MAX_LEVEL.get(w.ascension, w.level)
        weapon = WeaponInfo(
            name=w.name or "", rarity=w.rarity,
            base_attack=_num(w.main_stat_value) if w.main_stat_value is not None else "",
            secondary_stat=(_weapon_sub_text(w.sub_stat_name, w.sub_stat_value)
                            if w.sub_stat_value is not None else ""),
            secondary_stat_name=w.sub_stat_name or "",
            level_text=f"Lv. {w.level} / {max_level}",
            refinement_text=f"R{w.refinement}",
        )

    talents: dict[str, TalentInfo] = {}
    for name, talent in zip(("normal", "skill", "burst"), character.talents[:3]):
        talents[name] = TalentInfo(level_text=f"Lv. {talent.level}", level=talent.level,
                                   image=icons.get(talent.icon))

    artifacts: dict[str, ArtifactInfo | None] = {}
    by_slot = {a.slot.lower(): a for a in (character.artifacts or [])}
    for slot in ("flower", "plume", "sands", "goblet", "circlet"):
        art = by_slot.get(slot)
        if art is None:
            artifacts[slot] = None
            continue
        main = art.main_stat
        artifacts[slot] = ArtifactInfo(
            rarity=art.rarity, level=art.level,
            main_stat=(main.name if main else ""),
            main_value=(_pct(main.value) if main and main.is_percent
                        else _num(main.value) if main else ""),
            substats=[(s.name, f"+{_pct(s.value)}" if s.is_percent else f"+{_num(s.value)}")
                      for s in art.sub_stats[:4]],
            image=icons.get(art.icon),
        )

    # The set shown is whichever set the most equipped pieces belong to.
    counts: dict[str, int] = {}
    set_icons: dict[str, str] = {}
    for a in character.artifacts or []:
        if a.set_name:
            counts[a.set_name] = counts.get(a.set_name, 0) + 1
            set_icons.setdefault(a.set_name, a.icon or "")
    artifact_set = None
    if counts:
        best = max(counts, key=counts.get)
        artifact_set = SetInfo(
            name=best, count=counts[best], image=icons.get(set_icons.get(best)),
            others=sorted(((n, c) for n, c in counts.items() if n != best),
                          key=lambda item: -item[1]),
        )

    return CardData(
        artifact_set=artifact_set,
        character=CharacterInfo(
            id=character.id, name=character.name, element=character.element,
            rarity=character.rarity, level=character.level,
            constellation=character.constellation, friendship=character.friendship,
            max_level=_ASCENSION_MAX_LEVEL.get(character.ascension, character.level),
            weapon_type=(character.weapon.weapon_type or "") if character.weapon else "",
        ),
        constellations=[ConstellationInfo(unlocked=n.unlocked, image=icons.get(n.icon))
                        for n in (character.constellations or [])[:6]],
        player_name=getattr(player, "nickname", None) or "",
        player_uid=str(getattr(player, "uid", None) or ""),
        weapon=weapon, stats=block, talents=talents, artifacts=artifacts,
        portrait=portrait,
        weapon_image=icons.get(character.weapon.icon) if character.weapon else None,
        glow=glow, character_adjustment=adjustment,
    )
