"""Tests for greedy_select's selection_vol_aversion exponent — the knob that moves
the greedy loop from vol-minimising (1.0, classic score-per-vol) to pure
score/momentum selection (0.0).
"""
import numpy as np
import pandas as pd

from app.select import greedy_select


def _cov(vols: dict, corr_pairs: dict | None = None):
    """Cov from per-name vols + optional pairwise correlations (default 0)."""
    tickers = list(vols)
    n = len(tickers)
    idx = {t: i for i, t in enumerate(tickers)}
    C = np.eye(n)
    for (a, b), c in (corr_pairs or {}).items():
        C[idx[a], idx[b]] = C[idx[b], idx[a]] = c
    v = np.array([vols[t] for t in tickers])
    cov = C * np.outer(v, v)
    return pd.DataFrame(cov, index=tickers, columns=tickers)


# Scenario: anchor X is always picked first (highest score). For the SECOND pick the
# loop chooses between HIGH (high score, high vol, correlated with X) and DIV (lower
# score, low vol, uncorrelated). Vol-aversion decides which.
SCORES = pd.Series({"X": 1.0, "HIGH": 0.9, "DIV": 0.6})
COV = _cov({"X": 0.2, "HIGH": 0.5, "DIV": 0.15}, {("X", "HIGH"): 0.9})


def test_high_aversion_picks_the_diversifier():
    sel = greedy_select(SCORES, COV, target=2, selection_vol_aversion=1.0)
    picks = [s["ticker"] for s in sel]
    assert picks[0] == "X"
    assert picks[1] == "DIV"  # classic score-per-vol favours the vol-reducer


def test_zero_aversion_picks_the_high_score_leader():
    sel = greedy_select(SCORES, COV, target=2, selection_vol_aversion=0.0)
    picks = [s["ticker"] for s in sel]
    assert picks[0] == "X"
    assert picks[1] == "HIGH"  # pure score: highest composite wins despite its vol


def test_default_matches_explicit_one():
    """Backward compatibility: omitting the param == selection_vol_aversion=1.0."""
    a = [s["ticker"] for s in greedy_select(SCORES, COV, target=2)]
    b = [s["ticker"] for s in greedy_select(SCORES, COV, target=2, selection_vol_aversion=1.0)]
    assert a == b == ["X", "DIV"]


def test_zero_aversion_selects_in_pure_score_order():
    """With the vol divisor gone, selection (after the score-ranked first pick) is
    driven purely by composite score — top-N by score, caps aside."""
    scores = pd.Series({"A": 0.95, "B": 0.80, "C": 0.65, "D": 0.50, "E": 0.35})
    # modest, mostly-uncorrelated vols so vol can't reorder under aversion=0
    cov = _cov({"A": 0.30, "B": 0.18, "C": 0.20, "D": 0.16, "E": 0.22})
    sel = greedy_select(scores, cov, target=3, selection_vol_aversion=0.0)
    assert [s["ticker"] for s in sel] == ["A", "B", "C"]


def test_intermediate_aversion_is_between():
    """0.3 should lean toward the leader here (verifies the exponent actually scales
    the penalty, not just the 0/1 endpoints)."""
    sel = [s["ticker"] for s in greedy_select(SCORES, COV, target=2, selection_vol_aversion=0.3)]
    assert sel[1] == "HIGH"  # partial penalty still lets the high-score name win


def test_caps_still_bind_under_zero_aversion():
    """Pure-score selection must still respect the cluster count cap."""
    scores = pd.Series({"A": 0.95, "B": 0.90, "C": 0.85, "D": 0.40})
    cov = _cov({"A": 0.2, "B": 0.2, "C": 0.2, "D": 0.2})
    # A, B, C all in one cluster "G"; D alone. Count cap = 1 per cluster.
    cluster = {"A": "G", "B": "G", "C": "G", "D": "D"}
    sel = [s["ticker"] for s in greedy_select(
        scores, cov, target=3, sector_map=cluster, max_tickers_per_sector=1,
        selection_vol_aversion=0.0,
    )]
    # only one of the G-cluster names + D may be chosen, despite all outscoring D
    g_picked = [t for t in sel if cluster[t] == "G"]
    assert len(g_picked) == 1
    assert "D" in sel
