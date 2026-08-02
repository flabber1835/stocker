"""TrailingStopConfig — the schema surface of the trailing-stop exit rule.

Two properties matter more than the field-by-field bounds:

  1. The block DEFAULTS OFF and is inert at defaults, so every existing config —
     and the live one — is unaffected until someone deliberately turns it on.
  2. It sits at TOP LEVEL, not under delta_engine. Both parity manifests flatten
     only two levels deep, so a nested block would be invisible to the CI
     classification guard; and config-replay's `_is_inert` treats every
     `delta_engine.*` path as inert, so nesting there would let it SILENTLY score
     a stop-enabled candidate as though the stop did not exist.
"""
import pytest
from pydantic import ValidationError

from stock_strategy_shared.schemas.strategy import (
    StrategyConfig,
    TrailingStopConfig,
)


def _minimal(**extra) -> dict:
    cfg = {
        "strategy_id": "t",
        "regime_detection": {
            "regimes": {
                "bull_calm": {"spy_above_slow_sma": True, "vol_above_threshold": False},
                "bull_stress": {"spy_above_slow_sma": True, "vol_above_threshold": True},
                "bear_stress": {"spy_above_slow_sma": False, "vol_above_threshold": True},
                "bear_calm": {"spy_above_slow_sma": False, "vol_above_threshold": False},
            },
        },
        "factor_weights": {
            r: {"momentum": 0.4, "quality": 0.3, "value": 0.2,
                "growth": 0.1, "low_volatility": 0.0}
            for r in ("bull_calm", "bull_stress", "bear_stress", "bear_calm")
        },
    }
    cfg.update(extra)
    return cfg


class TestDefaultsOff:
    def test_disabled_by_default(self):
        assert TrailingStopConfig().enabled is False

    def test_absent_block_materialises_disabled(self):
        """A config that never mentions the block must not acquire a live stop."""
        assert StrategyConfig(**_minimal()).trailing_stop.enabled is False

    def test_a_DEPLOYED_config_with_the_stop_on_is_COHERENTLY_configured(self):
        """The guard changed shape when the owner turned the stop on live.

        It used to assert no deployed config enabled it — an accident guard,
        correct while the feature was unproven. That premise is now spent: the
        stop is on in momentum_core_v3 by explicit decision. Keeping the old
        assertion would just mean deleting it, so it becomes the invariant that
        still has teeth — if a deployed config enables the stop, the settings
        that make it SAFE must be present:

          arm_after_sessions >= 2   a two-day-old position's peak IS its entry
                                    price; arming at 1 stops out on noise
          max_stale_sessions >= 1   a frozen print would emit an unfillable exit
                                    every run, forever
          max_stops_per_run  >= 1   exits are exempt from the turnover cap, so
                                    this is the ONLY brake on a drawdown
                                    liquidating the whole book
          stop_pct in (0, 0.9]      schema-enforced, restated so the intent is
                                    visible here
        """
        import os
        import re

        from stock_strategy_shared.loader import load_strategy

        root = os.path.join(os.path.dirname(__file__), "..", "..")
        compose = open(os.path.join(root, "docker-compose.yml")).read()
        deployed = {m for m in re.findall(
            r"STRATEGY_CONFIG_PATH:\s*/strategies/(\S+\.yaml)", compose)}
        assert deployed, "no deployed strategy config found in docker-compose.yml"
        for name in sorted(deployed):
            cfg, _h = load_strategy(os.path.join(root, "strategies", name))
            ts = cfg.trailing_stop
            if not ts.enabled:
                continue
            assert ts.arm_after_sessions >= 2, name
            assert ts.max_stale_sessions >= 1, name
            assert ts.max_stops_per_run >= 1, name
            assert 0 < ts.stop_pct <= 0.9, name

    def test_a_DEPLOYED_stop_only_config_has_a_stop(self):
        """exit_policy=trailing_stop_only with no stop has NO ordinary exit — the
        book fills to max_positions and freezes. The schema refuses it; this
        checks the deployed config specifically, because that is the one that
        would freeze a real book."""
        import os
        import re

        from stock_strategy_shared.loader import load_strategy

        root = os.path.join(os.path.dirname(__file__), "..", "..")
        compose = open(os.path.join(root, "docker-compose.yml")).read()
        for name in sorted({m for m in re.findall(
                r"STRATEGY_CONFIG_PATH:\s*/strategies/(\S+\.yaml)", compose)}):
            cfg, _h = load_strategy(os.path.join(root, "strategies", name))
            if cfg.delta_engine.exit_policy == "trailing_stop_only":
                assert cfg.trailing_stop.enabled, name

    def test_a_challenger_may_enable_it(self):
        """The complement: the feature has to be testable. If this file stops
        existing or stops enabling the stop, the wind tunnel has nothing to score
        the exit-regime change against."""
        import os

        from stock_strategy_shared.loader import load_strategy

        path = os.path.join(os.path.dirname(__file__), "..", "..",
                            "strategies", "momentum_stop_v1.yaml")
        cfg, _hash = load_strategy(path)
        assert cfg.trailing_stop.enabled is True
        assert cfg.delta_engine.exit_policy == "trailing_stop_only"


