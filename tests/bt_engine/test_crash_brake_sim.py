"""The crash brake inside the simulator.

Two things have to be true for the tunnel's answer to mean anything:

  * with the brake OFF the run is bit-identical to before, so any measured
    difference is the brake and not the plumbing; and
  * when it engages it scales the WHOLE book by one factor, leaving relative
    weights alone — otherwise it is a hidden second selection rule and the
    experiment measures "brake + reshuffle" rather than the brake.

The order it is applied in also matters and is asserted: vol-targeting sizes the
book for its own estimated volatility (a continuous control), the brake is a
discrete market-wide cut. Applying the brake LAST means it can only reduce what
vol-targeting arrived at, never be diluted by it.
"""
from datetime import date

import numpy as np
import pandas as pd
import pytest

from app.sim import _FK_DEFAULTS, build_target
from stock_strategy_shared.schemas.strategy import StrategyConfig

_REGIMES = {
    "bull_calm":   {"spy_above_slow_sma": True,  "vol_above_threshold": False},
    "bull_stress": {"spy_above_slow_sma": True,  "vol_above_threshold": True},
    "bear_stress": {"spy_above_slow_sma": False, "vol_above_threshold": True},
    "bear_calm":   {"spy_above_slow_sma": False, "vol_above_threshold": False},
}
_W = {"momentum": 1.0, "quality": 0.0, "value": 0.0, "growth": 0.0,
      "low_volatility": 0.0, "liquidity": 0.0}


def _cfg(**over) -> StrategyConfig:
    base = {
        "strategy_id": "crash_brake_sim_test",
        "min_non_null_factors": 1,
        "required_factors": [],
        "universe": {"source": "av_listing", "min_price": 1.0,
                     "min_avg_dollar_volume_20d": 0.0},
        "regime_detection": {"slow_sma": 20, "vol_window": 5, "vol_threshold": 0.8,
                             "confirmation_days": 1, "regimes": _REGIMES},
        "factor_weights": {r: _W for r in _REGIMES},
        "regime_weighting_enabled": False,
        "static_factor_weights": _W,
        "portfolio_builder": {
            "method": "greedy_score_per_port_vol", "max_positions": 5,
            "max_position_weight": 0.5, "max_sector_weight": 1.0,
            "weighting": "equal_weight", "candidate_count": 20,
            "covariance_window_days": 40, "min_covariance_observations": 20,
            "covariance_shrinkage": 0.2, "cluster_correlation_threshold": 0.99,
            "max_cluster_weight": 1.0, "max_tickers_per_cluster": None,
            "cash_reserve": 0.0, "vol_target_enabled": False,
        },
        "vetter": {"candidate_count": 20},
    }
    base.update(over)
    return StrategyConfig(**base)


@pytest.fixture(scope="module")
def frames():
    days = pd.bdate_range("2024-01-02", periods=260)
    spec = {"AAA": 0.0012, "BBB": 0.0010, "CCC": 0.0008,
            "DDD": 0.0006, "EEE": 0.0004, "FFF": 0.0002}
    rows = []
    for t, drift in spec.items():
        px = 100.0
        for i, d in enumerate(days):
            px *= 1.0 + drift + 0.001 * np.sin(i / 9.0 + sum(map(ord, t)) % 7)
            rows.append({"ticker": t, "date": d, "close": px,
                         "adjusted_close": px, "volume": 1_000_000.0})
    prices = pd.DataFrame(rows)
    fnd = pd.DataFrame([
        {"ticker": t, "pe_ratio": 15.0, "pb_ratio": 2.0, "roe": 0.15,
         "debt_to_equity": 0.5, "revenue_growth": 0.05, "eps_growth": 0.05}
        for t in spec])
    spy = [100.0 * (1 + 0.0004 * i) for i in range(260)]
    return prices, fnd, spy


def _build(frames, crash_exposure=None, cfg=None):
    prices, fnd, spy = frames
    return build_target(prices, fnd, {}, cfg or _cfg(), "bull_calm",
                        dict(_FK_DEFAULTS), spy, crash_exposure=crash_exposure)


class TestOffIsInert:
    def test_none_is_bit_identical_to_the_previous_behaviour(self, frames):
        """`crash_exposure=None` is what every existing caller effectively passes;
        it must not perturb a single weight."""
        a, _r, _s = _build(frames)
        b, _r2, _s2 = _build(frames, crash_exposure=None)
        assert a == b

    def test_full_exposure_changes_nothing(self, frames):
        a, _r, _s = _build(frames)
        b, _r2, _s2 = _build(frames, crash_exposure=1.0)
        assert a == pytest.approx(b)


class TestEngagedScalesTheWholeBook:
    def test_gross_exposure_is_halved(self, frames):
        full, _r, _s = _build(frames)
        half, _r2, _s2 = _build(frames, crash_exposure=0.5)
        assert sum(half.values()) == pytest.approx(sum(full.values()) * 0.5)

    def test_composition_is_unchanged(self, frames):
        """Same names. A brake that also changes WHICH names are held is a second
        selection rule wearing a risk-control label."""
        full, _r, _s = _build(frames)
        half, _r2, _s2 = _build(frames, crash_exposure=0.5)
        assert set(half) == set(full)

    def test_relative_weights_are_preserved_exactly(self, frames):
        """The property that lets exposure be restored without re-ranking: every
        position is scaled by the SAME factor, so a name that was 20% of the book
        is 20% of the book again on restore."""
        full, _r, _s = _build(frames)
        half, _r2, _s2 = _build(frames, crash_exposure=0.5)
        ratios = {t: half[t] / full[t] for t in full}
        assert len(set(round(v, 12) for v in ratios.values())) == 1


class TestOrderingAgainstVolTarget:
    """The ordering that matters is NOT which multiplication happens first —
    scalars commute, so that distinction is empty. It is whether the brake is
    applied before `book_volatility` MEASURES the book.

    If it were, vol-targeting would see a halved book, compute that it has room
    to lever back up, and partly undo the brake — so the book would carry more
    risk in a crash than the config asked for. The fixture is deliberately tuned
    so vol-target exposure lands in the INTERIOR of [min, max]; at a saturated
    clamp the two orderings are indistinguishable and this test would pass
    vacuously.
    """

    def _cfg_interior(self):
        return _cfg(portfolio_builder={
            **_cfg().portfolio_builder.model_dump(),
            "vol_target_enabled": True, "vol_target": 0.002,
            "vol_target_min_exposure": 0.05})

    def test_the_fixture_actually_exercises_vol_targeting(self, frames):
        """Guards the paragraph above: if this de-levers to exactly 1.0 the clamp
        is saturated and the ordering test below proves nothing."""
        vol_only, _r, _s = _build(frames, cfg=self._cfg_interior())
        gross = sum(vol_only.values())
        assert 0.05 < gross < 0.999, f"vol-target is clamped, not interior: {gross}"

    def test_vol_targeting_measures_the_UNBRAKED_book(self, frames):
        """Braking first would let vol-targeting lever back up against it."""
        cfg = self._cfg_interior()
        vol_only, _r, _s = _build(frames, cfg=cfg)
        both, _r2, _s2 = _build(frames, crash_exposure=0.5, cfg=cfg)
        assert sum(both.values()) == pytest.approx(sum(vol_only.values()) * 0.5)
        assert sum(both.values()) < sum(vol_only.values())
