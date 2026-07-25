"""Factor-coverage contract.

This gate exists because `composite_scores` renormalizes per row over the
non-null factors. That is correct for a factor missing on SOME tickers and
catastrophic for one missing from the whole corpus: the run returns a plausible
number for a strategy nobody asked for. With auto-promotion enabled, that number
can rewrite the live config.

So the tests below assert the ARITHMETIC of the failure first — proving the
renormalization really does silently rescale the other weights — and then that
the gate refuses exactly those configs.
"""
import os

import pandas as pd
import pytest
import yaml
from stock_strategy_shared.factor_registry import FACTOR_NAMES
from stock_strategy_shared.schemas.strategy import StrategyConfig
from stock_strategy_shared.strategy_engine.rank import composite_scores

from app.coverage import (
    SUPPORTED_FACTORS,
    UNSUPPORTED_FACTORS,
    CoverageObserver,
    check_config_coverage,
    enforcement_enabled,
    registry_is_fully_classified,
    weighted_factors,
)

ROOT = os.path.join(os.path.dirname(__file__), "..", "..")


def _w(**overrides) -> dict:
    """A COMPLETE, valid weight vector. FactorWeights requires the five core
    fields and enforces a sum of 1.0, so a partial dict is a schema error, not a
    coverage question."""
    base = {"momentum": 0.0, "quality": 0.0, "value": 0.0, "growth": 0.0,
            "low_volatility": 0.0}
    base.update(overrides)
    total = sum(base.values())
    assert total > 0, "give at least one nonzero weight"
    return {k: v / total for k, v in base.items()}


def _reweighted(**overrides) -> StrategyConfig:
    """The active config with its STATIC weights replaced. required_factors is
    narrowed to momentum because StrategyConfig separately refuses a required
    factor carrying zero weight — an unrelated rule that would otherwise mask
    what these tests are actually asserting."""
    d = _cfg().model_dump()
    d["static_factor_weights"] = _w(**overrides)
    d["required_factors"] = ["momentum"]
    return StrategyConfig(**d)


def _cfg(path="momentum_rotation_v2.yaml") -> StrategyConfig:
    with open(os.path.join(ROOT, "strategies", path)) as f:
        return StrategyConfig(**yaml.safe_load(f))


# ── the bug itself, stated as arithmetic ────────────────────────────────────

def test_a_missing_factor_silently_rescales_every_other_weight():
    """THE reason this module exists. Dropping earnings_surprise does not score
    it as zero — it redistributes 0.12 across the rest, lifting momentum's
    effective weight from 0.360 to 0.409 (+13.6%)."""
    weights = {f: 0.0 for f in FACTOR_NAMES}
    weights.update({"momentum": 0.36, "earnings_surprise": 0.12, "quality": 0.20,
                    "low_volatility": 0.14, "value": 0.08, "liquidity": 0.06,
                    "growth": 0.04})
    # One ticker scoring 1.0 on momentum and 0.0 on everything else: its
    # composite IS momentum's effective weight.
    row = {f: 0.0 for f in FACTOR_NAMES}
    row["momentum"] = 1.0

    with_es = composite_scores(pd.DataFrame([row]), weights, min_factors=1, required=set())
    assert float(with_es.iloc[0]) == pytest.approx(0.36)

    row_without = dict(row)
    row_without["earnings_surprise"] = float("nan")
    without = composite_scores(pd.DataFrame([row_without]), weights,
                               min_factors=1, required=set())
    assert float(without.iloc[0]) == pytest.approx(0.36 / 0.88)   # 0.409…
    assert float(without.iloc[0]) > float(with_es.iloc[0]) * 1.13


# ── static gate ─────────────────────────────────────────────────────────────

def test_the_active_config_is_refused_until_sue_parity_lands():
    """momentum_rotation_v2 weights earnings_surprise at 0.12 and the corpus has
    no analyst estimates. Being refused is the CORRECT state — silently scoring
    it is what produced void results for weeks."""
    violations = check_config_coverage(_cfg())
    assert len(violations) == 1
    assert "earnings_surprise" in violations[0]
    assert "0.12" in violations[0]


def test_a_config_using_only_supported_factors_passes():
    assert check_config_coverage(
        _reweighted(momentum=0.5, quality=0.3, low_volatility=0.2)) == []


def test_zero_weight_on_an_unsupported_factor_is_fine():
    """The factor is renormalized out either way when its weight is 0, so there
    is nothing to distort and nothing to refuse. Refusing here would block
    configs that merely MENTION the factor."""
    assert check_config_coverage(
        _reweighted(momentum=0.6, quality=0.4, earnings_surprise=0.0)) == []


