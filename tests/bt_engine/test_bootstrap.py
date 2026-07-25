"""Terminal-wealth bootstrap — statistical validation.

This feeds the promotion gate, which rewrites the LIVE config automatically. So
the properties are asserted against closed-form answers wherever one exists,
rather than against whatever the implementation happens to emit.
"""
import math

import numpy as np
import pytest

from app.bootstrap import (
    DEFAULT_BLOCK_DAYS,
    _block_index_matrix,
    bootstrap_terminal_wealth,
    daily_returns,
    tail_is_acceptable,
)


# ── daily_returns ────────────────────────────────────────────────────────────

def test_daily_returns_are_simple_period_returns():
    rows = [{"portfolio_value": 100.0}, {"portfolio_value": 110.0},
            {"portfolio_value": 99.0}]
    assert daily_returns(rows) == pytest.approx([0.10, -0.10])


def test_daily_returns_stop_at_a_wiped_out_book():
    """Dividing by a zero or negative equity yields inf/NaN that silently
    poisons every downstream percentile."""
    rows = [{"portfolio_value": 100.0}, {"portfolio_value": 0.0},
            {"portfolio_value": 5.0}]
    r = daily_returns(rows)
    assert r == pytest.approx([-1.0])
    assert all(math.isfinite(x) for x in r)


def test_daily_returns_skip_unparseable_rows():
    rows = [{"portfolio_value": 100.0}, {"portfolio_value": None},
            {"nope": 1}, {"portfolio_value": 121.0}]
    assert daily_returns(rows) == pytest.approx([0.21])


# ── the index matrix (the part that is easy to get subtly wrong) ─────────────

def test_index_matrix_has_exact_shape_and_valid_indices():
    rng = np.random.default_rng(0)
    idx = _block_index_matrix(n=100, block=21, n_paths=50, rng=rng)
    assert idx.shape == (50, 100), "resampled path must match the real horizon"
    assert idx.min() >= 0 and idx.max() < 100


