"""Per-ticker ROE fallback in the quality factor (the PBR incident).

quality_use_gross_profitability=true computes profitability = gross_profit /
total_assets. A vendor blip nulled ONE ticker's total_assets while its ROE was
present in the same row; the old fallback was population-level (only fired when
the WHOLE universe had no GPA), so that ticker's quality went null, the
required_factors gate ejected it, and — because it was held — the orphan-exit
countdown started. The fallback is now per-ticker: GPA percentile where
available, ROE percentile where not.
"""
import pandas as pd

from app.factors import compute_quality


def _fund(rows):
    return pd.DataFrame(rows)


def test_ticker_with_null_total_assets_falls_back_to_roe():
    fund = _fund([
        # healthy universe: GPA computable
        {"ticker": "AAA", "gross_profit": 50.0, "total_assets": 100.0, "roe": 0.10, "debt_to_equity": 1.0},
        {"ticker": "BBB", "gross_profit": 20.0, "total_assets": 100.0, "roe": 0.05, "debt_to_equity": 2.0},
        {"ticker": "CCC", "gross_profit": 80.0, "total_assets": 100.0, "roe": 0.20, "debt_to_equity": 0.5},
        # the PBR case: total_assets nulled by a vendor blip, ROE present, D/E null
        {"ticker": "PBR", "gross_profit": 235.0, "total_assets": None, "roe": 0.256, "debt_to_equity": None},
    ])
    q = compute_quality(fund, use_gross_profitability=True)
    # Before the fix this was NaN -> required_factors ejection. ROE 0.256 is the
    # best in the ROE population, so PBR's quality must be present and strong.
    assert pd.notna(q["PBR"]), "quality must survive a single-ticker GPA input gap via ROE"
    assert q["PBR"] > 0.5
    # healthy tickers still scored
    assert q.drop("PBR").notna().all()


def test_population_level_fallback_still_works():
    # No ticker has GPA inputs at all -> whole leg falls back to ROE (old behavior).
    fund = _fund([
        {"ticker": "AAA", "roe": 0.10, "debt_to_equity": 1.0},
        {"ticker": "BBB", "roe": 0.30, "debt_to_equity": 0.5},
        {"ticker": "CCC", "roe": 0.05, "debt_to_equity": 2.0},
    ])
    q = compute_quality(fund, use_gross_profitability=True)
    assert q.notna().all()
    assert q["BBB"] > q["CCC"]  # best ROE + best D/E outranks worst


def test_flag_off_uses_roe_only_unchanged():
    fund = _fund([
        {"ticker": "AAA", "gross_profit": 50.0, "total_assets": 100.0, "roe": 0.10, "debt_to_equity": 1.0},
        {"ticker": "BBB", "gross_profit": 90.0, "total_assets": 100.0, "roe": 0.02, "debt_to_equity": 1.0},
    ])
    q = compute_quality(fund, use_gross_profitability=False)
    # flag off -> profitability is ROE, so AAA (higher ROE) wins despite worse GPA
    assert q["AAA"] > q["BBB"]


def test_gpa_ticker_not_polluted_by_roe_scale():
    # Tickers WITH GPA keep their GPA percentile — ROE only fills gaps.
    fund = _fund([
        {"ticker": "HIGHGPA", "gross_profit": 90.0, "total_assets": 100.0, "roe": 0.01, "debt_to_equity": 1.0},
        {"ticker": "LOWGPA",  "gross_profit": 10.0, "total_assets": 100.0, "roe": 0.99, "debt_to_equity": 1.0},
        {"ticker": "GAP",     "gross_profit": 50.0, "total_assets": None,  "roe": 0.50, "debt_to_equity": 1.0},
    ])
    q = compute_quality(fund, use_gross_profitability=True)
    # HIGHGPA's terrible ROE must not drag it below LOWGPA: GPA ordering rules
    # for the tickers that have it.
    assert q["HIGHGPA"] > q["LOWGPA"]
    assert pd.notna(q["GAP"])
