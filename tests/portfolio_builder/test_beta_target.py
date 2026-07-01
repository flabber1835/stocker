"""Unit / property / edge-case tests for the market-beta targeting overlay
(solve_beta_target_weights) — the deterministic risk-shaping tilt that reweights
the invested book toward a target portfolio beta (β = Σ wᵢβᵢ).

Pure-function tests (no DB). The overlay is default-OFF (beta_target_enabled) so
these exercise the solver directly; reversibility is guarded by the config default.
"""
import math

import pytest

from app.select import solve_beta_target_weights, compute_weights
from stock_strategy_shared.schemas.strategy import PortfolioBuilderConfig


def _book_beta(weights, betas):
    s = sum(weights.values())
    return sum(weights[t] * betas.get(t, 1.0) for t in weights) / s


# ── reversibility / config default ────────────────────────────────────────────

def test_beta_targeting_disabled_by_default():
    """The overlay must default OFF so existing configs behave exactly as before."""
    cfg = PortfolioBuilderConfig()
    assert cfg.beta_target_enabled is False
    assert cfg.beta_target == 1.3          # requested default target
    assert cfg.beta_tolerance == 0.10


# ── core targeting ────────────────────────────────────────────────────────────

def test_hits_target_within_feasible_range():
    # 5 equal-weight names with dispersed betas; base beta = mean = 1.0.
    betas = {"A": 0.5, "B": 0.8, "C": 1.0, "D": 1.2, "E": 1.5}
    base = {t: 0.2 for t in betas}
    assert _book_beta(base, betas) == pytest.approx(1.0, abs=1e-9)

    w, info = solve_beta_target_weights(base, betas, beta_target=1.3, max_position_weight=1.0)
    assert info["infeasible"] is False
    assert _book_beta(w, betas) == pytest.approx(1.3, abs=1e-3)
    assert sum(w.values()) == pytest.approx(1.0, abs=1e-9)
    # tilt moved weight toward the higher-beta names
    assert w["E"] > base["E"] and w["A"] < base["A"]


def test_lower_target_reduces_beta():
    betas = {"A": 0.5, "B": 0.8, "C": 1.0, "D": 1.2, "E": 1.5}
    base = {t: 0.2 for t in betas}
    w, info = solve_beta_target_weights(base, betas, beta_target=0.7, max_position_weight=1.0)
    assert info["infeasible"] is False
    assert _book_beta(w, betas) == pytest.approx(0.7, abs=1e-3)
    assert w["A"] > base["A"] and w["E"] < base["E"]


def test_target_equal_to_base_is_noop_ish():
    betas = {"A": 0.5, "B": 1.0, "C": 1.5}
    base = {t: 1 / 3 for t in betas}  # base beta 1.0
    w, info = solve_beta_target_weights(base, betas, beta_target=1.0, max_position_weight=1.0)
    assert info["infeasible"] is False
    assert _book_beta(w, betas) == pytest.approx(1.0, abs=1e-3)


# ── feasibility under the position cap ────────────────────────────────────────

def test_infeasible_target_flagged_and_clamped_to_closest():
    # Max book beta under a 0.10 cap: even all weight maxed on high-beta names can't
    # reach 2.5 when the top betas are ~1.5. Solver must flag infeasible and ship the
    # closest feasible (highest achievable) book, never breach the cap.
    betas = {f"T{i}": (0.8 + 0.05 * i) for i in range(20)}  # betas 0.8..1.75
    base = {t: 1 / 20 for t in betas}
    w, info = solve_beta_target_weights(base, betas, beta_target=2.5, max_position_weight=0.10)
    assert info["infeasible"] is True
    assert all(v <= 0.10 + 1e-9 for v in w.values())        # cap respected
    assert sum(w.values()) == pytest.approx(1.0, abs=1e-6)
    # got as close as the cap allows (well above base beta, below the impossible target)
    assert _book_beta(w, betas) > _book_beta(base, betas)
    assert _book_beta(w, betas) < 2.5


def test_no_dispersion_cannot_move_beta():
    # All betas identical → beta is invariant to reweighting → any off-base target
    # is infeasible; weights stay valid (sum 1, within cap).
    betas = {"A": 1.0, "B": 1.0, "C": 1.0}
    base = {t: 1 / 3 for t in betas}
    w, info = solve_beta_target_weights(base, betas, beta_target=1.4, max_position_weight=1.0)
    assert info["infeasible"] is True
    assert _book_beta(w, betas) == pytest.approx(1.0, abs=1e-6)


# ── missing beta imputation ───────────────────────────────────────────────────

def test_missing_beta_imputed_market():
    betas = {"A": 0.6, "B": 1.4}  # "C" has no beta → imputed 1.0
    base = {"A": 1 / 3, "B": 1 / 3, "C": 1 / 3}
    w, info = solve_beta_target_weights(base, betas, beta_target=1.2, max_position_weight=1.0)
    # achieved computed with the same 1.0 imputation for C
    ach = sum(w[t] * (betas.get(t, 1.0)) for t in w) / sum(w.values())
    assert ach == pytest.approx(1.2, abs=1e-3)
    assert info["infeasible"] is False


# ── determinism ───────────────────────────────────────────────────────────────

def test_deterministic():
    betas = {"A": 0.5, "B": 0.9, "C": 1.1, "D": 1.6}
    base = {t: 0.25 for t in betas}
    a, _ = solve_beta_target_weights(base, betas, 1.25, 0.5)
    b, _ = solve_beta_target_weights(base, betas, 1.25, 0.5)
    assert a == b


# ── overlay respects per-name cap even when solving ───────────────────────────

def test_solver_respects_position_cap():
    betas = {f"T{i}": (0.7 + 0.1 * i) for i in range(10)}  # 0.7..1.6
    base = {t: 0.1 for t in betas}
    w, info = solve_beta_target_weights(base, betas, beta_target=1.5, max_position_weight=0.15)
    assert all(v <= 0.15 + 1e-9 for v in w.values())
    assert sum(w.values()) == pytest.approx(1.0, abs=1e-6)
