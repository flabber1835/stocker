"""Production-shaped falsifiers from the 2026-08 NAS certification corpus."""
from __future__ import annotations

import pytest

from sentinel.feed import actions_map
from stock_strategy_shared.split_reconciliation import (
    SPLIT_AUTHORITATIVE_APPLIED,
    SPLIT_CORROBORATED_BRIDGED,
    SPLIT_CORROBORATED_QUANTIZED,
    SPLIT_CORROBORATED_SHIFTED,
    SPLIT_PENDING_BRIDGE,
    SPLIT_RESOLVED_NO_EVENT,
    SplitAuthority,
    SplitStreamReconciler,
    resolve_split_orientation,
    split_ratio_bounds,
    split_ratio_from_prices,
)


@pytest.mark.parametrize(
    "stated,prev_adj,prev_raw,event_adj,event_raw",
    [
        (0.0125, 315.2, 0.039, 328.0, 3.28),
        (0.01, 275.0, 0.028, 341.0, 3.41),
        (0.00455, 6.666, 0.01, 5.4, 1.8),
        (0.01, 206.0, 0.01, 187.2, 0.936),
        (0.004, 2.075, 0.008, 2.33, 2.33),
        (0.005, 7.7, 0.038, 5.71, 5.71),
        (0.005, 4.7, 0.024, 3.37, 3.37),
        (0.01, 1.56, 0.016, 1.83, 1.83),
        (0.00667, 2.01, 0.013, 2.18, 2.18),
        (0.005, 3.74, 0.019, 4.19, 4.19),
        (0.005, 4.48, 0.022, 3.34, 3.34),
    ],
)
def test_mill_rounded_sep_prices_corroborate_the_stated_split(
        stated, prev_adj, prev_raw, event_adj, event_raw):
    derived = split_ratio_from_prices(
        prev_adj, prev_raw, event_adj, event_raw)
    bounds = split_ratio_bounds(prev_adj, prev_raw, event_adj, event_raw)
    ratio, disposition = resolve_split_orientation(
        stated, derived, bounds=bounds)
    expected = (1 / round(1 / stated)) if stated < 1 else stated
    assert ratio == pytest.approx(expected)
    assert disposition == SPLIT_CORROBORATED_QUANTIZED


def test_split_and_adr_ratio_rows_are_different_authorities():
    rows = [
        {"ticker": "BQ", "date": "2025-07-11", "action": "adrratiosplit",
         "value": 0.00666666666666667, "source_row_id": "a" * 64},
        {"ticker": "BQ", "date": "2025-07-11", "action": "split",
         "value": 0.9375, "source_row_id": "b" * 64},
        {"ticker": "BVC", "date": "2026-01-05", "action": "adrratiosplit",
         "value": 0.5, "source_row_id": "c" * 64},
        {"ticker": "BVC", "date": "2026-01-05", "action": "split",
         "value": 0.1, "source_row_id": "d" * 64},
        {"ticker": "CANF", "date": "2026-01-05",
         "action": "adrratiosplit", "value": 0.0066,
         "source_row_id": "e" * 64},
        {"ticker": "CANF", "date": "2026-01-05", "action": "split",
         "value": 0.05, "source_row_id": "f" * 64},
    ]
    ratios, ambiguous = actions_map.split_rows_from_actions(
        rows, ["2025-07-11", "2026-01-05"])
    assert ratios == {
        ("BQ", "2025-07-11"): 0.9375,
        ("BVC", "2026-01-05"): 0.1,
        ("CANF", "2026-01-05"): 0.05,
    }
    assert ambiguous == []


def test_gp_action_one_session_late_is_applied_exactly_once():
    future = ("GP", "2025-09-09")
    authority = SplitAuthority(
        {future: 0.1},
        previous_session_candidates={
            ("GP", "2025-09-08"): (future, 0.1),
        })
    reconciler = SplitStreamReconciler(authority)

    event = reconciler.decide(
        ("GP", "2025-09-08"), prev_close=2.35, prev_raw=0.235,
        close=3.108, raw=3.108, fallback_ratio=0.1)
    next_day = reconciler.decide(
        future, prev_close=3.108, prev_raw=3.108,
        close=3.0, raw=3.0, fallback_ratio=1.0)

    assert (event.ratio, event.disposition) == (
        0.1, SPLIT_CORROBORATED_SHIFTED)
    assert (next_day.ratio, next_day.disposition) == (
        1.0, SPLIT_RESOLVED_NO_EVENT)


def test_bjdx_intermediate_adjustment_artifact_is_not_applied():
    action_key = ("BJDX", "2026-01-29")
    prior_key = ("BJDX", "2026-01-28")
    authority = SplitAuthority(
        {action_key: 0.25},
        previous_session_candidates={prior_key: (action_key, 0.25)})
    reconciler = SplitStreamReconciler(authority)

    intermediate = reconciler.decide(
        prior_key, prev_close=3.039, prev_raw=0.76,
        close=12.984, raw=0.815, fallback_ratio=4.0)
    effective = reconciler.decide(
        action_key, prev_close=12.984, prev_raw=0.815,
        close=3.43, raw=3.43, fallback_ratio=0.0625)

    assert (intermediate.ratio, intermediate.disposition) == (
        1.0, SPLIT_PENDING_BRIDGE)
    assert (effective.ratio, effective.disposition) == (
        0.25, SPLIT_CORROBORATED_BRIDGED)
    assert effective.prior_key == prior_key
    assert effective.prior_disposition == SPLIT_RESOLVED_NO_EVENT


def test_agmb_issuer_action_is_refuted_as_a_listed_share_event():
    authority = SplitAuthority({("AGMB", "2026-02-09"): 21.645})
    decision = SplitStreamReconciler(authority).decide(
        ("AGMB", "2026-02-09"), prev_close=14.65, prev_raw=14.65,
        close=15.61, raw=15.61, fallback_ratio=1.0)
    assert (decision.ratio, decision.disposition) == (
        1.0, SPLIT_RESOLVED_NO_EVENT)


def test_first_retained_session_uses_direct_stock_split_authority():
    authority = SplitAuthority({("APG", "2025-07-01"): 1.5})
    decision = SplitStreamReconciler(authority).decide(
        ("APG", "2025-07-01"), prev_close=None, prev_raw=None,
        close=33.09, raw=33.09, fallback_ratio=1.0)
    assert (decision.ratio, decision.disposition) == (
        1.5, SPLIT_AUTHORITATIVE_APPLIED)
