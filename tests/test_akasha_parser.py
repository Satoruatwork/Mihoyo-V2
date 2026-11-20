"""Tests for the label-based Akasha ranking parser (no network)."""

from __future__ import annotations

from bot.api.akasha_client import AkashaClient

# A trimmed real akasha.cv payload shape (data list of per-character entries).
_ENTRIES = [
    {
        "characterId": 10000002,
        "name": "Kamisato Ayaka",
        "calculations": {
            "fit": {"calculationId": "1000000216", "name": "Premium Team vs Boss, Avg DMG",
                    "ranking": 696199, "outOf": 836307, "result": 673534.8},
            "alt": {"calculationId": "1000000999", "name": "Alt formula",
                    "ranking": 500000, "outOf": 836307, "result": 500000.0},
        },
    },
    {
        "characterId": 10000046,
        "calculations": {"a": {"name": "Vape DMG", "ranking": 2147, "outOf": 268375}},
    },
]


def test_parses_by_label_and_picks_best_rank():
    ranks = AkashaClient()._parse(_ENTRIES, "901211014")
    assert set(ranks) == {"10000002", "10000046"}
    ayaka = ranks["10000002"]
    # Best (lowest) rank across calculations is chosen.
    assert ayaka.rank == 500000
    assert ayaka.total_players == 836307
    assert ayaka.calculation_name == "Alt formula"
    assert abs(ayaka.top_percent - (500000 / 836307 * 100)) < 0.01
    assert ayaka.available


def test_top_percent_from_rank_over_total():
    hutao = AkashaClient()._parse(_ENTRIES, "1")["10000046"]
    assert hutao.rank == 2147
    assert round(hutao.top_percent, 2) == round(2147 / 268375 * 100, 2)


def test_missing_calculations_skipped_not_crashing():
    ranks = AkashaClient()._parse([{"characterId": 111, "calculations": {}}], "1")
    assert ranks == {}


def test_entry_without_character_id_ignored():
    ranks = AkashaClient()._parse([{"calculations": {"a": {"ranking": 1, "outOf": 2}}}], "1")
    assert ranks == {}
