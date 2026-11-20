"""Realistic raw Enka.Network showcase payloads, shared by the integration tests.

These are shaped exactly like the JSON Enka returns, using **real** item ids, icon paths
and text-map hashes — so running them through the real ``EnkaClient`` produces the real
icon URLs the artwork service would fetch in production. Nothing here is a guessed CDN path.

Only the HTTP call is faked in tests; everything downstream (post-processing, mapping,
normalization, rendering) is the production code.
"""

from __future__ import annotations

import copy

# A real 5-star sword: Mistsplitter Reforged.
_WEAPON = {
    "itemId": 11509,
    "weapon": {"level": 90, "promoteLevel": 6, "affixMap": {"111509": 4}},
    "flat": {
        "nameTextMapHash": "4124851547", "rankLevel": 5, "itemType": "ITEM_WEAPON",
        "icon": "UI_EquipIcon_Sword_Narukami",
        "weaponStats": [
            {"appendPropId": "FIGHT_PROP_BASE_ATTACK", "statValue": 674.0},
            {"appendPropId": "FIGHT_PROP_CRITICAL_HURT", "statValue": 22.1},
        ],
    },
}

# Five real artifact pieces from one set (Resolution of Sojourner), one per slot.
_ARTIFACT_SPECS = [
    (51520, "EQUIP_BRACER", "UI_RelicIcon_10001_2", "FIGHT_PROP_HP", 4780.0),
    (51521, "EQUIP_NECKLACE", "UI_RelicIcon_10001_4", "FIGHT_PROP_ATTACK", 311.0),
    (51522, "EQUIP_SHOES", "UI_RelicIcon_10001_5", "FIGHT_PROP_ATTACK_PERCENT", 46.6),
    (51523, "EQUIP_RING", "UI_RelicIcon_10001_1", "FIGHT_PROP_FIRE_ADD_HURT", 46.6),
    (51524, "EQUIP_DRESS", "UI_RelicIcon_10001_3", "FIGHT_PROP_CRITICAL_HURT", 62.2),
]

_SUBSTATS = [
    {"appendPropId": "FIGHT_PROP_CRITICAL", "statValue": 9.7},
    {"appendPropId": "FIGHT_PROP_CRITICAL_HURT", "statValue": 7.8},
    {"appendPropId": "FIGHT_PROP_ATTACK_PERCENT", "statValue": 4.1},
    {"appendPropId": "FIGHT_PROP_ELEMENT_MASTERY", "statValue": 72.0},
]


def _artifacts() -> list[dict]:
    out = []
    for item_id, equip, icon, main_prop, main_value in _ARTIFACT_SPECS:
        out.append({
            "itemId": item_id,
            "reliquary": {"level": 21, "mainPropId": 14001, "appendPropIdList": [501221]},
            "flat": {
                "nameTextMapHash": "1613827080", "rankLevel": 5,
                "itemType": "ITEM_RELIQUARY", "icon": icon, "equipType": equip,
                "setNameTextMapHash": "35587211",
                "reliquaryMainstat": {"mainPropId": main_prop, "statValue": main_value},
                "reliquarySubstats": copy.deepcopy(_SUBSTATS),
            },
        })
    return out


def showcase_payload(avatar_id: int, skill_ids: tuple[int, int, int]) -> dict:
    """A complete single-character showcase response for ``avatar_id``."""
    return {
        "uid": "901211014", "ttl": 60,
        "playerInfo": {
            "nickname": "Rexxyyy", "level": 60, "worldLevel": 8, "signature": "",
            "finishAchievementNum": 500, "nameCardId": 210001,
            "profilePicture": {"id": 1}, "showAvatarInfoList": [],
        },
        "avatarInfoList": [{
            "avatarId": avatar_id,
            "propMap": {"4001": {"val": "90"}, "1002": {"val": "6"}},
            "talentIdList": [avatar_id * 10 + 1],   # one unlocked constellation -> C1
            "skillDepotId": 701,
            "skillLevelMap": {str(s): 10 for s in skill_ids},
            "fetterInfo": {"expLevel": 10},
            "fightPropMap": {
                "2000": 20023.0, "2001": 1891.0, "2002": 866.0,
                "20": 0.815, "22": 2.066, "23": 1.0, "28": 203.0, "30": 0.466,
            },
            "equipList": [copy.deepcopy(_WEAPON), *_artifacts()],
        }],
    }


# Arlecchino (established) and Odette (released after this code was written). Odette is here
# purely as an id + skill list — nothing about her is hardcoded anywhere in bot/.
ARLECCHINO = (10000096, (10961, 10962, 10965))
ODETTE = (10000150, (11501, 11502, 11505))