def test_blocks_are_contiguous_and_wrap_circularly():
    """Within a block, indices must advance by exactly 1 modulo n. That is what
    preserves volatility clustering; break it and this is an IID bootstrap
    wearing a block bootstrap's name."""
    n, block = 37, 8
    idx = _block_index_matrix(n, block, 200, np.random.default_rng(1))
    for path in idx:
        for b0 in range(0, (len(path) // block) * block, block):
            seg = path[b0:b0 + block]
            expected = (seg[0] + np.arange(block)) % n
            assert np.array_equal(seg, expected)


def test_circular_wrap_samples_every_observation_equally():
    """THE reason for circular blocks. A non-circular bootstrap under-samples
    both ends — early points can only START a block, late points only END one —
    which biases the very tail this exists to measure."""
    n = 50
    idx = _block_index_matrix(n, block=10, n_paths=4000,
                              rng=np.random.default_rng(7))
    counts = np.bincount(idx.ravel(), minlength=n).astype(float)
    share = counts / counts.sum()
    # every observation within 15% of uniform (1/n)
    assert share.max() < (1.0 / n) * 1.15
    assert share.min() > (1.0 / n) * 0.85


# ── terminal wealth: closed-form checks ─────────────────────────────────────

def test_constant_returns_reproduce_the_deterministic_answer_exactly():
    """With zero variance every resampled path is identical, so the bootstrap
    must return the analytic compounding result and a zero-width distribution."""
    n, r = 252, 0.001
    out = bootstrap_terminal_wealth([r] * n, starting_capital=100_000.0,
                                    block_days=21, n_paths=200)
    expected = 100_000.0 * (1 + r) ** n
    # wealth fields are rounded to the cent on the way out, so compare at that
    # resolution — the zero-WIDTH property below is the real assertion
    assert out["median_terminal_wealth"] == pytest.approx(expected, abs=0.01)
    assert out["p5_terminal_wealth"] == pytest.approx(expected, abs=0.01)
    assert out["p95_terminal_wealth"] == pytest.approx(expected, abs=0.01)
    assert out["p95_terminal_wealth"] == out["p5_terminal_wealth"], \
        "zero variance must give a zero-width distribution"
    assert out["prob_loss"] == 0.0
    assert out["median_multiple"] == pytest.approx((1 + r) ** n, abs=1e-6)


def test_median_log_wealth_matches_the_analytic_mean():
    """Every resampled path is a sum of n draws from the same pool, so the
    EXPECTED log terminal wealth is exactly n * mean(log1p(r)). The median of a
    near-symmetric sum should land on it."""
    rng = np.random.default_rng(11)
    r = rng.normal(0.0005, 0.01, size=504)
    out = bootstrap_terminal_wealth(r, starting_capital=1.0, block_days=21,
                                    n_paths=4000, seed=3)
    analytic = float(np.sum(np.log1p(r)))          # n * mean(log1p)
    assert math.log(out["median_terminal_wealth"]) == pytest.approx(
        analytic, abs=0.05)


def test_a_fatter_tail_shows_up_as_a_lower_p5_at_equal_central_outcome():
    """The whole point. Two series with near-identical compounded return, one
    with far more variance — the gate must be able to see the difference."""
    n = 504
    calm = np.full(n, 0.0004)
    wild = np.full(n, 0.0004)
    rng = np.random.default_rng(5)
    shock = rng.normal(0.0, 0.02, size=n)
    wild = wild + shock - shock.mean()             # same mean, much more spread
    c = bootstrap_terminal_wealth(calm, starting_capital=1.0, n_paths=3000, seed=1)
    w = bootstrap_terminal_wealth(wild, starting_capital=1.0, n_paths=3000, seed=1)
    assert w["median_multiple"] == pytest.approx(c["median_multiple"], rel=0.12)
    assert w["p5_multiple"] < c["p5_multiple"] * 0.9, (
        "a materially fatter tail did not lower the 5th percentile")


def test_scaling_every_return_up_raises_terminal_wealth():
    rng = np.random.default_rng(2)
    base = rng.normal(0.0003, 0.008, size=400)
    lo = bootstrap_terminal_wealth(base, starting_capital=1.0, n_paths=1500, seed=9)
    hi = bootstrap_terminal_wealth(base + 0.0004, starting_capital=1.0,
                                   n_paths=1500, seed=9)
    assert hi["median_multiple"] > lo["median_multiple"]
    assert hi["p5_multiple"] > lo["p5_multiple"]


def test_percentiles_are_ordered():
    rng = np.random.default_rng(4)
    out = bootstrap_terminal_wealth(rng.normal(0.0002, 0.012, 400),
                                    starting_capital=1.0, n_paths=2000, seed=6)
    assert (out["p5_terminal_wealth"] <= out["p25_terminal_wealth"]
            <= out["median_terminal_wealth"] <= out["p75_terminal_wealth"]
            <= out["p95_terminal_wealth"])


def test_total_loss_is_survivable_and_finite():
    """A -100% day must land the path at ~0, not NaN/-inf."""
    out = bootstrap_terminal_wealth([0.01] * 60 + [-1.0] + [0.01] * 60,
                                    starting_capital=1000.0, block_days=5,
                                    n_paths=500, seed=8)
    for k, v in out.items():
        if isinstance(v, float):
            assert math.isfinite(v), k
    assert out["p5_terminal_wealth"] >= 0.0


# ── determinism (a system-wide contract) ────────────────────────────────────

def test_same_seed_same_numbers_and_different_seed_differs():
    rng = np.random.default_rng(3)
    r = rng.normal(0.0004, 0.01, size=300)
    a = bootstrap_terminal_wealth(r, starting_capital=1.0, n_paths=800, seed=42)
    b = bootstrap_terminal_wealth(r, starting_capital=1.0, n_paths=800, seed=42)
    c = bootstrap_terminal_wealth(r, starting_capital=1.0, n_paths=800, seed=43)
    assert a == b, "bootstrap is not reproducible under a fixed seed"
    assert a["p5_terminal_wealth"] != c["p5_terminal_wealth"]


# ── refusing to answer ──────────────────────────────────────────────────────

@pytest.mark.parametrize("n", [0, 1, 10, 2 * DEFAULT_BLOCK_DAYS - 1])
def test_too_little_data_returns_none_rather_than_a_fabricated_distribution(n):
    assert bootstrap_terminal_wealth([0.001] * n) is None


def test_non_finite_returns_are_dropped():
    r = [0.01, float("nan"), 0.01, float("inf")] * 30
    out = bootstrap_terminal_wealth(r, starting_capital=1.0, block_days=5,
                                    n_paths=200, seed=2)
    assert out is not None and out["n_observations"] == 60


# ── paired benchmark ────────────────────────────────────────────────────────

def test_benchmark_is_resampled_with_the_same_draws():
    """Paired resampling: comparing two INDEPENDENTLY shuffled worlds would
    destroy the co-movement and make prob_beat_benchmark meaningless. A series
    that beats the benchmark on every single day must beat it on every path."""
    n = 300
    rng = np.random.default_rng(12)
    bench = rng.normal(0.0003, 0.01, size=n)
    port = bench + 0.0002                        # strictly better, every day
    out = bootstrap_terminal_wealth(port, starting_capital=1.0, block_days=21,
                                    n_paths=1000, seed=1, benchmark_returns=bench)
    assert out["prob_beat_benchmark"] == 1.0
    assert out["median_excess_multiple"] > 0

    worse = bench - 0.0002
    out2 = bootstrap_terminal_wealth(worse, starting_capital=1.0, block_days=21,
                                     n_paths=1000, seed=1, benchmark_returns=bench)
    assert out2["prob_beat_benchmark"] == 0.0


def test_mismatched_benchmark_length_is_ignored_not_guessed():
    out = bootstrap_terminal_wealth([0.001] * 100, starting_capital=1.0,
                                    block_days=10, n_paths=200,
                                    benchmark_returns=[0.001] * 42)
    assert "prob_beat_benchmark" not in out


# ── the gate helper ─────────────────────────────────────────────────────────

def test_tail_guard_blocks_a_worse_left_tail():
    ok, why = tail_is_acceptable({"p5_multiple": 0.80}, {"p5_multiple": 0.95},
                                 tolerance=0.05)
    assert ok is False and "left tail worse" in why


def test_tail_guard_allows_a_tail_within_tolerance():
    assert tail_is_acceptable({"p5_multiple": 0.91}, {"p5_multiple": 0.95},
                              tolerance=0.05)[0] is True
    assert tail_is_acceptable({"p5_multiple": 1.20}, {"p5_multiple": 0.95})[0] is True


def test_tail_guard_is_inert_when_stats_are_missing():
    """It runs alongside the existing gate on results that may predate the
    feature or come from a regime run. A new check must never silently block
    every promotion because an older row lacks a field."""
    assert tail_is_acceptable(None, {"p5_multiple": 0.9})[0] is True
    assert tail_is_acceptable({"p5_multiple": 0.9}, None)[0] is True
    assert tail_is_acceptable({}, {})[0] is True
    assert "skipped" in tail_is_acceptable({}, {})[1]


def test_tail_guard_boundary_is_exactly_the_tolerance():
    # exactly at tolerance => allowed; a hair beyond => refused
    assert tail_is_acceptable({"p5_multiple": 0.90}, {"p5_multiple": 0.95},
                              tolerance=0.05)[0] is True
    assert tail_is_acceptable({"p5_multiple": 0.8999}, {"p5_multiple": 0.95},
                              tolerance=0.05)[0] is False
