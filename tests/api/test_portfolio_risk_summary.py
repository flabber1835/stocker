"""Target-tab risk summary: sleeve beta, effective (cash-inclusive) beta, cash %.

The displayed "sleeve β" excludes the cash buffer (beta of the holdings as if fully
invested). "Effective β" = sleeve β × invested fraction = the book's real market
sensitivity after the cash drag. Cash % = 1 − Σ target weights.
"""
from app.main import _portfolio_risk_summary


def _h(ticker, weight):
    return {"ticker": ticker, "weight": weight}


def test_sleeve_beta_excludes_cash_effective_includes_it():
    # 3 names at 20% each → 60% invested, 40% cash. Betas avg 1.0.
    holdings = [_h("A", 0.20), _h("B", 0.20), _h("C", 0.20)]
    beta_map = {"A": 0.8, "B": 1.0, "C": 1.2}
    r = _portfolio_risk_summary(holdings, beta_map)
    assert abs(r["sleeve_beta"] - 1.0) < 1e-9          # weight-weighted, normalized → 1.0
    assert abs(r["invested_fraction"] - 0.60) < 1e-9
    assert abs(r["cash_pct"] - 0.40) < 1e-9
    # effective = sleeve × invested = 1.0 × 0.60
    assert abs(r["effective_beta"] - 0.60) < 1e-9
    assert r["coverage"] == 3


def test_sleeve_beta_normalized_over_covered_only():
    # One name has no beta — it counts toward invested/cash but NOT the sleeve β avg.
    holdings = [_h("A", 0.30), _h("NOBETA", 0.30)]
    beta_map = {"A": 1.5}
    r = _portfolio_risk_summary(holdings, beta_map)
    assert abs(r["sleeve_beta"] - 1.5) < 1e-9          # only A, normalized
    assert r["coverage"] == 1
    assert abs(r["invested_fraction"] - 0.60) < 1e-9   # both names invested
    assert abs(r["cash_pct"] - 0.40) < 1e-9
    # effective uses the (covered) sleeve β × the FULL invested fraction
    assert abs(r["effective_beta"] - 1.5 * 0.60) < 1e-9


def test_fully_invested_effective_equals_sleeve():
    holdings = [_h("A", 0.5), _h("B", 0.5)]   # 100% invested
    beta_map = {"A": 1.0, "B": 1.0}
    r = _portfolio_risk_summary(holdings, beta_map)
    assert abs(r["cash_pct"] - 0.0) < 1e-9
    assert abs(r["effective_beta"] - r["sleeve_beta"]) < 1e-9


def test_cash_pct_never_negative_on_rounding_overshoot():
    holdings = [_h("A", 0.5), _h("B", 0.5001)]   # sums slightly > 1
    r = _portfolio_risk_summary(holdings, {"A": 1.0})
    assert r["cash_pct"] == 0.0                   # clamped, not negative


def test_empty_holdings_all_none():
    r = _portfolio_risk_summary([], {})
    assert r["sleeve_beta"] is None and r["effective_beta"] is None
    assert r["invested_fraction"] is None and r["cash_pct"] is None and r["coverage"] == 0
