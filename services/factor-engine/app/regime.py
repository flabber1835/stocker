import pandas as pd


def detect_regime(spy_prices: pd.DataFrame) -> dict:
    if len(spy_prices) < 200:
        raise ValueError(f"Need at least 200 rows of SPY prices, got {len(spy_prices)}")

    prices = spy_prices.sort_values("date").reset_index(drop=True)
    adj = prices["adjusted_close"].astype(float)

    spy_price = adj.iloc[-1]
    spy_sma_50 = adj.iloc[-50:].mean()
    spy_sma_200 = adj.iloc[-200:].mean()
    spy_vs_sma200 = (spy_price / spy_sma_200) - 1.0

    if spy_price < spy_sma_200:
        regime = "bear"
    elif spy_price > spy_sma_50:
        regime = "bull"
    else:
        regime = "neutral"

    return {
        "regime": regime,
        "spy_price": float(spy_price),
        "spy_sma_50": float(spy_sma_50),
        "spy_sma_200": float(spy_sma_200),
        "spy_vs_sma200": float(spy_vs_sma200),
    }