def test_static_weights_are_not_judged_on_unused_regime_vectors():
    """With regime_weighting_enabled false, the four regime vectors are never
    consulted. Judging them would refuse configs that are perfectly scorable —
    and would mean re-deriving the enabled/disabled rule here, which is the
    drift this module exists to prevent."""
    d = _cfg().model_dump()
    assert d["regime_weighting_enabled"] is False
    d["required_factors"] = ["momentum"]
    d["static_factor_weights"] = _w(momentum=0.6, quality=0.4)
    # Load an uncomputable factor into a REGIME vector. Rotation is off, so this
    # vector is never consulted and must not be judged.
    d["factor_weights"]["bull_calm"] = _w(momentum=0.5, quality=0.3,
                                          earnings_surprise=0.2)
    cfg = StrategyConfig(**d)
    assert cfg.factor_weights["bull_calm"].earnings_surprise > 0
    assert "earnings_surprise" not in weighted_factors(cfg)
    assert check_config_coverage(cfg) == []

    # ...and the same config WITH rotation on is refused, proving the gate is
    # reading the enabled flag rather than ignoring regime vectors wholesale.
    d["regime_weighting_enabled"] = True
    assert check_config_coverage(StrategyConfig(**d)) != []


def test_regime_rotation_on_checks_every_regime_vector():
    """The mirror case: with rotation ON, a factor weighted in ONE regime can
    distort that regime's scores, so it must be caught."""
    d = _cfg().model_dump()
    d["regime_weighting_enabled"] = True
    d["required_factors"] = ["momentum"]
    for regime in ("bull_calm", "bull_stress", "bear_stress", "bear_calm"):
        d["factor_weights"][regime] = _w(momentum=0.6, quality=0.4)
    d["factor_weights"]["bear_calm"] = _w(momentum=0.5, quality=0.3,
                                          earnings_surprise=0.2)
    violations = check_config_coverage(StrategyConfig(**d))
    assert len(violations) == 1 and "earnings_surprise" in violations[0]


def test_violation_message_explains_the_consequence_not_just_the_fact():
    """A gate whose message is 'unsupported factor' teaches nobody why the run
    was refused, and the next person deletes the gate."""
    msg = check_config_coverage(_cfg())[0]
    assert "renormalize" in msg.lower()
    assert "different strategy" in msg.lower()


def test_violations_are_reported_even_when_enforcement_is_off(monkeypatch):
    """BT_COVERAGE_ENFORCE=false must change what the CALLER does, not blind the
    diagnosis. A disabled gate that is also silent is the original bug."""
    monkeypatch.setenv("BT_COVERAGE_ENFORCE", "false")
    assert enforcement_enabled() is False
    assert check_config_coverage(_cfg()) != []


@pytest.mark.parametrize("val,expected", [
    ("false", False), ("FALSE", False), ("0", False), ("no", False),
    ("off", False), ("true", True), ("", True), ("anything", True)])
def test_enforcement_flag_parsing(monkeypatch, val, expected):
    monkeypatch.setenv("BT_COVERAGE_ENFORCE", val)
    assert enforcement_enabled() is expected


def test_enforcement_defaults_to_on_when_unset(monkeypatch):
    monkeypatch.delenv("BT_COVERAGE_ENFORCE", raising=False)
    assert enforcement_enabled() is True


def test_enforcement_is_read_per_call_not_cached_at_import(monkeypatch):
    """It is a safety gate; flipping it must not require an image rebuild."""
    monkeypatch.setenv("BT_COVERAGE_ENFORCE", "true")
    assert enforcement_enabled() is True
    monkeypatch.setenv("BT_COVERAGE_ENFORCE", "false")
    assert enforcement_enabled() is False


# ── the declaration itself ──────────────────────────────────────────────────

def test_every_registry_factor_is_classified():
    """Adding a factor without deciding its wind-tunnel status must fail HERE,
    not silently default to 'supported' and reintroduce the bug."""
    assert registry_is_fully_classified() == []


def test_coverage_closed_for_everything_except_earnings_surprise():
    """After the bt-data fix, small_cap and issuance are computable. Pinned so a
    regression in bt-data's mapper shows up as a failing contract."""
    assert set(UNSUPPORTED_FACTORS) == {"earnings_surprise"}
    for f in ("small_cap", "issuance", "volume_surge", "near_high",
              "high_volatility"):
        assert f in SUPPORTED_FACTORS, f


def test_every_supported_factor_names_its_input():
    """The declaration is a contract, not a list: if you cannot name the column
    that feeds a factor, you cannot claim it is covered."""
    for name, source in SUPPORTED_FACTORS.items():
        assert source and ("bt_prices" in source or "bt_fundamentals" in source), name


# ── empirical backstop ──────────────────────────────────────────────────────

def _frame(**cols) -> pd.DataFrame:
    base = {f: [0.5, 0.5] for f in FACTOR_NAMES}
    base.update(cols)
    return pd.DataFrame(base)


