"""The active config's drift-rebalance gates must be REACHABLE at its own
book granularity.

The bug this pins: `rebalance_drift_threshold` defaulted to 0.02 ABSOLUTE while
the active config runs 35 positions at ~2.79% target weight each — so a buy_add
could only fire after a position lost ~70% of its relative weight. No single
name ever tripped the gate; the small per-name drifts (winners lifting equity,
shrinking everyone else by ~0.1-0.2pp) accumulated as ~5pp of permanent idle
cash on top of the 2.5% designed reserve. Observed live for a week at 8.9% cash
before being diagnosed. See docs/architecture.md "drift-rebalance thresholds
calibrated to book granularity".

Two layers:
  1. Arithmetic against the ACTIVE YAML: a position that lost a material
     fraction of its target weight must clear every configured gate, so a
     future max_positions / threshold / cash_reserve edit that re-creates the
     unreachable state fails here instead of silently re-accumulating cash.
  2. Behaviour through the real engine with the ACTIVE config's values: the
     materially-drifted position gets a buy_add, the barely-drifted one holds.
"""
import os
from datetime import date

import yaml

from app.engine import RankObservation, evaluate_target_vs_live
from stock_strategy_shared.schemas.strategy import StrategyConfig

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
ACTIVE_YAML = os.path.join(ROOT, "strategies", "momentum_rotation_v2.yaml")

# The materiality bar this repo has decided on: a position that has lost 20% of
# its target weight is materially underweight and must be correctable.
MATERIAL_RELATIVE_DRIFT = 0.20


def _active() -> StrategyConfig:
    with open(ACTIVE_YAML) as f:
        return StrategyConfig(**yaml.safe_load(f))


def _per_name_target(cfg: StrategyConfig) -> float:
    """Equal-weight approximation of the per-name target weight."""
    exposure = 1.0 - cfg.portfolio_builder.cash_reserve
    return exposure / cfg.delta_engine.max_positions


class TestActiveConfigGateArithmetic:
    def test_absolute_threshold_is_reachable_at_book_granularity(self):
        """A material (20%) relative drift must exceed the absolute threshold.
        The old default 0.02 fails this at 35 positions (0.02 > 0.2 x 0.0279)."""
        cfg = _active()
        material_drift = MATERIAL_RELATIVE_DRIFT * _per_name_target(cfg)
        assert cfg.delta_engine.rebalance_drift_threshold <= material_drift, (
            f"rebalance_drift_threshold {cfg.delta_engine.rebalance_drift_threshold} "
            f"exceeds a material 20% drift ({material_drift:.4f}) on a "
            f"{cfg.delta_engine.max_positions}-name book — the gate is unreachable "
            "and drift will accumulate as idle cash again")

    def test_relative_gate_passes_a_material_drift(self):
        cfg = _active()
        assert cfg.delta_engine.rebalance_min_relative_drift <= MATERIAL_RELATIVE_DRIFT, (
            "the relative-materiality floor blocks the very drift the absolute "
            "threshold was lowered to catch")

    def test_dollar_gate_passes_a_material_drift_at_current_scale(self):
        """At any plausible account size for a 35-name book (>= ~$50k), a
        material drift correction clears the dollar floor."""
        cfg = _active()
        account_value = 50_000.0
        material_dollars = MATERIAL_RELATIVE_DRIFT * _per_name_target(cfg) * account_value
        assert cfg.delta_engine.rebalance_min_trade_value <= material_dollars, (
            f"rebalance_min_trade_value {cfg.delta_engine.rebalance_min_trade_value} "
            f"exceeds a material correction (${material_dollars:.0f}) at a $50k account")

    def test_old_default_would_fail_the_reachability_bar(self):
        """Guards the test itself: if this arithmetic could not distinguish the
        old broken default from the fix, every assertion above is vacuous."""
        cfg = _active()
        material_drift = MATERIAL_RELATIVE_DRIFT * _per_name_target(cfg)
        assert 0.02 > material_drift, (
            "the schema-default 0.02 now passes the reachability bar — either "
            "the book got much chunkier (fine: update this test) or the bar is "
            "too loose to catch the original bug")


class TestActiveConfigGateBehaviour:
    """Drive the real engine with the ACTIVE config's gate values."""

    def _run(self, actual_weight: float):
        cfg = _active()
        de = cfg.delta_engine
        target_w = _per_name_target(cfg)
        obs = [RankObservation(run_date=date(2026, 7, 24), rank=5,
                               composite_score=0.9)]
        return evaluate_target_vs_live(
            target_portfolio={"AAA": target_w},
            live_positions={"AAA"},
            universe={"AAA": obs},
            confirmation_days=de.confirmation_days,
            max_positions=de.max_positions,
            actual_weights={"AAA": actual_weight},
            drift_threshold=de.rebalance_drift_threshold,
            min_relative_drift=de.rebalance_min_relative_drift,
            min_trade_value=de.rebalance_min_trade_value,
            account_value=100_000.0,
        )

    def test_materially_underweight_position_gets_a_buy_add(self):
        cfg = _active()
        target_w = _per_name_target(cfg)
        # 25% relative underweight — the drift class that used to sit invisible.
        d = self._run(actual_weight=target_w * 0.75)
        assert d["AAA"].action == "buy_add", d["AAA"].reason

    def test_immaterial_drift_still_holds(self):
        cfg = _active()
        target_w = _per_name_target(cfg)
        # 5% relative underweight — noise; must NOT churn.
        d = self._run(actual_weight=target_w * 0.95)
        assert d["AAA"].action == "hold", d["AAA"].reason
