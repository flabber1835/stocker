"""
Chaos/property fuzz of regime detection:
  resolve_confirmed_regime — the hysteresis/confirmation state machine that
    drives factor weights for the whole universe (off-by-one / state bug spot).
  detect_regime — raw regime from SPY price/vol; must always return a covered
    regime with finite signals on valid (positive) SPY history.
"""
import math
import os
import random

import numpy as np
import pandas as pd
import pytest

from app.regime import resolve_confirmed_regime, detect_regime
from stock_strategy_shared.loader import load_strategy

_STRAT_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "strategies", "quality_core_v1.yaml")
STRAT, _ = load_strategy(_STRAT_PATH)
RCFG = STRAT.regime_detection
REGIME_NAMES = list(RCFG.regimes.keys())


def test_confirmation_state_machine_fuzz():
    """A confirmed switch to a new regime must require `confirmation_days`
    consecutive identical raw signals; otherwise the prior confirmed regime holds."""
    rng = random.Random(5)
    options = ["bull_calm", "bull_stress", "bear_stress", "bear_calm"]
    for conf in (1, 2, 3, 5, 8):
        prior_raws: list[str] = []
        prior_confirmed = None
        for _ in range(600):
            raw = rng.choice(options)
            confirmed = resolve_confirmed_regime(raw, prior_raws, prior_confirmed, conf)
            assert confirmed in options

            # build the last `conf` raw signals, most-recent-first (today + history)
            last_conf = ([raw] + prior_raws)[:conf]
            switched = confirmed != prior_confirmed and prior_confirmed is not None
            if switched:
                # a switch only ever lands on the current raw, fully confirmed
                assert confirmed == raw, "switched to a non-current raw regime"
                assert len(last_conf) == conf and all(r == raw for r in last_conf), (
                    f"switch not confirmed for {conf}d: {last_conf}"
                )
            if prior_confirmed is not None and not (len(last_conf) == conf and all(r == raw for r in last_conf)):
                # not fully confirmed → must hold the prior confirmed regime
                assert confirmed == prior_confirmed, "regime changed without confirmation"

            prior_raws = ([raw] + prior_raws)[: max(conf, 1)]
            prior_confirmed = confirmed


def test_confirmation_immediate_when_conf_days_one():
    assert resolve_confirmed_regime("bear_stress", [], "bull_calm", 1) == "bear_stress"


def _spy(n, rng, vol=0.01, drift=0.0003):
    px = [400.0]
    for _ in range(n - 1):
        px.append(max(1.0, px[-1] * (1 + drift + vol * rng.gauss(0, 1))))
    return pd.DataFrame({"date": pd.date_range("2024-01-01", periods=n), "adjusted_close": px})


def test_detect_regime_always_covered_and_finite():
    rng = random.Random(7)
    for _ in range(500):
        n = RCFG.slow_sma + rng.randint(0, 200)
        vol = rng.choice([0.004, 0.01, 0.03, 0.06])
        drift = rng.choice([-0.002, -0.0005, 0.0003, 0.0015])
        out = detect_regime(_spy(n, rng, vol, drift), RCFG)
        assert out["raw_regime"] in REGIME_NAMES
        for k in ("spy_vs_sma", "realized_vol", "spy_price", "spy_sma_slow"):
            assert math.isfinite(out[k]), f"{k} not finite: {out[k]}"
        assert out["realized_vol"] >= 0.0


def test_detect_regime_raises_on_short_history():
    rng = random.Random(9)
    with pytest.raises(ValueError):
        detect_regime(_spy(RCFG.slow_sma - 1, rng), RCFG)


def test_detect_regime_robust_to_corrupt_spy_price():
    """A zero/negative SPY price (data corruption) must not yield inf/nan signals
    that silently misclassify the regime for the entire universe."""
    rng = random.Random(11)
    df = _spy(RCFG.slow_sma + 50, rng)
    df.loc[df.index[-3], "adjusted_close"] = 0.0      # corrupt one bar
    out = detect_regime(df, RCFG)
    assert out["raw_regime"] in REGIME_NAMES
    assert math.isfinite(out["realized_vol"]), f"corrupt SPY → realized_vol={out['realized_vol']}"
    assert math.isfinite(out["spy_vs_sma"]), f"corrupt SPY → spy_vs_sma={out['spy_vs_sma']}"