class TestTopLevelPlacement:
    def test_it_is_a_top_level_field(self):
        assert "trailing_stop" in StrategyConfig.model_fields

    def test_it_is_NOT_nested_under_delta_engine(self):
        """If someone 'tidies' this into delta_engine, config-replay's _is_inert
        would treat it as provably-harmless and score stop-enabled candidates as if
        the stop were absent."""
        from stock_strategy_shared.schemas.strategy import DeltaEngineConfig
        assert "trailing_stop" not in DeltaEngineConfig.model_fields

    def test_its_leaves_are_visible_two_levels_deep(self):
        """The depth the parity flatteners actually reach."""
        from stock_strategy_shared.parity import default_config_dump, flatten_config
        flat = flatten_config(default_config_dump())
        leaves = [p for p in flat if p.startswith("trailing_stop.")]
        assert "trailing_stop.enabled" in leaves
        assert "trailing_stop.stop_pct" in leaves


class TestBounds:
    @pytest.mark.parametrize("field,bad", [
        ("stop_pct", 0.0), ("stop_pct", -0.1), ("stop_pct", 1.5),
        ("arm_after_sessions", 1), ("arm_after_sessions", 0), ("arm_after_sessions", 500),
        ("max_stale_sessions", 0), ("max_stale_sessions", 99),
        ("max_stops_per_run", 0), ("max_stops_per_run", 1000),
    ])
    def test_out_of_bounds_rejected(self, field, bad):
        with pytest.raises(ValidationError):
            TrailingStopConfig(**{field: bad})

    def test_arming_floor_is_two_sessions(self):
        """A one-session-old position has a single close, so its peak IS its entry
        price and any downtick is a 'drawdown from peak'."""
        assert TrailingStopConfig.model_fields["arm_after_sessions"].metadata
        with pytest.raises(ValidationError):
            TrailingStopConfig(arm_after_sessions=1)
        assert TrailingStopConfig(arm_after_sessions=2).arm_after_sessions == 2

    def test_unknown_field_rejected(self):
        with pytest.raises(ValidationError):
            TrailingStopConfig(trail_percent=5)

    def test_values_round_trip(self):
        cfg = StrategyConfig(**_minimal(trailing_stop={
            "enabled": True, "stop_pct": 0.2, "arm_after_sessions": 10,
            "max_stale_sessions": 1, "max_stops_per_run": 3,
        }))
        ts = cfg.trailing_stop
        assert (ts.enabled, ts.stop_pct, ts.arm_after_sessions,
                ts.max_stale_sessions, ts.max_stops_per_run) == (True, 0.2, 10, 1, 3)

    def test_a_circuit_breaker_is_always_present(self):
        """There is no 'unlimited' setting. Exits are exempt from the risk-service
        turnover cap, so this is the only thing standing between a market-wide
        drawdown and liquidating the whole book at one open."""
        assert TrailingStopConfig().max_stops_per_run >= 1
        with pytest.raises(ValidationError):
            TrailingStopConfig(max_stops_per_run=0)
