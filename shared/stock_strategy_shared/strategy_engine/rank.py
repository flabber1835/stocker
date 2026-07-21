import pandas as pd
from stock_strategy_shared.schemas.strategy import StrategyConfig
from stock_strategy_shared.factor_registry import FACTOR_NAMES

# Single source of truth — shared/factor_registry.py. list() preserves the prior
# mutable-list type for any caller that relied on it.
FACTORS = list(FACTOR_NAMES)


def composite_scores(
    factor_scores: pd.DataFrame,
    weights: dict[str, float],
    min_factors: int,
    required: set[str],
) -> pd.Series:
    """Vectorized composite score — same semantics as the original row-wise
    df.apply version (kept verbatim in tests/shared/test_rank_vectorized.py as
    the equivalence oracle), ~2 orders of magnitude faster on a full universe:

      - a factor is AVAILABLE when its value is non-null (weight-0 factors still
        count toward the min_factors availability threshold, as before)
      - score = Σ (w_f / Σ available weights) · value_f over available factors
      - NaN when: fewer than min_factors available, any required factor is
        null/absent, or the available weights sum to exactly 0
      - a factor column absent from the frame behaves as all-null (row.get)

    Renormalized per row over the non-null factors, so a null factor is inert
    rather than zero-scored. Per-term division (w/Σw)·v matches the row-wise
    arithmetic shape; residual float differences are ≤ ~1e-15 (pairwise vs
    sequential summation), asserted in the equivalence test.
    """
    # Missing columns → all-NaN (mirrors row.get); junk coerces to NaN.
    vals = factor_scores.reindex(columns=FACTORS).apply(pd.to_numeric, errors="coerce")
    avail = vals.notna()
    w = pd.Series({f: float(weights[f]) for f in FACTORS}, index=FACTORS)
    avail_w = avail.mul(w, axis=1)                       # weight where available, else 0
    weight_sum = avail_w.sum(axis=1)
    # ws==0 → NaN divisor → NaN row (also masked explicitly below); no inf paths.
    norm_w = avail_w.div(weight_sum.where(weight_sum != 0), axis=0)
    score = norm_w.mul(vals.fillna(0.0)).sum(axis=1)

    invalid = (avail.sum(axis=1) < min_factors) | (weight_sum == 0)
    if required:
        req_vals = factor_scores.reindex(columns=sorted(required))
        invalid |= req_vals.isna().any(axis=1)
    return score.mask(invalid)


def rank_universe(
    factor_scores: pd.DataFrame,
    regime: str,
    strategy: StrategyConfig,
) -> pd.DataFrame:
    regime_weights: dict[str, float] = strategy.effective_factor_weights(regime).model_dump()

    df = factor_scores.copy()

    df["composite_score"] = composite_scores(
        df, regime_weights,
        min_factors=strategy.min_non_null_factors,
        required=set(strategy.required_factors),
    )

    # Only rank tickers with a valid composite score; drop unrankable rows entirely.
    # P1a determinism: break composite-score TIES on ticker (ascending) with a STABLE
    # sort. The default quicksort is unstable and has no secondary key, so two tickers
    # with equal composite scores — realistic when inputs are percentiles/z-scores —
    # got a nondeterministic relative rank → a different top-N → a different vetter
    # pool / portfolio across otherwise-identical runs. "rankings are reproducible"
    # (CLAUDE.md) requires a fully-specified, repeatable order.
    df_ranked = df[df["composite_score"].notna()].sort_values(
        ["composite_score", "ticker"], ascending=[False, True], kind="mergesort"
    ).reset_index(drop=True)
    df_ranked["rank"] = range(1, len(df_ranked) + 1)

    total = len(df_ranked)
    if total > 1:
        df_ranked["percentile"] = 1.0 - (df_ranked["rank"] - 1) / (total - 1)
    else:
        df_ranked["percentile"] = 1.0

    min_pct = strategy.min_score_percentile
    if min_pct > 0:
        df_ranked = df_ranked[df_ranked["percentile"] >= min_pct].reset_index(drop=True)
        df_ranked["rank"] = range(1, len(df_ranked) + 1)
        n_filtered = len(df_ranked)
        if n_filtered > 1:
            df_ranked["percentile"] = 1.0 - (df_ranked["rank"] - 1) / (n_filtered - 1)
        elif n_filtered == 1:
            df_ranked["percentile"] = 1.0

    cols = ["ticker", "rank", "composite_score", "percentile"] + FACTORS
    return df_ranked[[c for c in cols if c in df_ranked.columns]]
