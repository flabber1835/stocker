"""Tests for the pure spinoff-adjustment helpers.

Regression for the FedEx Freight spinoff false-drawdown: AV's adjusted_close left the
2026-06-01 ex-date cliff in FDX's series, so the vetter's 21-day falling-knife saw a
~-18% "crash" that was value handed to shareholders. The fix stitches the pre-ex
history down by the ex-date gap factor so the series is continuous and the false
drawdown vanishes.
"""
from datetime import date

from stock_strategy_shared.corporate_actions import (
    spinoff_factor,
    apply_corporate_actions,
    SPINOFF_FACTOR_MIN,
    SPINOFF_FACTOR_MAX,
)

EX = date(2026, 6, 1)


def _series(pre, post):
    """Build {date: close}: 5 pre-ex days all `pre`, 5 from ex_date all `post`."""
    out = {}
    for i in range(5):
        out[date(2026, 5, 25 + i)] = pre   # 05-25..05-29 (pre-ex)
    for i in range(5):
        out[date(2026, 6, 1 + i)] = post   # 06-01..06-05 (on/after ex)
    return out


# ── spinoff_factor ──────────────────────────────────────────────────────────────

def test_factor_is_postgap_over_pregap():
    # FDX-like: ~$412 → ~$338 → factor ≈ 0.82
    f = spinoff_factor(_series(412.0, 338.0), EX)
    assert f is not None and abs(f - 338.0 / 412.0) < 1e-9


def test_factor_none_when_price_rose_across_ex():
    # price ROSE across ex (>5%) → not a spinoff signature → no adjustment
    assert spinoff_factor(_series(100.0, 130.0), EX) is None


def test_factor_none_when_drop_implausibly_large():
    # >80% drop → likely a real crash / data error, not a clean spinoff → skip
    assert spinoff_factor(_series(100.0, 10.0), EX) is None


def test_factor_none_when_no_pre_or_post():
    assert spinoff_factor({date(2026, 5, 28): 100.0}, EX) is None          # no post
    assert spinoff_factor({date(2026, 6, 2): 100.0}, EX) is None           # no pre


def test_factor_within_band_inclusive():
    # a small spinoff (factor ~0.97) is applied
    f = spinoff_factor(_series(100.0, 97.0), EX)
    assert f is not None and SPINOFF_FACTOR_MIN <= f <= SPINOFF_FACTOR_MAX


# ── apply_corporate_actions ───────────────────────────────────────────────────────

def test_pre_ex_scaled_post_ex_unchanged():
    raw = _series(412.0, 338.0)
    adj = apply_corporate_actions(raw, [EX])
    f = 338.0 / 412.0
    for d, v in raw.items():
        if d < EX:
            assert abs(adj[d] - v * f) < 1e-6      # pre-ex scaled down
        else:
            assert abs(adj[d] - v) < 1e-9          # post-ex untouched


def test_false_drawdown_removed():
    # Before adjustment: 21d peak-to-now = 338/412 - 1 ≈ -18% (false knife).
    # After: peak and now are on the same basis → ~0 drawdown.
    raw = _series(412.0, 338.0)
    adj = apply_corporate_actions(raw, [EX])
    peak = max(adj.values())
    now = adj[max(adj)]
    assert (now / peak - 1.0) > -0.02              # no spurious cliff


def test_idempotent_recompute_from_raw():
    # Applying twice from the same raw lands on the same values (raw is immutable).
    raw = _series(412.0, 338.0)
    once = apply_corporate_actions(raw, [EX])
    twice = apply_corporate_actions(raw, [EX])
    assert once == twice


def test_no_actions_is_identity():
    raw = _series(412.0, 338.0)
    assert apply_corporate_actions(raw, []) == raw


def test_none_raw_passed_through():
    raw = {date(2026, 5, 28): None, date(2026, 6, 2): 100.0}
    adj = apply_corporate_actions(raw, [EX])
    assert adj[date(2026, 5, 28)] is None


def test_multiple_spinoffs_compound_on_earliest_history():
    ex2 = date(2026, 3, 2)
    raw = {
        date(2026, 2, 27): 200.0,   # before both
        date(2026, 3, 2): 180.0,    # on ex2 (factor2 = 180/200 = 0.9)
        date(2026, 5, 29): 412.0,   # before ex1, after ex2
        date(2026, 6, 1): 338.0,    # on ex1 (factor1 = 338/412)
    }
    adj = apply_corporate_actions(raw, [EX, ex2])
    f1 = 338.0 / 412.0
    f2 = 180.0 / 200.0
    # earliest date is before BOTH → scaled by f1*f2
    assert abs(adj[date(2026, 2, 27)] - 200.0 * f1 * f2) < 1e-6
    # between ex2 and ex1 → scaled by f1 only
    assert abs(adj[date(2026, 5, 29)] - 412.0 * f1) < 1e-6
    # on/after ex1 → unchanged
    assert abs(adj[date(2026, 6, 1)] - 338.0) < 1e-9
