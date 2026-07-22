"""Decision-ledger outcome labeling — pure math (services/pipeline/app/outcomes.py).

Closed-loop evaluation item 1: forward returns at fixed SESSION horizons, SPY
over the same spans, MFE/MAE over the 20-session window, and the completeness /
give-up rules that make retroactive relabeling converge.
"""
from datetime import date, timedelta

import pytest

from app.outcomes import HORIZONS, MAX_BASE_LAG_SESSIONS, label_decision, price_at_or_before


def _sessions(n, start=date(2026, 1, 5)):
    """n weekday sessions starting Monday 2026-01-05."""
    out, d = [], start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def _flat_series(sessions, price):
    return {d: price for d in sessions}


def _linear_series(sessions, start=100.0, step=1.0):
    return {d: start + i * step for i, d in enumerate(sessions)}


# ── price_at_or_before ────────────────────────────────────────────────────────

def test_price_at_or_before_picks_latest_not_after():
    s = _sessions(5)
    series = {s[0]: 10.0, s[2]: 12.0, s[4]: 14.0}
    assert price_at_or_before(series, s[3]) == (s[2], 12.0)
    assert price_at_or_before(series, s[0] - timedelta(days=1)) is None


# ── forward returns on the session grid ───────────────────────────────────────

def test_forward_returns_all_horizons():
    s = _sessions(80)
    px = _linear_series(s)                      # 100, 101, 102, ...
    spy = _flat_series(s, 500.0)                # SPY flat → spy_fwd = 0
    lab = label_decision(s[0], px, spy, s)
    for h in HORIZONS:
        assert lab[f"fwd_{h}d"] == pytest.approx(h / 100.0)
        assert lab[f"spy_fwd_{h}d"] == pytest.approx(0.0)
    assert lab["base_price"] == 100.0
    assert lab["complete"] is True


def test_horizons_not_yet_elapsed_stay_null_and_incomplete():
    s = _sessions(11)                           # decision at s[0]: only 1d/5d reachable
    lab = label_decision(s[0], _linear_series(s), _flat_series(s, 1.0), s)
    assert lab["fwd_1d"] is not None and lab["fwd_5d"] is not None
    assert lab["fwd_20d"] is None and lab["fwd_60d"] is None
    assert lab["complete"] is False


def test_decision_on_non_session_date_anchors_to_prior_session():
    s = _sessions(70)
    saturday = s[0] + timedelta(days=(5 - s[0].weekday()))
    anchor = max(d for d in s if d <= saturday)
    lab = label_decision(saturday, _linear_series(s), _flat_series(s, 1.0), s)
    i = s.index(anchor)
    assert lab["base_price"] == pytest.approx(100.0 + i)
    assert lab["fwd_1d"] == pytest.approx((100.0 + i + 1) / (100.0 + i) - 1)


def test_decision_before_calendar_returns_none():
    s = _sessions(70)
    assert label_decision(s[0] - timedelta(days=30), _linear_series(s),
                          _flat_series(s, 1.0), s) is None


# ── delisted / gappy names hold at last real price, but flagged stale ─────────

def test_delisted_name_holds_at_last_price_and_is_flagged_stale():
    s = _sessions(80)
    px = {d: 100.0 for d in s[:3]}              # trades 3 sessions then vanishes
    px[s[2]] = 50.0                             # last real print −50%
    lab = label_decision(s[0], px, _flat_series(s, 1.0), s)
    assert lab["fwd_20d"] == pytest.approx(-0.5)
    assert lab["fwd_60d"] == pytest.approx(-0.5)
    assert lab["complete"] is True
    # audit-3 fix #2: the hold-at-last-price label is visibly stale — sessions
    # between the print used (s[2]) and each horizon session
    assert lab["stale_20d"] == 18
    assert lab["stale_60d"] == 58
    assert lab["stale_1d"] == 0                 # still printing at s[1] — fresh


def test_fresh_series_has_zero_staleness():
    s = _sessions(80)
    lab = label_decision(s[0], _linear_series(s), _flat_series(s, 1.0), s)
    for h in HORIZONS:
        assert lab[f"stale_{h}d"] == 0


def test_staleness_null_when_horizon_unlabeled():
    s = _sessions(11)                           # only 1d/5d horizons reachable
    lab = label_decision(s[0], _linear_series(s), _flat_series(s, 1.0), s)
    assert lab["stale_1d"] == 0
    assert lab["stale_20d"] is None and lab["stale_60d"] is None


# ── base-price staleness cap and the give-up rule ─────────────────────────────

def test_stale_base_price_rejected_but_row_completes():
    s = _sessions(80)
    # only one ancient price, MAX_BASE_LAG_SESSIONS+1 sessions before decision
    decision_i = MAX_BASE_LAG_SESSIONS + 1
    px = {s[0]: 100.0}
    lab = label_decision(s[decision_i], px, _flat_series(s, 1.0), s)
    assert lab["base_price"] is None
    assert all(lab[f"fwd_{h}d"] is None for h in HORIZONS)
    assert lab["complete"] is True              # give-up: never retries forever
    # SPY legs still labeled (they don't depend on the ticker's base)
    assert lab["spy_fwd_20d"] == pytest.approx(0.0)


def test_base_price_within_lag_window_accepted():
    s = _sessions(80)
    px = {s[0]: 100.0}
    px.update({d: 110.0 for d in s[10:]})
    lab = label_decision(s[MAX_BASE_LAG_SESSIONS], px, _flat_series(s, 1.0), s)
    assert lab["base_price"] == 100.0


# ── MFE / MAE over the 20-session window ──────────────────────────────────────

def test_mfe_mae_capture_excursions():
    s = _sessions(80)
    px = _flat_series(s, 100.0)
    px[s[5]] = 120.0                            # +20% spike inside the window
    px[s[6]] = 100.0
    px[s[10]] = 80.0                            # −20% dip inside the window
    px[s[11]] = 100.0
    lab = label_decision(s[0], px, _flat_series(s, 1.0), s)
    assert lab["mfe_20d"] == pytest.approx(0.20)
    assert lab["mae_20d"] == pytest.approx(-0.20)


def test_mfe_mae_null_until_window_elapsed():
    s = _sessions(15)
    lab = label_decision(s[0], _flat_series(s, 100.0), _flat_series(s, 1.0), s)
    assert lab["mfe_20d"] is None and lab["mae_20d"] is None


def test_excursion_outside_window_ignored():
    s = _sessions(80)
    px = _flat_series(s, 100.0)
    px[s[25]] = 200.0                           # spike AFTER the 20-session window
    lab = label_decision(s[0], px, _flat_series(s, 1.0), s)
    assert lab["mfe_20d"] == pytest.approx(0.0)


# ── excess-vs-SPY sanity ──────────────────────────────────────────────────────

def test_spy_moves_measured_over_same_span():
    s = _sessions(80)
    px = _flat_series(s, 100.0)                 # ticker flat
    spy = _linear_series(s, 400.0, 4.0)         # SPY +1%/session
    lab = label_decision(s[0], px, spy, s)
    assert lab["fwd_20d"] == pytest.approx(0.0)
    assert lab["spy_fwd_20d"] == pytest.approx(20 * 4.0 / 400.0)
