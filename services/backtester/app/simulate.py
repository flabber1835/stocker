import pandas as pd
import numpy as np
from app.metrics import annualized_return, sharpe_ratio, max_drawdown, turnover


def run_backtest(
    portfolio_runs: list[dict],
    prices: pd.DataFrame,
    tx_cost_bps: int = 0,
) -> dict:
    """
    portfolio_runs: list of {portfolio_date, run_id, holdings: [{ticker, weight}]}
                    sorted by portfolio_date ASC
    prices: DataFrame with columns [ticker, date, adjusted_close]
    Returns: {summary: dict, periods: list[dict]}
    """
    if not portfolio_runs:
        return {"summary": {}, "periods": []}

    # Build a price pivot: date (index) x ticker (columns)
    price_pivot = prices.pivot_table(index="date", columns="ticker", values="adjusted_close")
    price_pivot.index = pd.to_datetime(price_pivot.index)
    price_pivot = price_pivot.sort_index()

    all_dates = price_pivot.index.tolist()

    periods = []
    equity_curve = [1.0]
    monthly_returns = []
    prev_weights: dict[str, float] = {}

    for i, pr in enumerate(portfolio_runs):
        period_start = pd.Timestamp(pr["portfolio_date"])
        period_end = pd.Timestamp(portfolio_runs[i + 1]["portfolio_date"]) if i + 1 < len(portfolio_runs) else None

        if period_end is None:
            # Last period: look for the next trading day 21 business days out
            future_dates = [d for d in all_dates if d > period_start]
            if not future_dates:
                continue
            if len(future_dates) < 21:
                period_end = future_dates[-1]
                # Drop the period if there is no meaningful forward window
                if period_end <= period_start:
                    continue
            else:
                period_end = future_dates[20]

        holdings = {h["ticker"]: float(h["weight"]) for h in pr.get("holdings", [])}
        curr_weights = holdings

        # For each holding: find start and end prices
        holding_returns = {}
        for ticker, w in holdings.items():
            if ticker not in price_pivot.columns:
                continue
            # Find the nearest available price on or after period_start
            start_candidates = [d for d in all_dates if d >= period_start]
            end_candidates = [d for d in all_dates if d >= period_end]
            if not start_candidates or not end_candidates:
                continue
            p_start = price_pivot.loc[start_candidates[0], ticker]
            p_end = price_pivot.loc[end_candidates[0], ticker]
            if pd.isna(p_start) or pd.isna(p_end) or p_start == 0:
                continue
            holding_returns[ticker] = float(p_end / p_start - 1.0)

        if not holding_returns:
            continue

        # Weight-average holding returns (re-normalize weights for available tickers)
        available_weight = sum(holdings[t] for t in holding_returns)
        if available_weight <= 0:
            continue
        port_return = sum(
            holding_returns[t] * holdings[t] / available_weight
            for t in holding_returns
        )

        # Transaction cost
        to = turnover(prev_weights, curr_weights)
        cost = to * tx_cost_bps / 10_000.0
        net_return = port_return - cost

        # SPY benchmark
        benchmark_return = 0.0
        if "SPY" in price_pivot.columns:
            start_candidates = [d for d in all_dates if d >= period_start]
            end_candidates = [d for d in all_dates if d >= period_end]
            if start_candidates and end_candidates:
                p_start = price_pivot.loc[start_candidates[0], "SPY"]
                p_end = price_pivot.loc[end_candidates[0], "SPY"]
                if not pd.isna(p_start) and not pd.isna(p_end) and p_start != 0:
                    benchmark_return = float(p_end / p_start - 1.0)

        n_days = (period_end - period_start).days
        # Drop degenerate periods with no forward data
        if period_end <= period_start:
            continue

        periods.append({
            "period_start": str(period_start.date()),
            "period_end": str(period_end.date()),
            "regime": pr.get("regime"),
            "portfolio_return": round(net_return, 6),
            "benchmark_return": round(benchmark_return, 6),
            "excess_return": round(net_return - benchmark_return, 6),
            "turnover": round(to, 4),
            "n_holdings": len(holding_returns),
            "holdings_snapshot": [
                {"ticker": t, "weight": holdings[t], "period_return": holding_returns.get(t)}
                for t in holdings
            ],
            "run_id": pr.get("run_id"),
            "n_days": n_days,
        })

        equity_curve.append(equity_curve[-1] * (1.0 + net_return))
        monthly_returns.append(net_return)
        prev_weights = curr_weights

    if not periods:
        return {"summary": {}, "periods": []}

    total_return = float(equity_curve[-1] - 1.0)
    total_days = sum(p["n_days"] for p in periods)

    # SPY compounded
    spy_equity = [1.0]
    for p in periods:
        spy_equity.append(spy_equity[-1] * (1.0 + p["benchmark_return"]))
    spy_total = float(spy_equity[-1] - 1.0)

    win_rate = sum(1 for p in periods if p["excess_return"] > 0) / len(periods)

    # Derive periods_per_year from actual average period length so Sharpe is
    # correct for monthly, weekly, or irregular rebalance frequencies.
    avg_period_days = total_days / len(periods) if periods else 21.0
    periods_per_year = 365.25 / max(avg_period_days, 1.0)

    summary = {
        "total_return": round(total_return, 6),
        "annualized_return": round(annualized_return(total_return, total_days), 6),
        "sharpe_ratio": round(sharpe_ratio(monthly_returns, periods_per_year=periods_per_year), 4),
        "max_drawdown": round(max_drawdown(equity_curve), 4),
        "avg_monthly_turnover": round(float(np.mean([p["turnover"] for p in periods])), 4),
        "win_rate": round(win_rate, 4),
        "benchmark_total_return": round(spy_total, 6),
        "benchmark_annualized_return": round(annualized_return(spy_total, total_days), 6),
        "n_rebalances": len(periods),
    }

    return {"summary": summary, "periods": periods}
