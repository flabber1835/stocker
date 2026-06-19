"""Round-trip (baseline) suppression for the falling-knife drawdown signal.

The naive peak-to-now drawdown (last/max − 1) overstates damage when a stock
SPIKED inside the window and then gave the run-up back — that's volatility, not a
falling knife. `recent_drawdown`/`excess_drawdown` now also measure the drop vs a
pre-spike baseline (mean of the first `baseline_window` closes) and keep whichever
shows LESS damage, so a round-trip nets out while a genuine one-way decline is
unchanged.

These cases use REAL price movement from the two stocks that exposed the bug
(ENPH 47→72→48, an AVGO-style 410→480→411 earnings round-trip) plus synthetic
shapes (steady collapse, spike-then-crash-below-baseline) and a seeded
random-walk path that ends flat vs ends down.
"""
from __future__ import annotations

import math
import random

import pytest

from stock_strategy_shared.drawdown import recent_drawdown, excess_drawdown


# ── real movement: the two stocks from the screenshots ──────────────────────────

# ENPH 2026-05-19 → 06-17 adjusted closes (21 sessions): ran 47 → 72 → back to 48.
ENPH = [46.76, 53.15, 62.34, 64.03, 66.90, 70.28, 69.50, 68.36, 63.74, 72.33,
        69.02, 68.30, 56.07, 56.88, 53.51, 50.57, 54.93, 54.59, 52.40, 50.26, 47.78]

# AVGO-style earnings round-trip: ran ~410 → ~480 → back to ~411 (net flat).
AVGO = [410, 415, 422, 430, 445, 460, 472, 480, 475, 465, 450, 440,
        430, 425, 420, 418, 415, 413, 412, 411, 411]


def test_enph_roundtrip_not_a_knife():
    raw = recent_drawdown(ENPH, baseline_window=0)
    eff = recent_drawdown(ENPH, baseline_window=3)
    # Naive peak-to-now is a scary -34% that would trip the 25% floor...
    assert raw == pytest.approx(47.78 / 72.33 - 1.0, abs=1e-6)
    assert raw <= -0.33
    # ...but it round-tripped to ~where it started → effective ≈ -12%, no floor trip.
    assert eff == pytest.approx(47.78 / ((46.76 + 53.15 + 62.34) / 3) - 1.0, abs=1e-6)
    assert -0.13 < eff < -0.10
    assert eff > raw  # less damage than the raw peak-to-now


def test_avgo_roundtrip_is_flat():
    raw = recent_drawdown(AVGO, baseline_window=0)
    eff = recent_drawdown(AVGO, baseline_window=3)
    assert raw == pytest.approx(411 / 480 - 1.0, abs=1e-6)   # ~-14%
    assert eff > -0.03                                        # essentially flat → no knife


# ── synthetic shapes ────────────────────────────────────────────────────────────

def test_one_way_collapse_still_fires():
    """A steady decline with no prior spike: baseline ≈ peak, so the round-trip
    logic leaves it essentially unchanged — it must still trip the floor."""
    collapse = [round(100 - i * 1.5, 2) for i in range(21)]   # 100 → 70
    raw = recent_drawdown(collapse, baseline_window=0)
    eff = recent_drawdown(collapse, baseline_window=3)
    assert raw == pytest.approx(-0.30, abs=1e-6)
    assert eff <= -0.25                       # still a knife (trips 25% floor)
    assert eff == pytest.approx(raw, abs=0.02)  # baseline barely changes a one-way drop


def test_spike_then_crash_below_baseline_reports_net_damage():
    """Spiked above baseline then crashed BELOW it: the give-back of the spike is
    stripped, but the real loss vs baseline remains and still fires."""
    path = [50, 53, 58, 64, 70, 66, 60, 53, 47, 43, 40, 38,
            37, 36, 35, 34.5, 34, 33.5, 33.2, 33, 33]
    raw = recent_drawdown(path, baseline_window=0)
    eff = recent_drawdown(path, baseline_window=3)
    baseline = (50 + 53 + 58) / 3
    assert raw == pytest.approx(33 / 70 - 1.0, abs=1e-6)        # ~-53% from the spike
    assert eff == pytest.approx(33 / baseline - 1.0, abs=1e-6)  # ~-38% net of give-back
    assert eff <= -0.25 and eff > raw


