"""
Chaos/property fuzz of the ranking math that every ticker flows through:
factor normalization (z-score / percentile / winsorize) and rank_universe
(composite score + percentile). Hunts for non-finite output, out-of-range
percentiles, unclipped z-scores, non-monotone percentiles, NaN ranks.
"""
import math
import os
import random

import numpy as np
import pandas as pd

from app.factors import cross_section_percentile, cross_section_zscore, _winsorize
from app.rank import rank_universe, FACTORS
from stock_strategy_shared.loader import load_strategy

_STRAT_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "strategies", "quality_core_v1.yaml")
STRAT, _ = load_strategy(_STRAT_PATH)
REGIMES = list(STRAT.factor_weights.keys())


def _rand_series(rng, n):
    vals = []
    for _ in range(n):
        r = rng.random()
        if r < 0.15:
            vals.append(float("nan"))
        elif r < 0.18:
            vals.append(float("inf") * rng.choice([1, -1]))
        elif r < 0.25:
            vals.append(rng.choice([0.0, 1e12, -1e12, 7.0]))   # equal-ish / extreme
        else:
            vals.append(rng.uniform(-100, 100))
    return pd.Series(vals, index=[f"x{i}" for i in range(n)])


def test_zscore_fuzz():
    rng = random.Random(11)
    for _ in range(3000):
        s = _rand_series(rng, rng.randint(0, 30))
        z = cross_section_zscore(s, clip=2.5)
        assert list(z.index) == list(s.index)
        for i in s.index:
            zi = z[i]
            assert not (isinstance(zi, float) and math.isinf(zi)), f"inf z for {s[i]}"
            if pd.isna(s[i]):
                assert pd.isna(zi), "NaN input must stay NaN"
            if not pd.isna(zi):
                assert abs(zi) <= 2.5 + 1e-9, f"z {zi} exceeds clip"
        finite = s.replace([np.inf, -np.inf], np.nan).dropna()
        if len(finite) >= 2 and finite.nunique() == 1:           # all-equal valid → 0.0
            for i in finite.index:
                assert abs(z[i]) < 1e-12


def test_percentile_fuzz():
    rng = random.Random(13)
    for _ in range(3000):
        s = _rand_series(rng, rng.randint(0, 30))
        p = cross_section_percentile(s)
        assert list(p.index) == list(s.index)
        valid = p.dropna()
        for v in valid:
            assert 0.0 < v <= 1.0 + 1e-12, f"percentile {v} out of (0,1]"
        # fewer than 2 non-NaN inputs → all NaN
        if s.dropna().shape[0] < 2:
            assert p.isna().all()


def test_winsorize_fuzz():
    rng = random.Random(17)
    for _ in range(2000):
        s = _rand_series(rng, rng.randint(0, 40)).replace([np.inf, -np.inf], np.nan).dropna()
        w = _winsorize(s)
        assert list(w.index) == list(s.index)
        if len(s) >= 10:
            lo, hi = s.quantile(0.01), s.quantile(0.99)
            assert (w >= lo - 1e-9).all() and (w <= hi + 1e-9).all()
        else:
            assert (w.values == s.values).all() or w.equals(s)


def test_rank_universe_fuzz():
    rng = random.Random(19)
    for _ in range(1500):
        n = rng.randint(1, 60)
        data = {"ticker": [f"T{i:03d}" for i in range(n)]}
        for f in FACTORS:
            col = []
            for _ in range(n):
                col.append(float("nan") if rng.random() < 0.2 else rng.random())  # factors ∈ [0,1]
            data[f] = col
        df = pd.DataFrame(data)
        regime = rng.choice(REGIMES)
        out = rank_universe(df, regime, STRAT)

        m = len(out)
        if m == 0:
            continue
        # ranks contiguous 1..m
        assert list(out["rank"]) == list(range(1, m + 1)), "ranks not contiguous"
        # composite finite and in [0,1] (inputs in [0,1], weights re-normalized to sum 1)
        for cs in out["composite_score"]:
            assert math.isfinite(cs), "non-finite composite"
            assert -1e-9 <= cs <= 1.0 + 1e-9, f"composite {cs} out of [0,1]"
        # percentile in [0,1], monotone non-increasing with rank, endpoints correct
        pcts = list(out["percentile"])
        for v in pcts:
            assert -1e-9 <= v <= 1.0 + 1e-9, f"percentile {v} out of [0,1]"
        for a, b in zip(pcts, pcts[1:]):
            assert b <= a + 1e-9, "percentile not monotone with rank"
        if m > 1:
            assert abs(pcts[0] - 1.0) < 1e-9 and abs(pcts[-1] - 0.0) < 1e-9
        # composite sorted descending (rank 1 = best)
        cs_list = list(out["composite_score"])
        for a, b in zip(cs_list, cs_list[1:]):
            assert b <= a + 1e-9, "composite not sorted descending by rank"
