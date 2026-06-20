"""FIX B — empty selection must not ZeroDivisionError.

compute_weights' equal_weight path does `1.0 / n` with n=len(selected); when
greedy_select returns [] (every candidate blocked by caps, or an empty pool),
n=0 → ZeroDivisionError, crashing the build. The guard converts this into a
controlled, catchable ValueError (no-feasible-portfolio) so the caller marks the
run failed/degraded with a clear diagnostic instead of crashing.
"""
import numpy as np
import pandas as pd
import pytest

from app.select import compute_weights, greedy_select


def _cov(tickers):
    n = len(tickers)
    var = 0.04
    mat = np.full((n, n), 0.0)
    np.fill_diagonal(mat, var)
    return pd.DataFrame(mat, index=tickers, columns=tickers)


def test_compute_weights_empty_raises_controlled_error():
    cov = _cov(["AAA"])  # cov content irrelevant; selection is empty
    with pytest.raises(ValueError) as ei:
        compute_weights([], cov, method="equal_weight")
    # Must be a clean, diagnostic ValueError — NOT a ZeroDivisionError.
    assert "empty selection" in str(ei.value).lower()


def test_compute_weights_empty_not_zero_division():
    cov = _cov(["AAA"])
    # Confirm specifically that we no longer raise ZeroDivisionError.
    with pytest.raises(ValueError):
        compute_weights([], cov, method="equal_weight")
    with pytest.raises(ValueError):
        compute_weights([], cov, method="inverse_vol")


def test_greedy_select_can_return_empty_and_is_safe_to_weight():
    # Force greedy_select to return [] by capping every cluster to 0 names.
    tickers = ["AAA", "BBB", "CCC"]
    scores = pd.Series({t: 1.0 for t in tickers})
    cov = _cov(tickers)
    cluster_map = {t: "C" for t in tickers}  # all one cluster
    selected = greedy_select(
        scores, cov, target=3,
        sector_map=cluster_map, max_sector_weight=1.0,
        max_tickers_per_sector=0,  # 0 names per cluster → nothing selectable
    )
    assert selected == []
    # And weighting the empty result is a controlled failure, not a crash.
    with pytest.raises(ValueError):
        compute_weights(selected, cov, method="equal_weight")
