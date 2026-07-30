"""Does config-replay actually DO what its manifest says?

A manifest is a claim. The old cache fingerprint was also a claim — "this
identifies the dataset" — and it was wrong for two years without anything
noticing, because nothing checked the claim against behaviour. So this suite
runs the composer on ONE frozen point-in-time fixture and asserts:

    HONOURED field  → changing it CHANGES the target
    IGNORED field   → changing it leaves the target BIT-IDENTICAL

The second direction is the one that matters. An IGNORED declaration that is
secretly honoured is merely over-cautious; an HONOURED declaration that is
secretly ignored is the earnings-surprise bug all over again — a number returned
for a question that was never asked.

The fixture is deliberately small and synthetic: the point is not realism, it is
that every input is pinned, so a difference in output can only have come from the
field under test.
"""
import numpy as np
import pandas as pd
import pytest
import yaml
import os

from app.config_replay import build_target_for_date
from app.parity import HONOURED, IGNORED, MANIFEST, check_config_parity
from stock_strategy_shared.factor_registry import FACTOR_NAMES
from stock_strategy_shared.schemas.strategy import StrategyConfig

ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
TICKERS = [f"T{i:02d}" for i in range(24)]
AS_OF = pd.Timestamp("2024-06-28")


@pytest.fixture(scope="module")
def fixture():
    """One frozen point-in-time slice: factors, prices, sectors.

    Seeded and deterministic — every run of every test sees identical inputs, so
    any output difference is attributable to the config field under test and
    nothing else."""
    rng = np.random.default_rng(20260725)

    # Factor frame: the persisted point-in-time scores config-replay consumes.
    rows = []
    for i, t in enumerate(TICKERS):
        row = {"ticker": t}
        for f in FACTOR_NAMES:
            row[f] = float(rng.uniform(0.05, 0.95))
        # A deterministic spread on momentum so ranking is not a coin flip.
        row["momentum"] = 0.95 - i * 0.03
        rows.append(row)
    factor_df = pd.DataFrame(rows)

    # Prices: 400 sessions, distinct per-ticker drift and vol so covariance,
    # clustering, beta and the investability floor all have something to bite on.
    days = pd.bdate_range("2022-12-01", periods=400)
    # shared 0.010 vs idio 0.0058 puts within-bloc correlation around 0.75 —
    # above cluster_correlation_threshold (0.7) so blocs really cluster, but not
    # so dominant that the cluster CAP swamps every other field under test.
    bloc_shocks = [rng.normal(0, 0.010, size=len(days)) for _ in range(4)]
    prows = []
    for i, t in enumerate(TICKERS + ["SPY"]):
        px = 40.0 + i
        drift = 0.0004 + 0.00008 * (i % 5)
        # Names within a bloc share most of their shock, so they correlate well
        # above cluster_correlation_threshold and form MULTI-name clusters. With
        # only independent noise every cluster is a singleton and the cluster
        # caps are untestable — the probe would pass without exercising anything.
        idio = rng.normal(0, 0.0058, size=len(days))
        shocks = bloc_shocks[i % 4] + idio
        for d, sh in zip(days, shocks):
            px *= 1.0 + drift + sh
            prows.append({"ticker": t, "date": d, "adjusted_close": px,
                          "close": px, "volume": 4_000_000.0 + 90_000 * i})
    prices = pd.DataFrame(prows)
    prices = prices[prices["date"] <= AS_OF]

    sector_map = {t: ["Tech", "Energy", "Health", "Financials"][i % 4]
                  for i, t in enumerate(TICKERS)}
    return factor_df, prices, sector_map


