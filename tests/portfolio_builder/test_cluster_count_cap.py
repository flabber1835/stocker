"""Exhaustive tests for the correlation-cluster COUNT cap (max_tickers_per_cluster).

Complements the existing weight cap (max_cluster_weight / max_sector_weight). The
count cap is enforced in greedy_select: once a cluster has N members selected,
further candidates from it are skipped — an absolute count, independent of the
weighting scheme and `target` (unlike the weight cap's count/target proxy). Both
caps apply; whichever binds first wins.

Coverage:
  - basic N cap (no cluster exceeds N)
  - N=1 (one per cluster, max diversification)
  - None disables (unbounded)
  - singletons unaffected
  - count cap binds tighter than weight cap, and vice-versa
  - count cap applies even when the weight cap is disabled (max_sector_weight=1.0)
  - the FIRST pick is also gated
  - portfolio under-fills when clusters * N < target (no infinite loop, no dupes)
  - backward-compat: weight-only behavior unchanged when count cap is None
  - property/fuzz: random clusters, the invariant always holds
  - config: schema field + active yaml = 3
"""
import numpy as np
import pandas as pd
import pytest

from app.select import greedy_select


# ── helpers ───────────────────────────────────────────────────────────────────

def _diag_cov(tickers, vol=0.20):
    """Diagonal (zero-correlation) covariance so vol never reorders selection —
    isolates the cap logic from the score/vol ranking."""
    var = vol ** 2
    mat = np.zeros((len(tickers), len(tickers)))
    np.fill_diagonal(mat, var)
    return pd.DataFrame(mat, index=tickers, columns=tickers)


def _scores(tickers):
    # strictly decreasing scores so selection order == ticker order (deterministic)
    return pd.Series({t: float(len(tickers) - i) for i, t in enumerate(tickers)})


def _cluster_counts(result, cmap):
    counts = {}
    for s in result:
        c = cmap.get(s["ticker"])
        counts[c] = counts.get(c, 0) + 1
    return counts


# ── basic count cap ───────────────────────────────────────────────────────────

def test_no_cluster_exceeds_n():
    # cluster A has 6 members, B has 6; cap at 3 each.
    tickers = [f"A{i}" for i in range(6)] + [f"B{i}" for i in range(6)]
    cmap = {t: ("A" if t.startswith("A") else "B") for t in tickers}
    res = greedy_select(_scores(tickers), _diag_cov(tickers), target=12,
                        sector_map=cmap, max_sector_weight=1.0,
                        max_tickers_per_sector=3)
    counts = _cluster_counts(res, cmap)
    assert counts.get("A", 0) == 3 and counts.get("B", 0) == 3
    assert all(v <= 3 for v in counts.values())
    assert len(res) == 6  # 3+3, can't exceed the caps even though target=12


def test_cap_picks_the_best_n_of_each_cluster():
    # strictly decreasing scores → the 3 kept from A must be A0,A1,A2 (top scores)
    tickers = [f"A{i}" for i in range(6)]
    cmap = {t: "A" for t in tickers}
    res = greedy_select(_scores(tickers), _diag_cov(tickers), target=10,
                        sector_map=cmap, max_sector_weight=1.0,
                        max_tickers_per_sector=3)
    kept = {s["ticker"] for s in res}
    assert kept == {"A0", "A1", "A2"}


# ── N = 1 (one per cluster) ───────────────────────────────────────────────────

def test_one_per_cluster():
    tickers = [f"A{i}" for i in range(4)] + [f"B{i}" for i in range(4)] + ["C0"]
    cmap = {t: t[0] for t in tickers}
    res = greedy_select(_scores(tickers), _diag_cov(tickers), target=10,
                        sector_map=cmap, max_sector_weight=1.0,
                        max_tickers_per_sector=1)
    counts = _cluster_counts(res, cmap)
    assert counts == {"A": 1, "B": 1, "C": 1}
    assert {s["ticker"] for s in res} == {"A0", "B0", "C0"}  # best of each


# ── None disables ─────────────────────────────────────────────────────────────

def test_none_disables_count_cap():
    tickers = [f"A{i}" for i in range(8)]
    cmap = {t: "A" for t in tickers}
    res = greedy_select(_scores(tickers), _diag_cov(tickers), target=5,
                        sector_map=cmap, max_sector_weight=1.0,
                        max_tickers_per_sector=None)
    # no cap → fills to target from the single cluster
    assert len(res) == 5
    assert _cluster_counts(res, cmap)["A"] == 5


# ── singletons unaffected ─────────────────────────────────────────────────────

def test_singletons_unaffected():
    # 5 distinct single-member clusters + one 4-member cluster, cap 2
    tickers = ["S0", "S1", "S2", "S3", "S4"] + [f"A{i}" for i in range(4)]
    cmap = {**{s: s for s in ["S0", "S1", "S2", "S3", "S4"]},
            **{f"A{i}": "A" for i in range(4)}}
    res = greedy_select(_scores(tickers), _diag_cov(tickers), target=12,
                        sector_map=cmap, max_sector_weight=1.0,
                        max_tickers_per_sector=2)
    counts = _cluster_counts(res, cmap)
    assert counts["A"] == 2                      # multi-member thinned to 2
    assert all(counts[s] == 1 for s in ["S0", "S1", "S2", "S3", "S4"])  # singletons kept
    assert len(res) == 7                         # 5 singletons + 2 from A


# ── interaction with the weight cap ───────────────────────────────────────────

