"""Unit tests for _intent_in_target — the delta-native "is this a builder-target
member" signal behind the dashboard's Target ✓ tick.

It must be derived from the intent's OWN fields (action + current_weight), NOT a
re-query of the latest portfolio_holdings (which can be a different build than the
one the delta consumed → desync). Guards the "38 vs 30 ticks" regression: a
data-gap HOLD (action='hold', weight 0) must NOT count as a target member.
"""
from app.main import _intent_in_target


def test_entry_is_in_target():
    assert _intent_in_target("entry", 0.04) is True


def test_buy_add_and_sell_trim_in_target():
    assert _intent_in_target("buy_add", 0.04) is True
    assert _intent_in_target("sell_trim", 0.04) is True


def test_watch_is_in_target_even_with_null_weight():
    # watch = capacity-deferred entry; current_weight is None but it IS a target name.
    assert _intent_in_target("watch", None) is True


def test_in_target_hold_has_positive_weight():
    assert _intent_in_target("hold", 0.03) is True


def test_data_gap_hold_is_not_target():
    # action='hold' but weight 0 → held, never selected → NOT a target member.
    assert _intent_in_target("hold", 0.0) is False
    assert _intent_in_target("hold", None) is False


def test_orphan_states_are_not_target():
    assert _intent_in_target("exit", 0.0) is False
    assert _intent_in_target("at_risk", 0.0) is False


def test_bad_weight_is_not_target():
    assert _intent_in_target("hold", "not-a-number") is False