@pytest.fixture(scope="module")
def base_cfg():
    with open(os.path.join(ROOT, "strategies", "momentum_rotation_v2.yaml")) as f:
        d = yaml.safe_load(f)
    # Scale the caps to a 24-name universe so selection is non-degenerate.
    # Caps deliberately RELAXED relative to production: each probe below must be
    # the only thing binding, or a "no change" result would just mean some other
    # cap was already dominating. max_positions=12 of 20 candidates is what makes
    # candidate_count separable (with 8 of 20, every pick came from the top 10 and
    # narrowing the head changed nothing). vol_target off for the same reason.
    d["portfolio_builder"].update({"max_positions": 12, "candidate_count": 20,
                                   "min_selected": 0, "max_position_weight": 0.20,
                                   "covariance_window_days": 120,
                                   "min_covariance_observations": 60,
                                   "max_cluster_weight": 0.60,
                                   "max_tickers_per_cluster": 4,
                                   "max_sector_weight": 0.60,
                                   "vol_target_enabled": False})
    d["universe"] = {"source": "av_listing", "min_price": 1.0,
                     "min_avg_dollar_volume_20d": 0.0}
    d["min_non_null_factors"] = 1
    return StrategyConfig(**d)


def _target(cfg, fixture) -> dict:
    factor_df, prices, sector_map = fixture
    out = build_target_for_date(factor_df.copy(), prices.copy(), cfg,
                                "bull_calm", dict(sector_map))
    return {r["ticker"]: round(float(r["weight"]), 12) for r in out}


def _with(cfg: StrategyConfig, path: str, value) -> StrategyConfig:
    d = cfg.model_dump()
    parts = path.split(".")
    node = d
    for p in parts[:-1]:
        node = node[p]
    node[parts[-1]] = value
    return StrategyConfig(**d)


# ── the fixture itself must be non-degenerate ───────────────────────────────

def test_the_fixture_produces_a_real_target(fixture, base_cfg):
    """Everything below compares targets. If the baseline target were empty,
    every 'unchanged' assertion would pass vacuously — the failure mode that
    makes a green suite meaningless."""
    t = _target(base_cfg, fixture)
    assert len(t) >= 4, t
    assert len(t) == base_cfg.portfolio_builder.max_positions, (
        "the base target must fill the cap, or the max_positions probe is testing "
        "a book that was already smaller than the cap")
    assert sum(t.values()) == pytest.approx(1.0 - base_cfg.portfolio_builder.cash_reserve,
                                            abs=0.02)


def test_the_composer_is_deterministic(fixture, base_cfg):
    """Bit-identical on repeat, or every comparison below is noise."""
    assert _target(base_cfg, fixture) == _target(base_cfg, fixture)


# ── HONOURED claims: the field must actually change the target ──────────────

HONOURED_PROBES = [
    ("portfolio_builder.max_positions", 3),
    # Each value is calibrated to BIND against the base target. A probe that does
    # not bite tests the probe, not the manifest — the first draft had three that
    # sat outside the binding range and passed for the wrong reason.
    ("portfolio_builder.max_position_weight", 0.06),
    ("portfolio_builder.weighting", "equal_weight"),
    ("portfolio_builder.candidate_count", 10),   # schema floor is 10
    ("portfolio_builder.max_sector_weight", 0.20),
    ("portfolio_builder.max_tickers_per_cluster", 1),
    ("portfolio_builder.cash_reserve", 0.20),
    ("portfolio_builder.do_not_buy", ["T00", "T01", "T02"]),
    ("universe.min_price", 1e9),          # floors everything out
    ("min_score_percentile", 0.9),        # applied inside rank_universe
]


@pytest.mark.parametrize("path,value", HONOURED_PROBES, ids=[p for p, _ in HONOURED_PROBES])
def test_an_honoured_field_changes_the_target(path, value, fixture, base_cfg):
    """An HONOURED declaration that is secretly ignored is the earnings-surprise
    bug: a number returned for a question nobody asked."""
    assert MANIFEST.verdict_for(path)[0] == HONOURED, (
        f"{path} is not declared HONOURED — update the probe or the manifest")
    before = _target(base_cfg, fixture)
    after = _target(_with(base_cfg, path, value), fixture)
    assert before != after, (
        f"'{path}' is declared HONOURED but changing it left the target identical")


