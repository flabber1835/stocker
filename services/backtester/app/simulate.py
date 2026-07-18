import pandas as pd
import numpy as np
from app.metrics import annualized_return, sharpe_ratio, max_drawdown, turnover

# Realistic default round-trip transaction cost. A ranking is produced from day
# D's close; the order can't fill until D+1, so a same-close fill is look-ahead.
# 10 bps is a conservative all-in liquid-large-cap estimate (spread + slippage).
DEFAULT_TX_COST_BPS = 10


def _first_after(all_dates, ts):
    """First trading date STRICTLY AFTER ts (the earliest a D-close ranking can
    actually be traded — removes the same-close look-ahead fill). None if none."""
    for d in all_dates:
        if d > ts:
            return d
    return None




def run_backtest(
    portfolio_runs: list[dict],
    prices: pd.DataFrame,
    tx_cost_bps: int = DEFAULT_TX_COST_BPS,
) -> dict:
    """
    portfolio_runs: list of {portfolio_date, run_id, holdings: [{ticker, weight}]}
                    sorted by portfolio_date ASC
    prices: DataFrame with columns [ticker, date, adjusted_close]
    Returns: {summary: dict, periods: list[dict]}

    Fill/bias model (G3): entry is the first close STRICTLY AFTER the rebalance
    date (no same-close look-ahead); exit is the price at/just before the next
    rebalance, and a name that stops trading mid-period exits at its last real
    price. A held name with no usable price is NOT dropped — it stays in the
    full-weight denominator at 0% return, so a missing name can never boost the
    survivors (the old renormalize-over-survivors upward bias).
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

        # Entry date = first close STRICTLY AFTER period_start (t+1 fill, no
        # same-close look-ahead). Exit date = first close strictly after
        # period_end (the new book also can't trade until its own close+1), so
        # entry and exit share the t+1 convention and the window is clean.
        entry_date = _first_after(all_dates, period_start)
        exit_date = _first_after(all_dates, period_end)
        if exit_date is None and entry_date is not None and period_end in all_dates:
            # Truncated FINAL period (audit finding): when period_end is the last
            # available trading day, nothing lies strictly after it, so the
            # "use last available date" branch above never actually produced a
            # period — the sim silently dropped its MOST RECENT rebalance
            # whenever it ended within ~21 trading days of the data edge. Exit
            # AT the last close instead (window is honest, just shorter; still
            # no look-ahead — everything used is ≤ period_end).
            exit_date = period_end
        if entry_date is None or exit_date is None or exit_date <= entry_date:
            continue

        holding_returns = {}   # ticker → realized return (0.0 for priced-but-flat / missing)
        priced = {}            # ticker → had a usable start price (for reporting)
        for ticker, w in holdings.items():
            if ticker not in price_pivot.columns:
                holding_returns[ticker] = 0.0   # no price series → flat, keeps its weight
                priced[ticker] = False
                continue
            p_start = price_pivot.loc[entry_date, ticker]
            if pd.isna(p_start) or p_start == 0:
                # No entry price → could not have opened; contributes 0, no survivor boost.
                holding_returns[ticker] = 0.0
                priced[ticker] = False
                continue
            p_end = price_pivot.loc[exit_date, ticker]
            if pd.isna(p_end):
                # Halted/delisted before the window end → exit at THIS ticker's last
                # real price in (entry_date, exit_date] (captures the realized move
                # to the halt, not a free renormalize-away). None → flat.
                col = price_pivot[ticker]
                valid = col[(col.index > entry_date) & (col.index <= exit_date)].dropna()
                p_end = float(valid.iloc[-1]) if not valid.empty else None
            if p_end is None or pd.isna(p_end):
                holding_returns[ticker] = 0.0
                priced[ticker] = True
                continue
            holding_returns[ticker] = float(p_end / p_start - 1.0)
            priced[ticker] = True

        if not holdings:
            continue

        # Full-weight denominator (NO survivor renormalization): every held name
        # keeps its weight; a missing price is 0% return, never a free boost.
        total_weight = sum(holdings.values())
        if total_weight <= 0:
            continue
        port_return = sum(
            holding_returns[t] * holdings[t] / total_weight for t in holdings
        )

        # Transaction cost
        to = turnover(prev_weights, curr_weights)
        cost = to * tx_cost_bps / 10_000.0
        net_return = port_return - cost

        # SPY benchmark — same t+1 entry/exit dates as the book (consistent window).
        benchmark_return = 0.0
        if "SPY" in price_pivot.columns:
            p_start = price_pivot.loc[entry_date, "SPY"]
            p_end = price_pivot.loc[exit_date, "SPY"]
            if not pd.isna(p_start) and not pd.isna(p_end) and p_start != 0:
                benchmark_return = float(p_end / p_start - 1.0)

        n_days = (exit_date - entry_date).days
        n_priced = sum(1 for t in holdings if priced.get(t))

        periods.append({
            "period_start": str(period_start.date()),
            "period_end": str(period_end.date()),
            "entry_date": str(entry_date.date()),
            "exit_date": str(exit_date.date()),
            "regime": pr.get("regime"),
            "portfolio_return": round(net_return, 6),
            "benchmark_return": round(benchmark_return, 6),
            "excess_return": round(net_return - benchmark_return, 6),
            "turnover": round(to, 4),
            "n_holdings": len(holdings),
            "n_priced": n_priced,          # G3: how many had a real price (rest counted flat)
            "holdings_snapshot": [
                {"ticker": t, "weight": holdings[t], "period_return": round(holding_returns[t], 6),
                 "priced": bool(priced.get(t))}
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
        "tx_cost_bps": tx_cost_bps,
        "periods_per_year": round(periods_per_year, 2),
        # G5: the DISTRIBUTION, not just the mean — the speculative sleeve is a
        # right-tail bet whose average is poor; judging it (or any config) on the
        # mean alone hides skew/kurtosis and tail risk.
        "return_distribution": _distribution_stats(monthly_returns),
        "excess_distribution": _distribution_stats([p["excess_return"] for p in periods]),
    }

    return {"summary": summary, "periods": periods}


def _distribution_stats(xs: list[float]) -> dict:
    """Percentiles + skew/kurtosis of a return series (no scipy). Empty → nulls."""
    a = np.asarray([x for x in xs if x is not None], dtype=float)
    if a.size == 0:
        return {"n": 0}
    out = {
        "n": int(a.size),
        "mean": round(float(a.mean()), 6),
        "std": round(float(a.std(ddof=1)) if a.size > 1 else 0.0, 6),
        "min": round(float(a.min()), 6),
        "p05": round(float(np.percentile(a, 5)), 6),
        "p25": round(float(np.percentile(a, 25)), 6),
        "median": round(float(np.median(a)), 6),
        "p75": round(float(np.percentile(a, 75)), 6),
        "p95": round(float(np.percentile(a, 95)), 6),
        "max": round(float(a.max()), 6),
        "pct_positive": round(float((a > 0).mean()), 4),
    }
    sd = a.std(ddof=0)
    if a.size > 2 and sd > 0:
        z = (a - a.mean()) / sd
        out["skew"] = round(float((z ** 3).mean()), 4)
        out["excess_kurtosis"] = round(float((z ** 4).mean() - 3.0), 4)
    else:
        out["skew"] = None
        out["excess_kurtosis"] = None
    return out