def test_baseline_window_zero_reverts_to_peak_to_now():
    for series in (ENPH, AVGO):
        assert recent_drawdown(series, baseline_window=0) == pytest.approx(
            series[-1] / max(series) - 1.0, abs=1e-9
        )


def test_at_fresh_high_is_zero_either_way():
    rising = [100 + i for i in range(21)]
    assert recent_drawdown(rising, baseline_window=0) == 0.0
    assert recent_drawdown(rising, baseline_window=3) == 0.0


# ── seeded random-walk paths that "look like a real stock" ──────────────────────

def _gbm(seed: int, n: int, mu: float, sigma: float, start: float = 100.0) -> list[float]:
    """Geometric random walk — a realistic daily price path."""
    rng = random.Random(seed)
    px = [start]
    for _ in range(n - 1):
        px.append(px[-1] * math.exp(mu + sigma * rng.gauss(0, 1)))
    return px


def test_random_walk_roundtrip_vs_decline():
    # A volatile path engineered to spike then return near its start (round trip):
    up = _gbm(1, 11, mu=0.03, sigma=0.04)          # run up ~11 days
    down = _gbm(2, 10, mu=-0.035, sigma=0.04, start=up[-1])  # give it back
    roundtrip = up + down
    # Ends within a few % of where it started over the window → not a knife.
    assert roundtrip[-1] == pytest.approx(roundtrip[0], rel=0.12)
    eff_rt = recent_drawdown(roundtrip, window=21, baseline_window=3)
    raw_rt = recent_drawdown(roundtrip, window=21, baseline_window=0)
    assert raw_rt < -0.10                # peak-to-now looks like a real drop
    assert eff_rt > raw_rt + 0.05        # baseline strips most of it

    # A genuine sustained decline (no recovery) must remain flagged.
    decline = _gbm(3, 21, mu=-0.02, sigma=0.02)
    eff_dec = recent_drawdown(decline, window=21, baseline_window=3)
    assert eff_dec <= -0.15


# ── excess_drawdown: the actual veto input (beta-adjusted) ───────────────────────

def _flatish_spy(n: int) -> list[float]:
    """Low-drift SPY with small variance (so beta is defined, net move ≈ 0)."""
    return [580.0 + (0.5 if i % 2 else 0.0) for i in range(n)]


def test_excess_roundtrip_suppressed_genuine_collapse_not():
    spy = _flatish_spy(130)

    # Round-trip stock (flat history then the AVGO round-trip in the last 21).
    roundtrip = [410.0] * 109 + AVGO
    assert len(roundtrip) == 130
    d_off = excess_drawdown(roundtrip, spy, window=21, baseline_window=0)
    d_on = excess_drawdown(roundtrip, spy, window=21, baseline_window=3)
    assert d_off["excess_dd"] <= -0.10      # naive: would trip a -15% veto
    assert d_on["excess_dd"] > -0.05        # round-trip aware: no veto

    # Genuine idiosyncratic collapse (SPY flat) must still fire on excess.
    collapse = [100.0] * 109 + [round(100 - i * 1.5, 2) for i in range(21)]
    d_col = excess_drawdown(collapse, spy, window=21, baseline_window=3)
    assert d_col["excess_dd"] <= -0.20      # not suppressed


def test_excess_strips_market_unchanged_by_baseline():
    # A name that fell only because the market fell (beta≈1) → excess ≈ 0, and the
    # baseline logic must not change that (no spike to strip).
    n = 130
    spy = [100.0 * (0.999 ** i) for i in range(n)]
    stock = [50.0 * (0.999 ** i) for i in range(n)]
    res = excess_drawdown(stock, spy, window=21, baseline_window=3)
    assert res is not None and res["excess_dd"] is not None
    assert abs(res["excess_dd"]) < 0.03