def test_factor_weights_are_honoured(fixture, base_cfg):
    """Re-weighting stored factors is the ONE thing config-replay exists to do."""
    d = base_cfg.model_dump()
    d["static_factor_weights"] = {"momentum": 0.1, "quality": 0.5, "value": 0.2,
                                  "growth": 0.1, "low_volatility": 0.1}
    d["required_factors"] = ["momentum"]
    assert _target(base_cfg, fixture) != _target(StrategyConfig(**d), fixture)


# ── IGNORED claims: the field must leave the target untouched ───────────────
# This is the direction that matters. If one of these FAILS, the manifest is
# under-claiming and a config is being refused that could have been scored — but
# if it silently passed while the field DID matter, the gate would be pointless.

IGNORED_PROBES = [
    ("portfolio_builder.turnover_penalty", 0.5),
    ("factor_engine.momentum_long_window", 400),
    ("factor_engine.volatility_window", 100),
    ("factor_engine.pe_pb_cap", 12.0),
    ("universe.require_fundamentals", True),
    ("deduplicate_share_classes", False),
    ("delta_engine.orphan_confirmation_days", 9),
    ("delta_engine.rebalance_drift_threshold", 0.5),
    # NOT a delta_engine path, deliberately — see the manifest note. Nesting the
    # trailing stop under delta_engine would put it in the inert exception below and
    # config-replay would score a stop-enabled candidate as though the stop were
    # absent, with a Sharpe attached.
    ("trailing_stop.enabled", True),
    ("trailing_stop.stop_pct", 0.05),
]


@pytest.mark.parametrize("path,value", IGNORED_PROBES, ids=[p for p, _ in IGNORED_PROBES])
def test_an_ignored_field_leaves_the_target_identical(path, value, fixture, base_cfg):
    """Proves the IGNORED declarations are true rather than defensive. Each of
    these is a knob an evaluator could plausibly turn; each would come back with
    a Sharpe attached and mean nothing."""
    assert MANIFEST.verdict_for(path)[0] == IGNORED, (
        f"{path} is not declared IGNORED — update the probe or the manifest")
    before = _target(base_cfg, fixture)
    after = _target(_with(base_cfg, path, value), fixture)
    assert before == after, (
        f"'{path}' is declared IGNORED but changing it MOVED the target — the "
        f"manifest is wrong, and the gate is refusing a config it could score")


# ── and the gate refuses exactly those ──────────────────────────────────────

@pytest.mark.parametrize("path,value", IGNORED_PROBES, ids=[p for p, _ in IGNORED_PROBES])
def test_the_gate_refuses_every_ignored_change(path, value, base_cfg):
    """The other half of the contract: having proven the field does nothing here,
    the engine must SAY so rather than return a number.

    delta_engine is the deliberate exception — config-replay never runs the state
    machine, so those knobs are inert always and refusing on them would block
    every real config."""
    v = check_config_parity(_with(base_cfg, path, value), baseline=base_cfg)
    if path.startswith("delta_engine."):
        assert v == [], "delta_engine knobs are inert here — refusing is noise"
    else:
        assert any(path in x for x in v), (
            f"changing '{path}' silently produced the same target AND was not "
            f"refused — that is exactly the failure this gate exists to prevent")


def test_an_unchanged_candidate_is_never_refused(base_cfg):
    assert check_config_parity(base_cfg, baseline=base_cfg) == []


def test_a_weights_only_candidate_is_allowed(base_cfg):
    """The bread-and-butter use of this tool must stay cheap and unblocked."""
    d = base_cfg.model_dump()
    d["static_factor_weights"] = {"momentum": 0.3, "quality": 0.3, "value": 0.2,
                                  "growth": 0.1, "low_volatility": 0.1}
    d["required_factors"] = ["momentum"]
    assert check_config_parity(StrategyConfig(**d), baseline=base_cfg) == []
