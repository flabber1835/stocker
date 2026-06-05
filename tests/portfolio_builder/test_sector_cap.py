"""Tests for the independent AV-sector cap (second concentration dimension).

The correlation-cluster cap bounds correlated micro-groups, but a whole sector
spread across several clusters (e.g. energy = tankers + refiners + E&P) escapes
it. greedy_select(av_sector_map, max_av_sector_weight) and
compute_weights(av_sector_map, max_av_sector_weight) add a real per-sector cap
on the AV sector label, enforced independently of (and alongside) the cluster cap.
"""
import numpy as np
import pandas as pd
import pytest
from app.select import greedy_select, compute_weights


def _diag_cov(tickers, vol=0.20):
    var = vol ** 2
    mat = np.zeros((len(tickers), len(tickers)))
    np.fill_diagonal(mat, var)
    return pd.DataFrame(mat, index=tickers, columns=tickers)


# ── greedy_select: AV-sector count-proxy cap ──────────────────────────────────

def test_av_sector_cap_limits_selection_count():
    """10 energy names + 10 others, all uncorrelated (so the cluster cap never
    binds). With max_av_sector_weight=0.25 and target=20, energy is capped at
    floor(0.25*20)=5 names by the count proxy."""
    energy = [f"E{i}" for i in range(10)]
    other = [f"O{i}" for i in range(10)]
    tickers = energy + other
    # Energy scores highest so it would otherwise dominate.
    scores = pd.Series({t: (2.0 if t in energy else 1.0) for t in tickers})
    cov = _diag_cov(tickers)
    av_sector = {t: ("ENERGY" if t in energy else "OTHER") for t in tickers}

    sel = greedy_select(scores, cov, target=20, av_sector_map=av_sector, max_av_sector_weight=0.25)
    picked = [s["ticker"] for s in sel]
    n_energy = sum(1 for t in picked if t in energy)
    assert n_energy <= 5, f"energy not capped: {n_energy} picked"


def test_av_sector_cap_disabled_by_default():
    """No av_sector_map → behaves exactly as before (energy can sweep)."""
    energy = [f"E{i}" for i in range(10)]
    other = [f"O{i}" for i in range(10)]
    tickers = energy + other
    scores = pd.Series({t: (2.0 if t in energy else 1.0) for t in tickers})
    cov = _diag_cov(tickers)
    sel = greedy_select(scores, cov, target=10)
    picked = [s["ticker"] for s in sel]
    assert all(t in energy for t in picked)  # all 10 picks are the top-scoring energy


def test_av_sector_and_cluster_caps_both_apply():
    """Cluster cap and AV-sector cap are independent; both can block a pick."""
    tickers = [f"E{i}" for i in range(8)] + [f"O{i}" for i in range(8)]
    scores = pd.Series({t: 1.0 for t in tickers})
    cov = _diag_cov(tickers)
    clusters = {t: t for t in tickers}  # every name its own cluster (cluster cap inert)
    av_sector = {t: ("ENERGY" if t.startswith("E") else "OTHER") for t in tickers}
    sel = greedy_select(
        scores, cov, target=12,
        sector_map=clusters, max_sector_weight=1.0,        # cluster cap off
        av_sector_map=av_sector, max_av_sector_weight=0.25,  # sector cap on
    )
    picked = [s["ticker"] for s in sel]
    assert sum(1 for t in picked if t.startswith("E")) <= 3  # floor(0.25*12)=3


# ── compute_weights: AV-sector weight cap ─────────────────────────────────────

def _sel(tickers, adj):
    return [{"ticker": t, "composite_score": 1.0, "adj_score": adj[t],
             "portfolio_vol_at_add": 0.2} for t in tickers]


def test_av_sector_weight_cap_binds():
    """adj_score_proportional would give energy ~60% of weight; the 0.25 sector cap
    must pull it to ~25%. Other names sit in 4 distinct sectors so the 0.25 cap is
    feasible (4 x 0.25 = 1.0)."""
    energy = ["E0", "E1", "E2"]
    other = ["O0", "O1", "O2", "O3"]
    tickers = energy + other
    adj = {"E0": 6.0, "E1": 6.0, "E2": 6.0, "O0": 3.0, "O1": 3.0, "O2": 3.0, "O3": 3.0}
    cov = _diag_cov(tickers)
    other_sectors = {"O0": "TECH", "O1": "HEALTH", "O2": "FIN", "O3": "INDU"}
    av_sector = {**{t: "ENERGY" for t in energy}, **other_sectors}
    w = compute_weights(
        _sel(tickers, adj), cov, method="adj_score_proportional",
        max_position_weight=1.0,
        av_sector_map=av_sector, max_av_sector_weight=0.25,
    )
    energy_w = sum(w[t] for t in energy)
    assert energy_w == pytest.approx(0.25, abs=0.01), f"energy weight {energy_w:.3f} not capped to 0.25"
    assert sum(w.values()) == pytest.approx(1.0, abs=1e-6)


def test_both_weight_caps_satisfied_simultaneously():
    """A cluster cap and a sector cap together both hold after redistribution.
    Three non-energy sectors keep the 0.35 sector cap feasible."""
    tickers = ["E0", "E1", "O0", "O1", "O2"]
    adj = {"E0": 5.0, "E1": 5.0, "O0": 2.0, "O1": 2.0, "O2": 2.0}
    cov = _diag_cov(tickers)
    clusters = {"E0": "CL", "E1": "CL", "O0": "O0", "O1": "O1", "O2": "O2"}  # E0,E1 one cluster
    av_sector = {"E0": "ENERGY", "E1": "ENERGY", "O0": "TECH", "O1": "HEALTH", "O2": "FIN"}
    w = compute_weights(
        _sel(tickers, adj), cov, method="adj_score_proportional",
        max_position_weight=1.0,
        sector_map=clusters, max_sector_weight=0.30,        # cluster cap (E0,E1)
        av_sector_map=av_sector, max_av_sector_weight=0.35,  # sector cap (energy)
    )
    assert w["E0"] + w["E1"] <= 0.30 + 0.01      # cluster cap binds first (tighter)
    assert sum(w.values()) == pytest.approx(1.0, abs=1e-6)


def test_disabled_av_sector_cap_is_noop():
    """max_av_sector_weight=1.0 (default) leaves weights as the plain method output."""
    tickers = ["A", "B", "C", "D"]
    adj = {"A": 4.0, "B": 3.0, "C": 2.0, "D": 1.0}
    cov = _diag_cov(tickers)
    base = compute_weights(_sel(tickers, adj), cov, method="adj_score_proportional")
    with_map = compute_weights(
        _sel(tickers, adj), cov, method="adj_score_proportional",
        av_sector_map={t: "X" for t in tickers}, max_av_sector_weight=1.0,
    )
    assert base == with_map
