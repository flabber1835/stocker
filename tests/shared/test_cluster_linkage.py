"""Single- vs complete-linkage correlation clustering.

The defect complete-linkage addresses is CHAINING. Under single-linkage A~B and
B~C put A, B and C in one cluster even when corr(A,C) is near zero — they co-move
*through* B. In a broad momentum book a run of such pairwise links can fuse most
of the market into one mega-cluster, and `max_tickers_per_cluster` then blocks
names that are not correlated with each other at all.

The default is NOT changed, deliberately: single-linkage produced every existing
result, and tightening the cap under it has already been measured as costly
(~26.1% -> 18.1% CAGR with no drawdown improvement). Complete-linkage exists so
the wind tunnel can score the alternative instead of the question being argued.
"""
from __future__ import annotations

import pandas as pd
import pytest

from stock_strategy_shared.strategy_engine.select import correlation_clusters


def _corr(pairs: dict[tuple[str, str], float], tickers: list[str]) -> pd.DataFrame:
    m = pd.DataFrame(0.0, index=tickers, columns=tickers)
    for t in tickers:
        m.loc[t, t] = 1.0
    for (a, b), v in pairs.items():
        m.loc[a, b] = v
        m.loc[b, a] = v
    return m


class TestTheChainingDefect:
    """A~B and B~C both clear the bar; A~C does not."""

    CHAIN = _corr({("A", "B"): 0.85, ("B", "C"): 0.85, ("A", "C"): 0.05},
                  ["A", "B", "C"])

    def test_single_linkage_fuses_the_chain(self):
        out = correlation_clusters(self.CHAIN, threshold=0.7, method="single")
        assert len(set(out.values())) == 1, "single-linkage should chain A-B-C"

    def test_complete_linkage_refuses_to(self):
        """C is uncorrelated with A, so a cluster containing both would make the
        count cap block two names that have nothing to do with each other."""
        out = correlation_clusters(self.CHAIN, threshold=0.7, method="complete")
        assert out["A"] == out["B"], "A and B genuinely co-move"
        assert out["C"] != out["A"], "C should not be dragged in through B"


class TestDefaultIsUnchanged:
    def test_omitting_method_is_single_linkage(self):
        m = TestTheChainingDefect.CHAIN
        assert (correlation_clusters(m, threshold=0.7)
                == correlation_clusters(m, threshold=0.7, method="single"))

    def test_a_genuinely_correlated_block_clusters_the_same_either_way(self):
        """Where there is no chaining the two linkages must agree — otherwise
        'complete' would be changing more than the thing it was introduced for."""
        m = _corr({("A", "B"): 0.9, ("B", "C"): 0.9, ("A", "C"): 0.9},
                  ["A", "B", "C", "D"])
        assert (correlation_clusters(m, threshold=0.7, method="single")
                == correlation_clusters(m, threshold=0.7, method="complete"))


class TestSharedContract:
    """Both linkages must honour the invariants every consumer already relies on."""

    M = _corr({("B", "C"): 0.95, ("A", "B"): 0.1, ("A", "C"): 0.1},
              ["A", "B", "C", "D"])

    @pytest.mark.parametrize("method", ["single", "complete"])
    def test_cluster_id_is_the_smallest_member(self, method):
        out = correlation_clusters(self.M, threshold=0.7, method=method)
        assert out["B"] == "B" and out["C"] == "B"

    @pytest.mark.parametrize("method", ["single", "complete"])
    def test_every_ticker_is_mapped(self, method):
        out = correlation_clusters(self.M, threshold=0.7, method=method)
        assert set(out) == {"A", "B", "C", "D"}

    @pytest.mark.parametrize("method", ["single", "complete"])
    def test_a_lone_ticker_is_its_own_cluster(self, method):
        out = correlation_clusters(self.M, threshold=0.7, method=method)
        assert out["D"] == "D"

    @pytest.mark.parametrize("method", ["single", "complete"])
    def test_negative_correlation_counts_as_co_movement(self, method):
        """Absolute value: a -0.9 pair is one bet expressed two ways, and capping
        it as two independent names would understate concentration."""
        m = _corr({("A", "B"): -0.9}, ["A", "B"])
        out = correlation_clusters(m, threshold=0.7, method=method)
        assert out["A"] == out["B"]

    @pytest.mark.parametrize("method", ["single", "complete"])
    def test_it_is_deterministic(self, method):
        """Complete-linkage is greedy and therefore order-dependent by nature; it
        visits members in a fixed lexicographic order so the same matrix always
        yields the same map. This repo tests determinism directly elsewhere."""
        a = correlation_clusters(self.M, threshold=0.7, method=method)
        b = correlation_clusters(self.M.loc[["D", "C", "B", "A"], ["D", "C", "B", "A"]],
                                 threshold=0.7, method=method)
        assert a == b

    @pytest.mark.parametrize("method", ["single", "complete"])
    def test_an_empty_matrix_is_empty(self, method):
        assert correlation_clusters(pd.DataFrame(), threshold=0.7, method=method) == {}
