"""Regression for TRI 2026-05-04 sub-2% share consolidation."""
from __future__ import annotations

import pytest

from stock_strategy_shared.split_reconciliation import (
    SPLIT_CORROBORATED_QUANTIZED,
    SPLIT_UNRESOLVED,
    SplitAuthority,
    SplitStreamReconciler,
    resolve_split_orientation,
    split_ratio_bounds,
    split_ratio_from_prices,
)


def test_tri_unsnapped_sep_ratio_corroborates_explicit_split():
    stated = 0.98456
    derived = split_ratio_from_prices(
        95.891, 94.41, 95.75, 95.75)
    bounds = split_ratio_bounds(
        95.891, 94.41, 95.75, 95.75)

    assert derived == pytest.approx(0.9845553805883762)
    assert bounds is not None
    assert bounds[0] <= stated <= bounds[1]

    ratio, disposition = resolve_split_orientation(
        stated, derived, bounds=bounds, explicit_no_event=True)
    assert ratio == pytest.approx(stated)
    assert disposition == SPLIT_CORROBORATED_QUANTIZED


def test_tri_stream_path_does_not_turn_small_real_split_into_no_event():
    authority = SplitAuthority({("TRI", "2026-05-04"): 0.98456})
    decision = SplitStreamReconciler(authority).decide(
        ("TRI", "2026-05-04"),
        prev_close=95.891,
        prev_raw=94.41,
        close=95.75,
        raw=95.75,
        fallback_ratio=1.0,
    )

    assert decision.ratio == pytest.approx(0.98456)
    assert decision.disposition == SPLIT_CORROBORATED_QUANTIZED
    assert decision.derived == pytest.approx(0.9845553805883762)


def test_small_explicit_split_outside_rounding_bounds_still_fails_closed():
    derived = split_ratio_from_prices(100.0, 99.5, 100.0, 100.0)
    bounds = split_ratio_bounds(100.0, 99.5, 100.0, 100.0)
    assert derived == pytest.approx(0.995)
    assert bounds is not None
    assert not (bounds[0] <= 0.98456 <= bounds[1])

    ratio, disposition = resolve_split_orientation(
        0.98456, derived, bounds=bounds, explicit_no_event=True)
    assert ratio == 1.0
    assert disposition == SPLIT_UNRESOLVED
