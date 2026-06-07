"""Unit tests for the theme-classifier scoring (orthogonalized-sector method).

Guards the property the design depends on: stripping [SPY, generic_semi] keeps the
core AI names high while collapsing generic (non-AI) semis — without the over-strip
that raw [SPY, SOXX] caused."""
import numpy as np
import pandas as pd

from app.compute import AI_INFRA, score_exposures


def _panel(seed_subset):
    np.random.seed(7)
    n = 300
    idx = pd.date_range("2025-01-01", periods=n)
    spy_r = np.random.normal(0, 0.01, n)
    gen_r = np.random.normal(0, 0.008, n)   # generic-semi factor (non-AI)
    ai_r = np.random.normal(0, 0.01, n)     # AI-specific factor

    def px(lm, lg, la):
        r = lm * spy_r + lg * gen_r + la * ai_r + np.random.normal(0, 0.003, n)
        return 100 * (1 + pd.Series(r, index=idx)).cumprod()

    cols = {
        "SPY": 100 * (1 + pd.Series(spy_r, index=idx)).cumprod(),
        # SOXX is cap-weighted into AI semis: loads on market + generic + AI.
        "SOXX": 100 * (1 + pd.Series(1.0 * spy_r + 0.6 * gen_r + 0.9 * ai_r, index=idx)).cumprod(),
        "CRWV": px(1.0, 0.0, 0.9),   # non-seed AI adjacent (power/cloud): AI, no generic-semi
        "SWKS": px(1.0, 1.0, 0.0),   # generic semi: market + generic, NO AI
    }
    for s in seed_subset:
        cols[s] = px(1.0, 0.1, 1.0)  # seed pure-plays: strong AI, AI-pure (little generic-semi)
    return pd.DataFrame(cols)


def test_core_ai_kept_generic_semi_demoted():
    seed = AI_INFRA.seed
    panel = _panel(seed)
    liq = pd.Series({c: 5e8 for c in panel.columns})
    equities = set(panel.columns) - {"SPY", "SOXX"}
    res = score_exposures(panel, equities, liq, AI_INFRA)
    expo = res.set_index("ticker")["exposure"]

    # A core AI semi (seed) and a non-seed AI adjacent both score high.
    assert expo["NVDA"] > 0.6, expo["NVDA"]
    assert expo["CRWV"] > 0.6, expo["CRWV"]
    # The generic semi collapses well below the membership threshold.
    assert expo["SWKS"] < 0.35, expo["SWKS"]
    # And ranks below the real AI names.
    assert expo["NVDA"] > expo["SWKS"] and expo["CRWV"] > expo["SWKS"]


def test_falls_back_to_market_only_without_sector_etf():
    seed = AI_INFRA.seed
    panel = _panel(seed).drop(columns=["SOXX"])   # no sector factor available
    liq = pd.Series({c: 5e8 for c in panel.columns})
    equities = set(panel.columns) - {"SPY"}
    res = score_exposures(panel, equities, liq, AI_INFRA)
    # Still produces a ranking (market-only residualization) with seed names present.
    assert "NVDA" in set(res["ticker"])
    assert (res["exposure"] >= 0).all()
