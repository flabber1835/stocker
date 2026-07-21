"""Vectorized composite_scores must be EXACTLY the old row-wise scoring.

The row-wise df.apply implementation (kept verbatim below as the oracle) was
the ranking hot path — O(rows) Python-level calls per rebalance date, which
multiplied across a full universe × decades × 54 sweep configs. The vectorized
replacement must be behavior-preserving: same NaN mask, same scores to within
float-summation noise (~1e-15). This suite is the proof.
"""
import math
import random

import numpy as np
import pandas as pd
import pytest

from stock_strategy_shared.strategy_engine.rank import FACTORS, composite_scores


def _rowwise_oracle(df: pd.DataFrame, regime_weights: dict, min_factors: int,
                    required: set) -> pd.Series:
    """The ORIGINAL implementation, verbatim from rank_universe pre-vectorization."""
    def compute_score(row: pd.Series) -> float:
        available = {f: regime_weights[f] for f in FACTORS if pd.notna(row.get(f))}
        if len(available) < min_factors:
            return float("nan")
        if any(pd.isna(row.get(f)) for f in required):
            return float("nan")
        weight_sum = sum(available.values())
        if weight_sum == 0:
            return float("nan")
        return sum((w / weight_sum) * row[f] for f, w in available.items())
    if df.empty:
        return pd.Series(dtype=float, index=df.index)
    return df.apply(compute_score, axis=1)


def _assert_equivalent(df, weights, min_factors, required):
    old = _rowwise_oracle(df, weights, min_factors, required)
    new = composite_scores(df, weights, min_factors, required)
    assert list(old.index) == list(new.index)
    for i in df.index:
        o, n = old.loc[i], new.loc[i]
        if isinstance(o, float) and math.isnan(o):
            assert math.isnan(n), f"row {i}: oracle NaN, vectorized {n}"
        else:
            assert n == pytest.approx(o, abs=1e-12), f"row {i}: {o} vs {n}"


def _weights(rng, zero_some=False):
    w = {f: round(rng.uniform(0, 0.4), 3) for f in FACTORS}
    if zero_some:
        for f in rng.sample(FACTORS, k=len(FACTORS) // 2):
            w[f] = 0.0
    return w


def _frame(rng, n_rows, nan_frac, drop_cols=()):
    data = {"ticker": [f"T{i:04d}" for i in range(n_rows)]}
    for f in FACTORS:
        if f in drop_cols:
            continue
        col = [rng.uniform(-2, 2) if rng.random() > nan_frac else np.nan
               for _ in range(n_rows)]
        data[f] = col
    return pd.DataFrame(data)


def test_fuzz_equivalence_across_shapes_and_nan_densities():
    rng = random.Random(42)
    for trial in range(30):
        df = _frame(rng, n_rows=rng.randint(1, 60), nan_frac=rng.choice([0.0, 0.2, 0.6, 0.95]),
                    drop_cols=rng.sample(FACTORS, k=rng.choice([0, 0, 1, 3])))
        weights = _weights(rng, zero_some=rng.random() < 0.5)
        min_factors = rng.randint(0, len(FACTORS))
        required = set(rng.sample(FACTORS, k=rng.choice([0, 0, 1, 2])))
        _assert_equivalent(df, weights, min_factors, required)


def test_zero_weight_factor_still_counts_as_available():
    # weight-0 factor with a value counts toward min_factors (old semantics)
    df = pd.DataFrame({"ticker": ["A"], FACTORS[0]: [1.0], FACTORS[1]: [2.0]})
    w = {f: 0.0 for f in FACTORS}
    w[FACTORS[1]] = 1.0
    _assert_equivalent(df, w, 2, set())
    out = composite_scores(df, w, min_factors=2, required=set())
    assert out.iloc[0] == pytest.approx(2.0)     # renormalized over nonzero weight


def test_all_available_weights_zero_is_nan():
    df = pd.DataFrame({"ticker": ["A"], FACTORS[0]: [1.0]})
    w = {f: 0.0 for f in FACTORS}
    w[FACTORS[1]] = 1.0                          # weighted factor is NULL here
    _assert_equivalent(df, w, 0, set())
    assert math.isnan(composite_scores(df, w, 0, set()).iloc[0])


def test_required_factor_missing_column_is_nan():
    df = pd.DataFrame({"ticker": ["A"], FACTORS[0]: [1.0]})
    w = {f: 0.1 for f in FACTORS}
    _assert_equivalent(df, w, 0, {FACTORS[2]})   # required col absent entirely
    assert math.isnan(composite_scores(df, w, 0, {FACTORS[2]}).iloc[0])


def test_empty_frame():
    df = pd.DataFrame({"ticker": pd.Series(dtype=str)})
    out = composite_scores(df, {f: 0.1 for f in FACTORS}, 1, set())
    assert len(out) == 0