def test_count_cap_binds_tighter_than_weight_cap():
    # weight cap 0.15 * target 30 = 4.5 → ~4 allowed; count cap 2 is tighter → 2 wins
    tickers = [f"A{i}" for i in range(6)] + [f"D{i}" for i in range(30)]
    cmap = {**{f"A{i}": "A" for i in range(6)},
            **{f"D{i}": f"D{i}" for i in range(30)}}  # D's are singletons
    res = greedy_select(_scores(tickers), _diag_cov(tickers), target=30,
                        sector_map=cmap, max_sector_weight=0.15,
                        max_tickers_per_sector=2)
    assert _cluster_counts(res, cmap)["A"] == 2


def test_weight_cap_binds_tighter_than_count_cap():
    # weight cap 0.10 * target 30 = 3 allowed; count cap 5 is looser → weight wins (3)
    tickers = [f"A{i}" for i in range(6)] + [f"D{i}" for i in range(30)]
    cmap = {**{f"A{i}": "A" for i in range(6)},
            **{f"D{i}": f"D{i}" for i in range(30)}}
    res = greedy_select(_scores(tickers), _diag_cov(tickers), target=30,
                        sector_map=cmap, max_sector_weight=0.10,
                        max_tickers_per_sector=5)
    assert _cluster_counts(res, cmap)["A"] == 3


def test_count_cap_applies_with_weight_cap_disabled():
    # max_sector_weight=1.0 (disabled) but count cap still enforced
    tickers = [f"A{i}" for i in range(6)]
    cmap = {t: "A" for t in tickers}
    res = greedy_select(_scores(tickers), _diag_cov(tickers), target=6,
                        sector_map=cmap, max_sector_weight=1.0,
                        max_tickers_per_sector=2)
    assert _cluster_counts(res, cmap)["A"] == 2


# ── first-pick gating + under-fill ────────────────────────────────────────────

def test_underfill_when_clusters_times_n_below_target():
    # 2 clusters, cap 1 → at most 2 names even though target=10. No dupes, no hang.
    tickers = [f"A{i}" for i in range(5)] + [f"B{i}" for i in range(5)]
    cmap = {t: t[0] for t in tickers}
    res = greedy_select(_scores(tickers), _diag_cov(tickers), target=10,
                        sector_map=cmap, max_sector_weight=1.0,
                        max_tickers_per_sector=1)
    assert len(res) == 2
    assert len({s["ticker"] for s in res}) == 2   # no duplicates


def test_positions_are_sequential_and_unique_under_cap():
    tickers = [f"A{i}" for i in range(4)] + [f"B{i}" for i in range(4)]
    cmap = {t: t[0] for t in tickers}
    res = greedy_select(_scores(tickers), _diag_cov(tickers), target=8,
                        sector_map=cmap, max_sector_weight=1.0,
                        max_tickers_per_sector=2)
    positions = [s["position"] for s in res]
    assert positions == list(range(1, len(res) + 1))
    assert len({s["ticker"] for s in res}) == len(res)


# ── backward compatibility ────────────────────────────────────────────────────

def test_weight_only_behavior_unchanged_when_count_cap_none():
    # Mirror the old weight-proxy: max_sector_weight 0.30, target 10 → ceil 3 per sector.
    tickers = [f"A{i}" for i in range(6)] + [f"B{i}" for i in range(6)]
    cmap = {t: t[0] for t in tickers}
    res = greedy_select(_scores(tickers), _diag_cov(tickers), target=10,
                        sector_map=cmap, max_sector_weight=0.30,
                        max_tickers_per_sector=None)
    counts = _cluster_counts(res, cmap)
    # 0.30 * 10 = 3.0 → (count/10) <= 0.30 allows exactly 3
    assert counts["A"] == 3 and counts["B"] == 3


def test_no_sector_map_count_cap_is_noop():
    tickers = [f"X{i}" for i in range(5)]
    res = greedy_select(_scores(tickers), _diag_cov(tickers), target=5,
                        sector_map=None, max_tickers_per_sector=1)
    assert len(res) == 5   # no grouping → cap can't apply


# ── property / fuzz ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("seed", range(15))
def test_property_no_cluster_exceeds_cap(seed):
    rng = np.random.default_rng(seed)
    n = int(rng.integers(12, 40))
    n_clusters = int(rng.integers(2, 8))
    tickers = [f"T{i}" for i in range(n)]
    cmap = {t: f"C{int(rng.integers(0, n_clusters))}" for t in tickers}
    cap = int(rng.integers(1, 4))
    target = int(rng.integers(5, n + 5))
    res = greedy_select(_scores(tickers), _diag_cov(tickers), target=target,
                        sector_map=cmap, max_sector_weight=1.0,
                        max_tickers_per_sector=cap)
    counts = _cluster_counts(res, cmap)
    assert all(v <= cap for v in counts.values()), (seed, cap, counts)
    assert len({s["ticker"] for s in res}) == len(res)   # never duplicates
    assert len(res) <= target


# ── config wiring ─────────────────────────────────────────────────────────────

def test_config_field_present_and_validates():
    from stock_strategy_shared.schemas.strategy import PortfolioBuilderConfig
    c = PortfolioBuilderConfig(max_tickers_per_cluster=3)
    assert c.max_tickers_per_cluster == 3
    # default is None (disabled)
    assert PortfolioBuilderConfig().max_tickers_per_cluster is None
    # ge=1 enforced
    with pytest.raises(Exception):
        PortfolioBuilderConfig(max_tickers_per_cluster=0)


def test_active_strategy_sets_cap_to_3():
    import yaml
    from pathlib import Path
    root = Path(__file__).resolve().parents[2]
    cfg = yaml.safe_load((root / "strategies" / "quality_core_v1.yaml").read_text())
    assert cfg["portfolio_builder"]["max_tickers_per_cluster"] == 3
