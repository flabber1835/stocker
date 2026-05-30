"""
Chaos/property fuzz of portfolio-builder weight math (compute_weights).

Documented contract: "Returns weights that sum to 1.0", every weight ≤
max_position_weight (when feasible), ≥ 0, finite. Fuzzed across all four methods
with adversarial n / caps / sectors to hunt for sum-drift, cap breaches, NaN.
"""
import math
import random

import numpy as np
import pandas as pd
import pytest

from app.select import compute_weights

METHODS = ["equal_weight", "adj_score_proportional", "score_proportional", "inverse_vol"]


def _make(n, rng):
    tickers = [f"T{i:02d}" for i in range(n)]
    selected = [
        {
            "ticker": t,
            "adj_score": rng.uniform(0.05, 5.0),         # greedy base-shifts > 0
            "composite_score": rng.uniform(-1.0, 1.0),
        }
        for t in tickers
    ]
    vols = {t: rng.uniform(0.05, 0.6) for t in tickers}  # realistic per-name vol
    cov = pd.DataFrame(
        {a: {b: (vols[a] ** 2 if a == b else 0.3 * vols[a] * vols[b]) for b in tickers}
         for a in tickers}
    )
    return tickers, selected, cov


def test_weights_sum_to_one_under_fuzz():
    rng = random.Random(7)
    bad = []
    for _ in range(2000):
        n = rng.randint(1, 40)
        tickers, selected, cov = _make(n, rng)
        method = rng.choice(METHODS)
        mpw = rng.choice([1.0, 0.5, 0.25, 0.15, 0.10, 0.05, 1.0 / n, 2.0 / n])
        w = compute_weights(selected, cov, method, max_position_weight=mpw)
        s = sum(w.values())
        feasible = n * mpw >= 1.0 - 1e-9
        # contract: weights always sum to 1.0
        if abs(s - 1.0) > 5e-5:
            bad.append((method, n, round(mpw, 4), round(s, 6), feasible))
        for t, v in w.items():
            assert math.isfinite(v), f"non-finite weight {t}={v}"
            assert v >= -1e-9, f"negative weight {t}={v}"
            if feasible:
                assert v <= mpw + 1e-6, f"{method} n={n} cap {mpw} breached: {t}={v}"
    assert not bad, f"gross sum-drift (>5e-5) in {len(bad)} cases, e.g. {bad[:8]}"


def test_infeasible_cap_when_fewer_selected_than_max_positions():
    """Concrete production path: only 5 names qualify but max_position_weight=0.10
    (valid for max_positions=30). 5×0.10 = 0.5 < 1 → the book should still be fully
    invested (weights sum to 1), not leave 50% idle."""
    rng = random.Random(1)
    _, selected, cov = _make(5, rng)
    w = compute_weights(selected, cov, "equal_weight", max_position_weight=0.10)
    assert abs(sum(w.values()) - 1.0) < 5e-5, f"under-invested: sum={sum(w.values()):.4f}, w={w}"


# ── greedy_select fuzz ────────────────────────────────────────────────────────

from app.select import greedy_select  # noqa: E402


def _psd_cov(tickers, rng):
    k = len(tickers)
    vols = np.array([rng.uniform(0.05, 0.6) for _ in tickers])
    C = np.full((k, k), 0.0)
    for i in range(k):
        for j in range(k):
            C[i, j] = 1.0 if i == j else rng.uniform(-0.1, 0.4)
    C = (C + C.T) / 2
    np.fill_diagonal(C, 1.0)
    cov = (np.outer(vols, vols) * C)
    return pd.DataFrame(cov, index=tickers, columns=tickers)


def test_greedy_select_fuzz():
    rng = random.Random(101)
    for _ in range(300):
        n = rng.randint(1, 18)
        tickers = [f"G{i:02d}" for i in range(n)]
        scores = pd.Series({t: rng.uniform(-3, 3) for t in tickers})
        cov = _psd_cov(tickers, rng)
        target = rng.randint(1, 20)
        sectors = ["tech", "fin", "energy", "health"]
        sector_map = {t: rng.choice(sectors) for t in tickers} if rng.random() < 0.6 else None
        msw = rng.choice([1.0, 0.5, 0.34, 0.25]) if sector_map else 1.0
        holdings = set(rng.sample(tickers, k=rng.randint(0, n))) if rng.random() < 0.5 else None
        tpen = rng.choice([0.0, 0.05, 0.2]) if holdings else 0.0

        res = greedy_select(scores, cov, target=target, sector_map=sector_map,
                            max_sector_weight=msw, current_holdings=holdings, turnover_penalty=tpen)

        assert len(res) <= target, f"selected {len(res)} > target {target}"
        seen_t = [d["ticker"] for d in res]
        assert len(seen_t) == len(set(seen_t)), "duplicate ticker selected"
        assert set(seen_t) <= set(tickers), "selected a ticker not in input"
        assert [d["position"] for d in res] == list(range(1, len(res) + 1)), "position not contiguous"
        for d in res:
            assert math.isfinite(d["adj_score"]) and d["adj_score"] > 0, d
            assert math.isfinite(d["composite_score"])
            assert math.isfinite(d["portfolio_vol_at_add"]) and d["portfolio_vol_at_add"] > 0
        # count-based sector cap (the hard constraint enforced during selection)
        if sector_map is not None and msw < 1.0:
            counts = {}
            for d in res:
                s = sector_map[d["ticker"]]
                counts[s] = counts.get(s, 0) + 1
            for s, c in counts.items():
                assert c <= math.floor(target * msw) + 1e-9 or c == 1, f"sector {s} count {c} > cap {target*msw}"
