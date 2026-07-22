"""Pure outcome-labeling math for the decision ledger (decision_outcomes).

Given a decision (ticker + decision date), a session calendar (the SPY date
grid — same convention as the factor stack), and adjusted-close series, compute
forward returns at fixed session horizons, SPY over the same spans, and the
20-session max-favorable/adverse excursion.

Conventions (mirroring the backtester's de-bias rules):
- The decision session is the last session ≤ decision_date.
- A price "at" a session is the last available price ≤ that session's date,
  capped by MAX_BASE_LAG_SESSIONS for the BASE price only (a decision on a
  name with no recent price is unpriceable, not stale-priceable). Forward
  prices have no cap: a delisted/halted name holds at its last real price.
- A horizon is labelable only once the calendar has that many sessions past
  the decision session. MFE/MAE are computed only when the full 20-session
  window has elapsed (they are window statistics, not running values).
- `complete` when the longest horizon has elapsed and labeling ran — even if
  base_price was never found (give-up rule: null labels, no eternal retry).

No I/O, no globals — everything a test can drive directly.
"""
from __future__ import annotations

from bisect import bisect_right
from datetime import date

HORIZONS = (1, 5, 20, 60)
MFE_WINDOW = 20
MAX_BASE_LAG_SESSIONS = 5


def price_at_or_before(series: dict[date, float], d: date) -> tuple[date, float] | None:
    """Last (date, price) with date ≤ d, or None. `series` keys need not be sorted."""
    best: tuple[date, float] | None = None
    for pd_, px in series.items():
        if pd_ <= d and (best is None or pd_ > best[0]):
            best = (pd_, px)
    return best


def label_decision(
    decision_date: date,
    prices: dict[date, float],
    spy_prices: dict[date, float],
    sessions: list[date],
    horizons: tuple[int, ...] = HORIZONS,
) -> dict | None:
    """Compute the label columns for one decision.

    Returns None when the decision date precedes the session calendar entirely
    (nothing to anchor to). Otherwise a dict with base_price, fwd_<h>d,
    spy_fwd_<h>d, mfe/mae, and `complete`.
    """
    i = bisect_right(sessions, decision_date) - 1
    if i < 0:
        return None
    anchor = sessions[i]
    max_h = max(horizons)
    calendar_done = i + max_h < len(sessions)

    out: dict = {f"fwd_{h}d": None for h in horizons}
    out.update({f"spy_fwd_{h}d": None for h in horizons})
    out.update({f"stale_{h}d": None for h in horizons})
    out.update({"base_price": None, "mfe_20d": None, "mae_20d": None,
                "complete": calendar_done})

    base = price_at_or_before(prices, anchor)
    if base is not None:
        lag_i = bisect_right(sessions, base[0]) - 1
        if i - lag_i > MAX_BASE_LAG_SESSIONS:
            base = None
    spy_base = price_at_or_before(spy_prices, anchor)

    for h in horizons:
        if i + h >= len(sessions):
            continue  # horizon not yet elapsed — stays null, row stays incomplete
        target = sessions[i + h]
        if base is not None and base[1] > 0:
            fp = price_at_or_before(prices, target)
            if fp is not None:
                out[f"fwd_{h}d"] = fp[1] / base[1] - 1.0
                # Staleness (audit-3 fix #2): sessions between the print this
                # label actually used and the horizon session. 0 = fresh; a
                # delisted/halted name held at its last real price is visibly
                # stale instead of silently "valid". Consumers filter on this.
                fp_i = bisect_right(sessions, fp[0]) - 1
                out[f"stale_{h}d"] = max(0, (i + h) - fp_i)
        if spy_base is not None and spy_base[1] > 0:
            sp = price_at_or_before(spy_prices, target)
            if sp is not None:
                out[f"spy_fwd_{h}d"] = sp[1] / spy_base[1] - 1.0

    if base is not None:
        out["base_price"] = base[1]
        if i + MFE_WINDOW < len(sessions) and base[1] > 0:
            window = []
            for s in sessions[i + 1: i + 1 + MFE_WINDOW]:
                p = price_at_or_before(prices, s)
                if p is not None:
                    window.append(p[1] / base[1] - 1.0)
            if window:
                out["mfe_20d"] = max(window)
                out["mae_20d"] = min(window)
    return out
