"""Canonical drawdown / falling-knife math — the SINGLE source of truth shared by the
llm-vetter (the actual veto) and the pipeline (the display copy on the screener card),
so "what the card shows" can never drift from "what the veto computes".

Recent drawdown = how far a stock trades below its own trailing peak:

    drawdown = last_close / max(close over the trailing window) - 1.0   (<= 0)

A stock at a fresh high → 0.0; one trading 27% below its recent peak → -0.27. Unlike
the 12-1 momentum factor (which skips the most recent ~21 days), drawdown has NO skip
window, so it reflects a crash that happened in the last few weeks — the buy-side blind
spot the falling-knife veto closes.

Dependency-free on purpose (no numpy): one definition for both services and their tests.
"""
from __future__ import annotations

from typing import Sequence


def recent_drawdown(
    closes: Sequence[float], window: int = 21, baseline_window: int = 3
) -> float | None:
    """Trailing peak-to-now drawdown over the last `window` closes, net of any
    run-up that has since been given back ("round-trip" suppression).

    closes: chronological adjusted closes (oldest → newest). Only the last
            `window` are considered.

    The naive peak-to-now measure (last/max − 1) overstates damage when a stock
    SPIKED inside the window and then merely round-tripped back toward where it
    started — e.g. ENPH 47 → 72 → 48 reads as −34% even though it is net-flat, and
    AVGO 410 → 480 → 411 reads as −14% with no value lost. Those are volatility,
    not falling knives. To strip the give-back we also measure the drop relative to
    a pre-spike `baseline` (the mean of the first `baseline_window` closes in the
    window) and take whichever shows LESS damage:

        raw_dd       = last / max(window) - 1          (peak-to-now)
        net_dd       = last / baseline    - 1          (damage vs window start)
        effective_dd = min(0, max(raw_dd, net_dd))     (give-back nets out)

    A genuine one-way collapse has baseline ≈ peak, so net_dd ≈ raw_dd and the
    value is unchanged — it still fires. A round-trip back to baseline nets to ~0.
    A crash that ended BELOW the baseline reports the real (smaller) net loss.

    `baseline_window=0` disables the adjustment and restores pure peak-to-now.

    Returns a value in (-1.0, 0.0] (0.0 = at peak / net-flat-or-up), or None if
    there is no usable price data (empty, or no positive peak).
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
    raw_dd = last / peak - 1.0
    if baseline_window and baseline_window > 0:
        bw = min(baseline_window, len(recent))
        baseline = sum(recent[:bw]) / bw
        if baseline > 0:
            net_dd = last / baseline - 1.0
            return min(0.0, max(raw_dd, net_dd))
    return raw_dd


def beta_and_idio_vol(
    stock_closes: Sequence[float],
    spy_closes: Sequence[float],
    lookback: int = 120,
    min_observations: int = 20,
) -> tuple[float | None, float | None]:
    """OLS beta of stock vs SPY daily returns AND the stock's idiosyncratic
    (residual) annualized volatility.

    beta = cov(r_stock, r_spy) / var(r_spy); idio_vol = stdev(r_stock − beta·r_spy)
    × √252 — the stock-specific noise left after stripping the market component.
    Both series chronological + ALIGNED to the same trading dates; last `lookback`+1
    closes. Returns (None, None) when there aren't `min_observations` usable pairs
    or SPY has zero variance. Pure / dependency-free (no numpy).
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
        return None, None
    k = len(rs)
    mean_s = sum(rs) / k
    mean_m = sum(rm) / k
    var_m = sum((x - mean_m) ** 2 for x in rm)
    if var_m <= 0:
        return None, None
    cov = sum((rs[i] - mean_s) * (rm[i] - mean_m) for i in range(k))
    beta = cov / var_m
    resid = [rs[i] - beta * rm[i] for i in range(k)]
    mean_r = sum(resid) / k
    var_r = sum((x - mean_r) ** 2 for x in resid) / max(k - 1, 1)
    idio_vol = (var_r ** 0.5) * (252 ** 0.5)
    return beta, idio_vol