def test_observer_flags_a_factor_null_on_every_rebalance():
    cfg = _cfg()
    obs = CoverageObserver(cfg)
    for _ in range(5):
        obs.observe(_frame(earnings_surprise=[None, None]))
    v = obs.violations()
    assert len(v) == 1 and "earnings_surprise" in v[0] and "5 rebalance" in v[0]


def test_observer_forgives_a_factor_that_was_null_only_early():
    """Warm-up. A factor can legitimately be all-null at the start of a window;
    failing on the first frame would false-positive on exactly the thin-data
    configs the tunnel is meant to explore."""
    obs = CoverageObserver(_cfg())
    obs.observe(_frame(earnings_surprise=[None, None]))
    obs.observe(_frame(earnings_surprise=[None, None]))
    obs.observe(_frame(earnings_surprise=[0.7, None]))   # appears once
    assert obs.violations() == []


def test_observer_ignores_unweighted_factors():
    """small_cap is weight-0 in the active config; its absence distorts no
    score, so it must not fail a run."""
    obs = CoverageObserver(_cfg())
    obs.observe(_frame(small_cap=[None, None], issuance=[None, None]))
    assert all("small_cap" not in v and "issuance" not in v
               for v in obs.violations())


def test_observer_stays_silent_when_no_frames_were_ever_produced():
    """A run that produced zero factor frames failed for some other reason.
    Reporting every weighted factor as a coverage violation would misdiagnose
    it and send the next person to the wrong place."""
    obs = CoverageObserver(_cfg())
    assert obs.violations() == []
    obs.observe(None)
    obs.observe(pd.DataFrame())
    assert obs.violations() == []


def test_observer_treats_a_missing_column_as_missing_data():
    obs = CoverageObserver(_cfg())
    obs.observe(pd.DataFrame({"ticker": ["A"], "momentum": [0.5]}))
    assert any("earnings_surprise" in v for v in obs.violations())


# ── end-to-end wiring ───────────────────────────────────────────────────────
# The unit tests above prove CoverageObserver's logic. These prove sim.py
# actually THREADS it through build_target — an observer that is never called is
# indistinguishable from a passing check, which is the failure mode this whole
# change exists to eliminate.

def _sim_cfg(**over):
    from .test_sim import _cfg
    d = _cfg().model_dump()
    d.update(over)
    return StrategyConfig(**d)


def test_a_real_simulation_raises_when_a_weighted_factor_is_absent():
    from app.coverage import CoverageError
    from app.sim import SimParams, run_simulation

    from .test_plausibility import _rising

    prices, fnd, days = _rising(n_days=520)
    # The synthetic fundamentals carry no earnings; weight the factor anyway.
    cfg = _sim_cfg(static_factor_weights=_w(momentum=0.5, quality=0.3,
                                            earnings_surprise=0.2),
                   required_factors=["momentum"])
    with pytest.raises(CoverageError) as exc:
        run_simulation(prices, fnd, {}, cfg,
                       SimParams(start=days[60].date(), end=days[-1].date(),
                                 tx_cost_bps=10, fill_timing="next_open",
                                 rebalance_every=5))
    msg = str(exc.value)
    assert "earnings_surprise" in msg
    assert "momentum" not in msg, (
        "momentum has enough history here — a second violation would mean the "
        "fixture, not the coverage gap, is what failed the run")


def test_the_same_simulation_succeeds_without_the_absent_factor():
    """Control: proves the raise above is the COVERAGE check firing, not the
    fixture being broken in some unrelated way."""
    from app.sim import SimParams, run_simulation

    from .test_plausibility import _rising

    prices, fnd, days = _rising(n_days=520)
    cfg = _sim_cfg(static_factor_weights=_w(momentum=0.5, quality=0.3,
                                            value=0.2),
                   required_factors=["momentum"])
    r = run_simulation(prices, fnd, {}, cfg,
                       SimParams(start=days[60].date(), end=days[-1].date(),
                                 tx_cost_bps=10, fill_timing="next_open",
                                 rebalance_every=5))
    assert r.summary["total_return"] is not None


def test_enforcement_off_downgrades_the_raise_to_a_caveat(monkeypatch):
    """BT_COVERAGE_ENFORCE=false must still SAY it — the result is void either
    way, and a silent degraded run is the original bug verbatim."""
    monkeypatch.setenv("BT_COVERAGE_ENFORCE", "false")
    from app.sim import SimParams, run_simulation

    from .test_plausibility import _rising

    prices, fnd, days = _rising(n_days=520)
    cfg = _sim_cfg(static_factor_weights=_w(momentum=0.5, quality=0.3,
                                            earnings_surprise=0.2),
                   required_factors=["momentum"])
    r = run_simulation(prices, fnd, {}, cfg,
                       SimParams(start=days[60].date(), end=days[-1].date(),
                                 tx_cost_bps=10, fill_timing="next_open",
                                 rebalance_every=5))
    assert any("earnings_surprise" in c for c in r.caveats)
