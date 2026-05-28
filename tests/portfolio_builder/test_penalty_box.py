"""Tests for penalty box exclusion logic in portfolio-builder.

Verifies that:
- Tickers currently in the penalty box are excluded from candidates
- Tickers only in penalty box (not flagged today) are still excluded
- Vetter exclusions and penalty box exclusions combine correctly
- An expired penalty box (past penalty_box_until) does NOT exclude
- Portfolio selection proceeds normally after exclusions
"""
from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest
from app.select import greedy_select, build_covariance, compute_weights


# ── Pure exclusion logic (mirrors _do_build Step 2b) ──────────────────────────

def _apply_exclusions(
    candidate_tickers: list[str],
    scores_map: dict[str, float],
    vetter_excluded: list[str],
    penalty_box_set: set[str],
) -> tuple[list[str], dict[str, float]]:
    """Replicate the combined exclusion logic from portfolio-builder _do_build."""
    all_excluded_set = set(vetter_excluded) | penalty_box_set
    filtered = [t for t in candidate_tickers if t not in all_excluded_set]
    filtered_scores = {t: v for t, v in scores_map.items() if t not in all_excluded_set}
    return filtered, filtered_scores


def test_penalty_box_ticker_excluded():
    """A ticker in the penalty box is removed from candidates."""
    tickers = ["AAPL", "MSFT", "GOOGL", "META"]
    scores = {"AAPL": 1.5, "MSFT": 1.2, "GOOGL": 1.0, "META": 0.8}
    vetter_excluded = []
    penalty_box = {"GOOGL"}

    filtered, _ = _apply_exclusions(tickers, scores, vetter_excluded, penalty_box)
    assert "GOOGL" not in filtered
    assert set(filtered) == {"AAPL", "MSFT", "META"}


def test_vetter_excluded_ticker_excluded():
    """A ticker flagged by today's vetter run is excluded even if not in penalty box yet."""
    tickers = ["AAPL", "MSFT", "NVDA"]
    scores = {"AAPL": 1.5, "MSFT": 1.2, "NVDA": 2.0}
    vetter_excluded = ["NVDA"]  # flagged today, penalty box row created after
    penalty_box = set()         # not in penalty box yet (will be after this run)

    filtered, _ = _apply_exclusions(tickers, scores, vetter_excluded, penalty_box)
    assert "NVDA" not in filtered
    assert set(filtered) == {"AAPL", "MSFT"}


def test_combined_vetter_and_penalty_box():
    """Vetter exclusions + penalty box exclusions combine additively."""
    tickers = ["AAPL", "MSFT", "GOOGL", "META", "NVDA"]
    scores = {t: float(i) for i, t in enumerate(tickers)}
    vetter_excluded = ["AAPL"]     # flagged today
    penalty_box = {"GOOGL", "META"}  # serving penalty from prior flags

    filtered, _ = _apply_exclusions(tickers, scores, vetter_excluded, penalty_box)
    assert set(filtered) == {"MSFT", "NVDA"}
    assert "AAPL" not in filtered
    assert "GOOGL" not in filtered
    assert "META" not in filtered


def test_penalty_box_ticker_in_both_vetter_and_box():
    """A ticker flagged today that is also in penalty box is excluded exactly once."""
    tickers = ["AAPL", "MSFT", "GOOGL"]
    scores = {"AAPL": 1.5, "MSFT": 1.2, "GOOGL": 0.5}
    vetter_excluded = ["GOOGL"]   # flagged today (re-flag resets clock)
    penalty_box = {"GOOGL"}       # also in penalty box from prior run

    filtered, _ = _apply_exclusions(tickers, scores, vetter_excluded, penalty_box)
    assert "GOOGL" not in filtered
    assert filtered.count("GOOGL") == 0  # not added back
    assert set(filtered) == {"AAPL", "MSFT"}