def estimate_beta(
    stock_closes: Sequence[float],
    spy_closes: Sequence[float],
    lookback: int = 120,
    min_observations: int = 20,
) -> float | None:
    """OLS beta of stock daily returns on SPY daily returns (see beta_and_idio_vol)."""
    return beta_and_idio_vol(stock_closes, spy_closes, lookback, min_observations)[0]


def scaled_excess_threshold(
    idio_vol: float | None,
    base: float,
    anchor: float = 0.35,
    lo: float = 0.10,
    hi: float = 0.30,
) -> float:
    """Vol-scaled excess-drawdown limit: base × (idio_vol / anchor), clamped to
    [lo, hi]. A calm stock (low idio_vol) gets a TIGHTER limit (flagged on a
    smaller idiosyncratic drop); a wild one gets MORE rope. Falls back to the flat
    `base` when idio_vol is unknown (insufficient history) or anchor is invalid, so
    a data-poor name is never given a weird threshold."""
    if idio_vol is None or anchor is None or anchor <= 0:
        return base
    return max(lo, min(hi, base * (idio_vol / anchor)))


def excess_drawdown(
    stock_closes: Sequence[float],
    spy_closes: Sequence[float],
    window: int = 21,
    beta_lookback: int = 120,
    beta_floor: float = 0.0,
    beta_cap: float = 3.0,
    baseline_window: int = 3,
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

    The drawdown is round-trip aware (see `recent_drawdown`): the drop is measured
    against whichever of the trailing peak or the pre-spike baseline (mean of the
    first `baseline_window` aligned closes) shows LESS damage, and the SPY move is
    taken over the SAME span so the beta adjustment stays consistent. This keeps a
    spike-and-give-back (e.g. an earnings round-trip) from registering as a knife
    while leaving a genuine one-way decline unchanged. `baseline_window=0` restores
    pure peak-to-now.

    Returns {raw_dd, spy_move, beta, excess_dd, idio_vol} or None when there isn't
    enough aligned price history. `raw_dd` is the round-trip-aware (effective)
    drawdown — the value the floor/veto act on. `beta`/`excess_dd` are None when
    beta can't be estimated — caller then falls back to the absolute floor.
    `idio_vol` (annualized residual vol) drives the vol-scaled threshold.
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
    # Peak-to-now (raw) and the SPY move over that span.
    raw_dd = s_vals[-1] / peak - 1.0
    spy_move = m_vals[-1] / m_vals[peak_i] - 1.0
    # Round-trip suppression: also measure vs a pre-spike baseline and, when that
    # shows less damage (a give-back), use it AND the matching SPY span so beta
    # strips the right market move. Mirrors recent_drawdown's effective_dd.
    if baseline_window and baseline_window > 0:
        bw = min(baseline_window, len(s_vals))
        base_s = sum(s_vals[:bw]) / bw
        base_m = sum(m_vals[:bw]) / bw
        if base_s > 0 and base_m > 0:
            net_dd = s_vals[-1] / base_s - 1.0
            if net_dd >= raw_dd:  # less damage → round-trip; nets the give-back out
                raw_dd = min(0.0, net_dd)
                spy_move = m_vals[-1] / base_m - 1.0

    beta, idio_vol = beta_and_idio_vol(stock_closes, spy_closes, lookback=beta_lookback)
    if beta is None:
        return {"raw_dd": raw_dd, "spy_move": spy_move, "beta": None,
                "excess_dd": None, "idio_vol": idio_vol}
    beta = min(max(beta, beta_floor), beta_cap)
    return {
        "raw_dd": raw_dd,
        "spy_move": spy_move,
        "beta": beta,
        "excess_dd": raw_dd - beta * spy_move,
        "idio_vol": idio_vol,
    }
