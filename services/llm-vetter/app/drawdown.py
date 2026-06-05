"""Pure recent-drawdown helper, shared by the vetter (prompt + backstop) and tests.

Recent drawdown = how far a stock trades below its own trailing peak:

    drawdown = last_close / max(close over the trailing window) - 1.0   (<= 0)

A stock at a fresh high → 0.0; one trading 27% below its recent peak → -0.27.
This is the "falling knife" signal: unlike the 12-1 momentum factor (which skips
the most recent ~21 days), drawdown has NO skip window, so it reflects a crash
that happened in the last few weeks — exactly the blind spot on the buy side.

Dependency-free on purpose: one definition used by the live vetter and its tests.
"""
from __future__ import annotations

from typing import Sequence


def recent_drawdown(closes: Sequence[float], window: int = 21) -> float | None:
    """Trailing peak-to-now drawdown over the last `window` closes.

    closes: chronological adjusted closes (oldest → newest). Only the last
            `window` are considered.
    Returns a value in (-1.0, 0.0] (0.0 = at peak), or None if there is no
    usable price data (empty, or no positive peak).
    """
    if not closes:
        return None
    recent = [float(c) for c in closes[-window:] if c is not None and float(c) > 0]
    if not recent:
        return None
    peak = max(recent)
    last = recent[-1]
    if peak <= 0:
        return None
    return last / peak - 1.0


def estimate_beta(
    stock_closes: Sequence[float],
    spy_closes: Sequence[float],
    lookback: int = 120,
    min_observations: int = 20,
) -> float | None:
    """OLS beta of stock daily returns on SPY daily returns.

    Both series must be chronological (oldest → newest) and ALIGNED to the same
    trading dates (caller aligns by date). Uses the last `lookback`+1 closes.
    beta = cov(r_stock, r_spy) / var(r_spy). Returns None if there aren't at least
    `min_observations` usable return pairs or SPY has zero variance.

    Pure / dependency-free (no numpy) to match this module's one-definition rule.
    """
    s = list(stock_closes)[-(lookback + 1):]
    m = list(spy_closes)[-(lookback + 1):]
    n = min(len(s), len(m))
    rs: list[float] = []
    rm: list[float] = []
    for i in range(1, n):
        a0, a1, b0, b1 = s[i - 1], s[i], m[i - 1], m[i]
        if a0 and a1 and b0 and b1 and float(a0) > 0 and float(b0) > 0:
            rs.append(float(a1) / float(a0) - 1.0)
            rm.append(float(b1) / float(b0) - 1.0)
    if len(rs) < min_observations:
        return None
    mean_s = sum(rs) / len(rs)
    mean_m = sum(rm) / len(rm)
    var_m = sum((x - mean_m) ** 2 for x in rm)
    if var_m <= 0:
        return None
    cov = sum((rs[i] - mean_s) * (rm[i] - mean_m) for i in range(len(rs)))
    return cov / var_m


def excess_drawdown(
    stock_closes: Sequence[float],
    spy_closes: Sequence[float],
    window: int = 21,
    beta_lookback: int = 120,
    beta_floor: float = 0.0,
    beta_cap: float = 3.0,
) -> dict | None:
    """Beta-adjusted (residual) drawdown — the stock-specific falling-knife signal.

        excess_dd = raw_dd - beta * spy_move_over_same_span

    where raw_dd is the trailing-window peak-to-now drawdown, spy_move is SPY's
    return from the date of THAT peak to now, and beta is the stock's market beta.
    Strips out the market-driven portion of the drop: a name that fell only because
    the market fell (excess ≈ 0) is NOT a falling knife; a name falling on its own
    (large negative excess) is.

    `stock_closes` and `spy_closes` must be chronological and ALIGNED to the same
    trading dates. beta is clipped to [beta_floor, beta_cap] (default [0, 3]) so a
    noisy/negative estimate can't invert the adjustment.

    Returns {raw_dd, spy_move, beta, excess_dd} or None when there isn't enough
    aligned price history. `beta`/`excess_dd` are None (raw_dd still populated) when
    beta can't be estimated — caller then falls back to the absolute floor.
    """
    if not stock_closes or not spy_closes:
        return None
    sw = list(stock_closes)[-window:]
    mw = list(spy_closes)[-window:]
    pairs = [
        (float(a), float(b))
        for a, b in zip(sw, mw)
        if a and b and float(a) > 0 and float(b) > 0
    ]
    if len(pairs) < 2:
        return None
    s_vals = [a for a, _ in pairs]
    m_vals = [b for _, b in pairs]
    peak = max(s_vals)
    peak_i = s_vals.index(peak)
    raw_dd = s_vals[-1] / peak - 1.0
    spy_move = m_vals[-1] / m_vals[peak_i] - 1.0

    beta = estimate_beta(stock_closes, spy_closes, lookback=beta_lookback)
    if beta is None:
        return {"raw_dd": raw_dd, "spy_move": spy_move, "beta": None, "excess_dd": None}
    beta = min(max(beta, beta_floor), beta_cap)
    return {
        "raw_dd": raw_dd,
        "spy_move": spy_move,
        "beta": beta,
        "excess_dd": raw_dd - beta * spy_move,
    }
