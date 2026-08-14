"""Real-shape ACTIONS source identity and multiplicity falsifiers."""
from __future__ import annotations

from decimal import Decimal

from sentinel.feed import action_source, actions_map


def row(**changes):
    value = {
        "date": "2026-08-14", "action": "relation", "ticker": "XRN",
        "name": "XORTX Therapeutics Inc", "value": None,
        "contraticker": None, "contraname": None,
    }
    value.update(changes)
    return value


def test_identity_is_null_stable_numeric_semantic_and_content_complete():
    base = row(value=1)
    assert action_source.source_row_id(base) == action_source.source_row_id(
        row(value=Decimal("1.00")))
    assert action_source.source_row_id(
        row(contraticker=None)) != action_source.source_row_id(row(contraticker=""))
    for field, changed in (("name", "another issuer"),
                           ("contraticker", "ABC"),
                           ("contraname", "Another Counterparty"),
                           ("value", 2)):
        assert action_source.source_row_id(base) != action_source.source_row_id(
            row(**{field: changed}))


def test_xrn_shape_retains_siblings_and_deduplicates_exact_repeat():
    first = row(contraticker="XRTXF", contraname="XORTX THERAPEUTICS INC")
    second = row(contraticker="XORT", contraname="XORTX Therapeutics Inc")
    distinct = action_source.distinct_rows([first, first.copy(), second])
    assert len(distinct) == 2
    profile = action_source.multiplicity_profile([first, first.copy(), second])
    assert profile == {
        "source_rows": 3, "distinct_rows": 2, "exact_repeat_rows": 1,
        "by_action": {"relation": {
            "source_rows": 3, "distinct_rows": 2, "economic_keys": 1,
            "multiplicity_keys": 1, "exact_repeat_rows": 1,
        }},
    }


def test_ambiguous_splits_are_not_first_last_or_product():
    ratios, ambiguous = actions_map.split_rows_from_actions([
        row(ticker="AAA", action="split", value=2),
        row(ticker="AAA", action="split", value=3, contraticker="NEW"),
    ], ["2026-08-14"])
    assert ratios == {}
    assert ambiguous == [{
        "ticker": "AAA", "session": "2026-08-14", "distinct_rows": 2,
        "distinct_values": [2.0, 3.0], "invalid_value_rows": 0,
    }]


def test_exact_duplicate_split_is_one_source_row():
    split = row(ticker="AAA", action="split", value=2)
    ratios, ambiguous = actions_map.split_rows_from_actions(
        [split, split.copy()], ["2026-08-14"])
    assert ratios == {("AAA", "2026-08-14"): 2.0}
    assert ambiguous == []
