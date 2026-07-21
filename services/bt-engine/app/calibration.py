"""Score-calibration diagnostics (closed-loop item 3, pure math).

Does a better composite score actually predict a better forward return, and is
the relationship monotone? Sampled rebalance dates → decile-of-score → mean
forward return over `horizon` sessions. A flat or non-monotone curve says the
model's ordering carries no information in that band; top-decile-only lift with
a flat middle is evidence for concentrated books.

Deciles are CONTIGUOUS RANK BINS (decile 1 = best-scored tenth). Tickers
missing a price at either end of the span are skipped (delisted mid-horizon —
their absence is reported via per-decile n, not silently averaged as 0).
"""
from __future__ import annotations

from typing import Callable

N_BINS = 10


def decile_forward_returns(scores: dict[str, float],
                           base_prices: dict[str, float] | Callable[[str], float | None],
                           fwd_prices: dict[str, float] | Callable[[str], float | None],
                           n_bins: int = N_BINS) -> list[dict]:
    """One date's calibration row: rank `scores` best-first, cut into n_bins
    contiguous bins, mean forward return per bin. Returns [] when there are
    fewer scored tickers than bins (a decile of <1 name is noise)."""
    base_get = base_prices.get if isinstance(base_prices, dict) else base_prices
    fwd_get = fwd_prices.get if isinstance(fwd_prices, dict) else fwd_prices

    rets: list[tuple[float, float]] = []          # (score, fwd_return), scored only
    for t, s in scores.items():
        if s is None:
            continue
        b, f = base_get(t), fwd_get(t)
        if b is None or f is None or b <= 0:
            continue
        rets.append((float(s), f / b - 1.0))
    if len(rets) < n_bins:
        return []
    rets.sort(key=lambda x: -x[0])                # best score first
    out = []
    n = len(rets)
    for d in range(n_bins):
        lo, hi = (d * n) // n_bins, ((d + 1) * n) // n_bins
        chunk = [r for _, r in rets[lo:hi]]
        out.append({"decile": d + 1, "n": len(chunk),
                    "avg_fwd": sum(chunk) / len(chunk) if chunk else None})
    return out


def aggregate_calibration(per_date_rows: list[list[dict]],
                          horizon_sessions: int, n_bins: int = N_BINS) -> dict | None:
    """Average the per-date decile rows into the final curve. None when no date
    produced a usable row. monotone_fraction = share of adjacent decile pairs
    where the better decile beat the worse one (1.0 = perfectly monotone);
    top_minus_bottom = decile-1 avg − decile-N avg."""
    usable = [rows for rows in per_date_rows if rows]
    if not usable:
        return None
    sums = [0.0] * n_bins
    counts = [0] * n_bins
    ns = [0] * n_bins
    for rows in usable:
        for r in rows:
            i = r["decile"] - 1
            if r["avg_fwd"] is not None:
                sums[i] += r["avg_fwd"]
                counts[i] += 1
                ns[i] += r["n"]
    deciles = [{"decile": i + 1,
                "avg_fwd": round(sums[i] / counts[i], 6) if counts[i] else None,
                "n": ns[i]} for i in range(n_bins)]
    avgs = [d["avg_fwd"] for d in deciles]
    pairs = [(a, b) for a, b in zip(avgs, avgs[1:]) if a is not None and b is not None]
    return {
        "horizon_sessions": horizon_sessions,
        "n_dates": len(usable),
        "deciles": deciles,
        "top_minus_bottom": (round(avgs[0] - avgs[-1], 6)
                             if avgs[0] is not None and avgs[-1] is not None else None),
        "monotone_fraction": (round(sum(1 for a, b in pairs if a >= b) / len(pairs), 4)
                              if pairs else None),
    }


def sample_evenly(items: list, max_n: int) -> list:
    """Deterministic even sampling preserving order (first and last kept)."""
    if len(items) <= max_n:
        return list(items)
    if max_n <= 1:
        return [items[-1]]
    step = (len(items) - 1) / (max_n - 1)
    idxs = sorted({round(i * step) for i in range(max_n)})
    return [items[i] for i in idxs]
