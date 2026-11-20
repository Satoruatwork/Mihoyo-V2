"""Raw Enka payload -> domain model.

The parser is intentionally defensive (every field via ``.get`` with a default) so a schema
drift or a single malformed character never discards the whole showcase. Name-hash and
character-metadata localization are injected as optional callables, so the parser depends on
neither the asset layer nor any bundled text map.
"""

from __future__ import annotations

from typing import Any, Callable, Optional

from enkarender.enums import Element
from enkarender.exceptions import EmptyShowcase, ParseError
from enkarender.logging import get_logger
from enkarender.models.domain import Artifact, Character, Player, Showcase, Stat, Weapon

logger = get_logger("models.parser")

NameResolver = Callable[[Any], Optional[str]]
CharacterResolver = Callable[[str], Optional[dict]]

# Enka fightPropMap keys -> (label, is_percent). Percent props arrive as fractions.
_FIGHT_PROP = {
    "2000": ("HP", False),
    "2001": ("ATK", False),
    "2002": ("DEF", False),
    "20": ("CRIT Rate", True),
    "22": ("CRIT DMG", True),
    "23": ("Energy Recharge", True),
    "28": ("Elemental Mastery", False),
}
_FRACTION_KEYS = {"20", "22", "23"}  # stored 0..1, shown as %

# Equip stat propIds that are percentages (artifact/weapon sub/main stats).
_PERCENT_PROPS = {
    "FIGHT_PROP_HP_PERCENT", "FIGHT_PROP_ATTACK_PERCENT", "FIGHT_PROP_DEFENSE_PERCENT",
    "FIGHT_PROP_CRITICAL", "FIGHT_PROP_CRITICAL_HURT", "FIGHT_PROP_CHARGE_EFFICIENCY",
    "FIGHT_PROP_HEAL_ADD",
}
_PROP_LABELS = {
    "FIGHT_PROP_HP": "HP", "FIGHT_PROP_HP_PERCENT": "HP",
    "FIGHT_PROP_ATTACK": "ATK", "FIGHT_PROP_ATTACK_PERCENT": "ATK",
    "FIGHT_PROP_DEFENSE": "DEF", "FIGHT_PROP_DEFENSE_PERCENT": "DEF",
    "FIGHT_PROP_CRITICAL": "CRIT Rate", "FIGHT_PROP_CRITICAL_HURT": "CRIT DMG",
    "FIGHT_PROP_CHARGE_EFFICIENCY": "Energy Recharge",
    "FIGHT_PROP_ELEMENT_MASTERY": "Elemental Mastery",
    "FIGHT_PROP_BASE_ATTACK": "Base ATK",
    "FIGHT_PROP_HEAL_ADD": "Healing Bonus",
    "FIGHT_PROP_FIRE_ADD_HURT": "Pyro DMG", "FIGHT_PROP_WATER_ADD_HURT": "Hydro DMG",
    "FIGHT_PROP_ELEC_ADD_HURT": "Electro DMG", "FIGHT_PROP_ICE_ADD_HURT": "Cryo DMG",
    "FIGHT_PROP_WIND_ADD_HURT": "Anemo DMG", "FIGHT_PROP_ROCK_ADD_HURT": "Geo DMG",
    "FIGHT_PROP_GRASS_ADD_HURT": "Dendro DMG", "FIGHT_PROP_PHYSICAL_ADD_HURT": "Physical DMG",
}
# Any *_ADD_HURT prop is a percentage bonus.
_PERCENT_SUFFIXES = ("_ADD_HURT", "_PERCENT")
_SLOT_NAMES = {
    "EQUIP_BRACER": "Flower", "EQUIP_NECKLACE": "Plume", "EQUIP_SHOES": "Sands",
    "EQUIP_RING": "Goblet", "EQUIP_DRESS": "Circlet",
}


def parse_showcase(
    raw: dict[str, Any],
    *,
    resolve_name: NameResolver | None = None,
    resolve_character: CharacterResolver | None = None,
) -> Showcase:
    """Map a raw Enka payload into a :class:`Showcase`.

    ``resolve_name`` maps a ``nameTextMapHash`` to a localized display string.
    ``resolve_character`` maps an ``avatarId`` to ``{name, element, rarity, portrait}``.
    Both are optional; when absent, ids/hashes are used verbatim (still renderable).
    """
    if not isinstance(raw, dict):
        raise ParseError("payload is not an object")

    player = _parse_player(raw.get("playerInfo", {}))
    characters: list[Character] = []
    for av in raw.get("avatarInfoList", []) or []:
        try:
            characters.append(_parse_character(av, resolve_name, resolve_character))
        except Exception as exc:  # noqa: BLE001 - skip a bad character, keep the rest
            logger.warning("Skipping unparseable character: %s", exc)

    if not characters:
        raise EmptyShowcase(f"No characters in showcase for UID {player.uid}")
    return Showcase(player=player, characters=characters)


def _parse_player(info: dict[str, Any]) -> Player:
    return Player(
        uid=str(info.get("uid", "")),
        nickname=str(info.get("nickname", "") or ""),
        level=int(info.get("level", 0) or 0),
        world_level=int(info.get("worldLevel", 0) or 0),
        signature=str(info.get("signature", "") or ""),
        achievements=_opt_int(info.get("finishAchievementNum")),
        namecard=_opt_str(info.get("nameCardId")),
    )


