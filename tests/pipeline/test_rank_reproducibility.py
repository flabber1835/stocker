"""P1b: rank_universe is reproducible and ties break deterministically (CLAUDE.md
"rankings are reproducible"). Guards the P1a fix — a regression to an unstable sort
with no secondary key would make equal-composite tickers reorder run-to-run.
"""
import os

import pandas as pd

from app.rank import rank_universe, FACTORS
from stock_strategy_shared.loader import load_strategy

_STRAT, _ = load_strategy(os.path.join(os.path.dirname(__file__), "..", "..",
                                       "strategies", "quality_core_v1.yaml"))
_REGIME = "bull_calm"


def _frame(rows):
    """rows: list of (ticker, {factor: value}). Missing factors default to 0.5."""
    recs = []
    for tk, fv in rows:
        rec = {f: 0.5 for f in FACTORS}
        rec.update(fv)
        rec["ticker"] = tk
        recs.append(rec)
    return pd.DataFrame(recs)


def test_identical_inputs_give_identical_ranking():
    # Three names with DISTINCT composites + two with IDENTICAL factor vectors (a tie).
    df = _frame([
        ("AAA", {f: 0.9 for f in FACTORS}),
        ("BBB", {f: 0.1 for f in FACTORS}),
        ("TIE2", {f: 0.5 for f in FACTORS}),
        ("TIE1", {f: 0.5 for f in FACTORS}),
        ("CCC", {f: 0.7 for f in FACTORS}),
    ])
    out1 = rank_universe(df.copy(), _REGIME, _STRAT)
    out2 = rank_universe(df.sample(frac=1, random_state=3).reset_index(drop=True),
                         _REGIME, _STRAT)  # shuffled input order
    # Same ticker→rank mapping regardless of input row order.
    m1 = dict(zip(out1["ticker"], out1["rank"]))
    m2 = dict(zip(out2["ticker"], out2["rank"]))
    assert m1 == m2, f"ranking not reproducible across input order: {m1} vs {m2}"


def test_ties_break_on_ticker_ascending():
    df = _frame([
        ("ZZZ", {f: 0.5 for f in FACTORS}),
        ("AAA", {f: 0.5 for f in FACTORS}),
        ("MMM", {f: 0.5 for f in FACTORS}),
    ])
    out = rank_universe(df, _REGIME, _STRAT)
    # All composites equal → order must be alphabetical by ticker (the secondary key).
    assert list(out.sort_values("rank")["ticker"]) == ["AAA", "MMM", "ZZZ"]


def test_run_twice_byte_identical():
    df = _frame([(f"T{i:03d}", {f: (i % 7) / 7.0 for f in FACTORS}) for i in range(40)])
    a = rank_universe(df.copy(), _REGIME, _STRAT).reset_index(drop=True)
    b = rank_universe(df.copy(), _REGIME, _STRAT).reset_index(drop=True)
    pd.testing.assert_frame_equal(a, b)