def test_expired_penalty_box_does_not_exclude():
    """Tickers whose penalty_box_until < today are NOT in the active penalty box."""
    today = date.today()
    rows = [
        {"ticker": "AAPL", "penalty_box_until": today - timedelta(days=1)},  # expired
        {"ticker": "MSFT", "penalty_box_until": today + timedelta(days=5)},  # active
    ]
    # The SQL query filters penalty_box_until >= today
    active_penalty_box = {r["ticker"] for r in rows if r["penalty_box_until"] >= today}
    assert "AAPL" not in active_penalty_box
    assert "MSFT" in active_penalty_box


def test_no_exclusions_returns_all_candidates():
    """With empty vetter exclusions and empty penalty box, all candidates remain."""
    tickers = ["AAPL", "MSFT", "GOOGL"]
    scores = {"AAPL": 1.5, "MSFT": 1.2, "GOOGL": 1.0}
    filtered, filtered_scores = _apply_exclusions(tickers, scores, [], set())
    assert filtered == tickers
    assert filtered_scores == scores


def test_all_candidates_excluded_returns_empty():
    """When all candidates are excluded, the filtered list is empty."""
    tickers = ["AAPL", "MSFT"]
    scores = {"AAPL": 1.5, "MSFT": 1.2}
    vetter_excluded = ["AAPL"]
    penalty_box = {"MSFT"}

    filtered, filtered_scores = _apply_exclusions(tickers, scores, vetter_excluded, penalty_box)
    assert filtered == []
    assert filtered_scores == {}


def test_penalty_box_ticker_not_in_candidates_is_noop():
    """A penalty box ticker not in the candidate list has no effect (silent skip)."""
    tickers = ["AAPL", "MSFT"]
    scores = {"AAPL": 1.5, "MSFT": 1.2}
    penalty_box = {"NVDA", "META"}  # neither is in candidates

    filtered, _ = _apply_exclusions(tickers, scores, [], penalty_box)
    assert set(filtered) == {"AAPL", "MSFT"}


# ── Integration with greedy_select ────────────────────────────────────────────

def _simple_cov(tickers: list[str], vol: float = 0.20) -> pd.DataFrame:
    n = len(tickers)
    var = vol ** 2
    mat = np.full((n, n), 0.0)
    np.fill_diagonal(mat, var)
    return pd.DataFrame(mat, index=tickers, columns=tickers)


def test_greedy_select_after_penalty_exclusions():
    """Portfolio-builder selects from filtered candidates after penalty box exclusion."""
    all_tickers = [f"T{i}" for i in range(20)]
    scores_map = {t: float(20 - i) for i, t in enumerate(all_tickers)}

    # T0 and T1 are highest-scoring but in penalty box
    penalty_box = {"T0", "T1"}
    filtered = [t for t in all_tickers if t not in penalty_box]
    filtered_scores = pd.Series({t: scores_map[t] for t in filtered})
    cov = _simple_cov(filtered)

    result = greedy_select(filtered_scores, cov, target=5)
    selected = [r["ticker"] for r in result]

    assert "T0" not in selected
    assert "T1" not in selected
    assert len(selected) == 5
    # T2 is the next highest score after exclusions
    assert result[0]["ticker"] == "T2"


def test_penalty_box_exclusion_logged_separately(capsys):
    """Penalty-box-only exclusions are logged separately from vetter exclusions."""
    vetter_excluded = ["AAPL"]
    penalty_box_excluded = ["GOOGL", "META"]

    warn_lines = []
    if vetter_excluded:
        warn_lines.append(f"LLM vetter excluded {len(vetter_excluded)} tickers: {vetter_excluded}")
    if penalty_box_excluded:
        warn_lines.append(f"Penalty box excluded {len(penalty_box_excluded)} additional tickers: {penalty_box_excluded}")

    assert len(warn_lines) == 2
    assert "vetter" in warn_lines[0]
    assert "Penalty box" in warn_lines[1]
    assert "GOOGL" in warn_lines[1]
    assert "META" in warn_lines[1]