def _parse_character(
    av: dict[str, Any],
    resolve_name: NameResolver | None,
    resolve_character: CharacterResolver | None,
) -> Character:
    aid = str(av.get("avatarId", ""))
    meta = resolve_character(aid) if resolve_character else None
    meta = meta or {}

    name = meta.get("name") or av.get("_name") or aid
    element = Element.parse(meta.get("element") or av.get("_element"))
    rarity = _opt_int(meta.get("rarity") or av.get("_rarity"))
    portrait = meta.get("portrait") or av.get("_portrait")

    prop_map = av.get("propMap", {}) or {}
    level = _opt_int(_nested(prop_map, "4001", "val")) or 1
    constellation = len(av.get("talentIdList", []) or [])

    stats = _parse_stats(av.get("fightPropMap", {}) or {})
    weapon, artifacts = _parse_equipment(av.get("equipList", []) or [], resolve_name)

    return Character(
        id=aid,
        name=str(name),
        element=element,
        rarity=rarity,
        level=level,
        friendship=_opt_int(_nested(av.get("fetterInfo", {}), "expLevel")),
        constellation=constellation,
        portrait=portrait,
        weapon=weapon,
        artifacts=artifacts,
        stats=stats,
    )


def _parse_stats(fight_prop_map: dict[str, Any]) -> list[Stat]:
    stats: list[Stat] = []
    for key, (label, percent) in _FIGHT_PROP.items():
        if key not in fight_prop_map:
            continue
        value = _num(fight_prop_map[key])
        if key in _FRACTION_KEYS:
            value *= 100.0
        stats.append(Stat(name=label, value=value, percent=percent))
    return stats


def _parse_equipment(
    equip_list: list[dict[str, Any]], resolve_name: NameResolver | None
) -> tuple[Weapon | None, list[Artifact]]:
    weapon: Weapon | None = None
    artifacts: list[Artifact] = []

    for equip in equip_list:
        flat = equip.get("flat", {}) or {}
        item_type = flat.get("itemType")
        if item_type == "ITEM_WEAPON":
            weapon = _parse_weapon(equip, flat, resolve_name)
        elif item_type == "ITEM_RELIQUARY":
            artifacts.append(_parse_artifact(equip, flat, resolve_name))
    return weapon, artifacts


def _parse_weapon(equip: dict, flat: dict, resolve_name: NameResolver | None) -> Weapon:
    w = equip.get("weapon", {}) or {}
    affix = w.get("affixMap", {}) or {}
    refinement = (next(iter(affix.values()), 0) + 1) if affix else 1
    main, sub = None, None
    for ws in flat.get("weaponStats", []) or []:
        stat = _stat_from_prop(ws.get("appendPropId"), ws.get("statValue"))
        if ws.get("appendPropId") == "FIGHT_PROP_BASE_ATTACK":
            main = stat
        else:
            sub = stat
    return Weapon(
        name=_resolve(flat.get("nameTextMapHash"), resolve_name),
        level=_opt_int(w.get("level")) or 1,
        refinement=refinement,
        rarity=_opt_int(flat.get("rankLevel")),
        icon=flat.get("icon"),
        main_stat=main,
        sub_stat=sub,
    )


def _parse_artifact(equip: dict, flat: dict, resolve_name: NameResolver | None) -> Artifact:
    r = equip.get("reliquary", {}) or {}
    main = flat.get("reliquaryMainstat", {}) or {}
    subs = flat.get("reliquarySubstats", []) or []
    return Artifact(
        slot=_SLOT_NAMES.get(flat.get("equipType", ""), "?"),
        level=max(0, (_opt_int(r.get("level")) or 1) - 1),
        rarity=_opt_int(flat.get("rankLevel")),
        set_name=_resolve(flat.get("setNameTextMapHash"), resolve_name),
        icon=flat.get("icon"),
        main_stat=_stat_from_prop(main.get("mainPropId"), main.get("statValue")),
        sub_stats=[_stat_from_prop(s.get("appendPropId"), s.get("statValue")) for s in subs],
    )


def _stat_from_prop(prop_id: str | None, value: Any) -> Stat:
    pid = prop_id or ""
    label = _PROP_LABELS.get(pid) or _prettify_prop(pid)
    percent = pid in _PERCENT_PROPS or pid.endswith(_PERCENT_SUFFIXES)
    return Stat(name=label, value=_num(value), percent=percent)


def _prettify_prop(prop_id: str) -> str:
    """Turn an unmapped ``FIGHT_PROP_FOO_BAR`` into ``Foo Bar`` (never a raw enum in the UI)."""
    if not prop_id:
        return "?"
    words = prop_id.replace("FIGHT_PROP_", "").replace("_", " ").title()
    return words or "?"


# --- small helpers ---
def _resolve(value: Any, resolver: NameResolver | None) -> str:
    if resolver is not None and value is not None:
        resolved = resolver(value)
        if resolved:
            return str(resolved)
    return str(value) if value is not None else "?"


def _nested(d: dict, *keys: str) -> Any:
    cur: Any = d
    for k in keys:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(k)
    return cur


def _num(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _opt_int(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _opt_str(value: Any) -> str | None:
    return str(value) if value is not None else None
