import pandas as pd
from stock_strategy_shared.schemas.strategy import StrategyConfig

FACTORS = ["momentum", "quality", "value", "growth", "low_volatility", "liquidity"]


def rank_universe(
    factor_scores: pd.DataFrame,
    regime: str,
    strategy: StrategyConfig,
) -> pd.DataFrame:
    regime_weights: dict[str, float] = strategy.factor_weights[regime].model_dump()

    df = factor_scores.copy()

    min_factors = strategy.min_non_null_factors
    required = set(strategy.required_factors)

    def compute_score(row: pd.Series) -> float:
        available = {f: regime_weights[f] for f in FACTORS if pd.notna(row.get(f))}
        if len(available) < min_factors:
            return float("nan")
        if any(pd.isna(row.get(f)) for f in required):
            return float("nan")
        weight_sum = sum(available.values())
        if weight_sum == 0:
            return float("nan")
        return sum((w / weight_sum) * row[f] for f, w in available.items())

    df["composite_score"] = df.apply(compute_score, axis=1)

    # Only rank tickers with a valid composite score; drop unrankable rows entirely
    df_ranked = df[df["composite_score"].notna()].sort_values(
        "composite_score", ascending=False
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
