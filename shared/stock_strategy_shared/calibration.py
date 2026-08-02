"""Score-calibration diagnostics — CANONICAL, pure math.

Does a better rank actually predict a better forward return, and is the
relationship monotone? Sampled dates → decile-of-rank → mean forward return over
`horizon` sessions. A flat or non-monotone curve says the ordering carries no
information in that band; top-decile-only lift with a flat middle is evidence for
a concentrated book rather than a calibrated continuous forecast.

Deciles are CONTIGUOUS RANK BINS (decile 1 = best). Tickers missing a price at
either end of the span are EXCLUDED and counted, never averaged in as 0.

Why this module is shared
-------------------------
There used to be two implementations — `services/bt-engine/app/calibration.py`
and an inline copy in the evaluator's `packet.py` — and they drifted, which is
how the live one ended up without a config filter, without error bars, and with
an unbounded forward-price lookup while the tunnel's was fine. Both now import
this; bt-engine's module is a re-export shim, the same treatment `rank`/`select`
got.

Reading the output honestly
---------------------------
A decile curve without a sample size and an interval is not a result. An external
review of this system computed a top-minus-bottom spread of +0.40pp with a
bootstrap 95% interval of −1.13 to +1.86 and correctly called it weak — while the
version that shipped here reported only the point estimate. So `aggregate` now
returns, alongside the curve:

  n_dates            how many independent anchors are behind it
  per_date_ic        the per-date rank IC distribution and how often it is > 0
  spread_ci          bootstrap interval + P(spread > 0) over the per-date spreads
  missing_rate       share of ranked names dropped for want of an endpoint price

Those four are what separate "the ranking predicts returns" from "six overlapping
windows happened to line up".
"""
from __future__ import annotations

import random
from typing import Callable, Sequence

N_BINS = 10
BOOTSTRAP_DRAWS = 2000
# Fixed so the same inputs always produce the same interval — this repo tests
# determinism directly, and a CI that moves between runs is not quotable.
BOOTSTRAP_SEED = 20260802


# ── one date ──────────────────────────────────────────────────────────────────

def decile_forward_returns(scores: dict[str, float],
                           base_prices: dict[str, float] | Callable[[str], float | None],
                           fwd_prices: dict[str, float] | Callable[[str], float | None],
                           n_bins: int = N_BINS,
                           benchmark_return: float | None = None) -> list[dict]:
    """One date's calibration row: rank `scores` best-first, cut into n_bins
    contiguous bins, mean forward return per bin. Returns [] when there are
    fewer scored tickers than bins (a decile of <1 name is noise).

    `benchmark_return` (optional) subtracts a market return over the same span,
    making the numbers EXCESS returns — what the live evaluator reports.
    """
    base_get = base_prices.get if isinstance(base_prices, dict) else base_prices
    fwd_get = fwd_prices.get if isinstance(fwd_prices, dict) else fwd_prices

    rets: list[tuple[float, float]] = []          # (score, fwd_return), scored only
    n_scored = n_missing = 0
    for t, s in scores.items():
        if s is None:
            continue
        n_scored += 1
        b, f = base_get(t), fwd_get(t)
        if b is None or f is None or b <= 0:
            n_missing += 1
            continue
        r = f / b - 1.0
        if benchmark_return is not None:
            r -= benchmark_return
        rets.append((float(s), r))
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
    # Carried on the first bin so a date's coverage and IC travel with its row
    # rather than needing a parallel structure through every caller.
    out[0]["_meta"] = {
        "n_scored": n_scored,
        "n_missing": n_missing,
        "rank_ic": spearman_ic([(-s, r) for s, r in rets]),
    }
    return out


def top_n_return(pairs: Sequence[tuple[int, float]], n: int) -> float | None:
    """Mean forward return of the best-ranked `n` names.

    The decile curve answers "is the ORDERING informative"; this answers "does the
    part we actually BUY outperform". For a 25-name book out of ~2000 those are
    very different questions — the book is the top ~1.75%, i.e. the top fifth of
    decile 1 — and a ranking can be useless in its middle while its head still
    pays. Reported alongside the curve so the two are never conflated.
    """
    vals = [v for _r, v in sorted(pairs, key=lambda x: x[0])[:max(1, n)]]
    return round(sum(vals) / len(vals), 6) if vals else None


def decile_rows_from_ranks(pairs: Sequence[tuple[int, float]],
                           n_bins: int = N_BINS,
                           n_scored: int | None = None,
                           n_missing: int = 0,
                           top_n: int | None = None) -> list[dict]:
    """Same shape as `decile_forward_returns`, for callers that already hold
    (rank, forward_return) pairs — the live path, where the rank is persisted and
    the return is computed in SQL. Lower rank = better."""
    pairs = [(int(r), float(v)) for r, v in pairs]
    if len(pairs) < n_bins:
        return []
    ordered = sorted(pairs, key=lambda x: x[0])
    n = len(ordered)
    out = []
    for d in range(n_bins):
        chunk = [v for _, v in ordered[(d * n) // n_bins:((d + 1) * n) // n_bins]]
        out.append({"decile": d + 1, "n": len(chunk),
                    "avg_fwd": sum(chunk) / len(chunk) if chunk else None})
    out[0]["_meta"] = {
        "n_scored": n_scored if n_scored is not None else len(pairs) + n_missing,
        "n_missing": n_missing,
        "rank_ic": spearman_ic(ordered),
        "top_n": top_n,
        "top_n_return": top_n_return(ordered, top_n) if top_n else None,
    }
    return out


# ── statistics ────────────────────────────────────────────────────────────────

def spearman_ic(pairs: Sequence[tuple[float, float]]) -> float | None:
    """Rank correlation between a ranking key and the realised forward return.

    Sign convention: pairs are (rank_key, forward_return) where a LOWER key is a
    BETTER prediction, so a working model gives a NEGATIVE raw correlation. This
    returns the flipped value, so positive = the ranking predicts returns — the
    same orientation as the published IC everyone quotes.

    Ties are averaged. None when fewer than 3 usable pairs or either side is
    constant. No scipy: neither image ships it.
    """
    vals = [(float(a), float(b)) for a, b in pairs
            if a is not None and b is not None]
    if len(vals) < 3:
        return None
    ra = _average_ranks([a for a, _ in vals])
    rb = _average_ranks([b for _, b in vals])
    n = len(vals)
    ma, mb = sum(ra) / n, sum(rb) / n
    va = sum((x - ma) ** 2 for x in ra)
    vb = sum((x - mb) ** 2 for x in rb)
    if va <= 0 or vb <= 0:
        return None
    cov = sum((x - ma) * (y - mb) for x, y in zip(ra, rb))
    return round(-cov / (va ** 0.5 * vb ** 0.5), 6)


def _average_ranks(xs: Sequence[float]) -> list[float]:
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    out = [0.0] * len(xs)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        avg = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            out[order[k]] = avg
        i = j + 1
    return out


def bootstrap_ci(values: Sequence[float], draws: int = BOOTSTRAP_DRAWS,
                 seed: int = BOOTSTRAP_SEED, alpha: float = 0.05) -> dict | None:
    """Percentile bootstrap over independent per-date observations.

    Returns mean, [lo, hi] and `prob_positive` — the share of resamples whose
    mean is > 0. That last number is the one worth quoting: it converts "the
    spread was +0.40pp" into "…and there is a 69% chance the true spread is
    positive", which reads very differently.

    None below 3 observations: a bootstrap over two points is theatre.
    """
    vals = [float(v) for v in values if v is not None]
    if len(vals) < 3:
        return None
    rng = random.Random(seed)
    n = len(vals)
    means = []
    for _ in range(draws):
        means.append(sum(vals[rng.randrange(n)] for _ in range(n)) / n)
    means.sort()
    lo = means[int(alpha / 2 * draws)]
    hi = means[min(draws - 1, int((1 - alpha / 2) * draws))]
    return {
        "n_obs": n,
        "mean": round(sum(vals) / n, 6),
        "lo": round(lo, 6),
        "hi": round(hi, 6),
        "prob_positive": round(sum(1 for m in means if m > 0) / draws, 4),
        "draws": draws,
    }


# ── aggregation ───────────────────────────────────────────────────────────────

def aggregate_calibration(per_date_rows: list[list[dict]],
                          horizon_sessions: int, n_bins: int = N_BINS,
                          regimes: Sequence[str | None] | None = None) -> dict | None:
    """Average the per-date decile rows into the final curve, WITH the evidence
    needed to judge it. None when no date produced a usable row.

    `regimes` (optional, parallel to per_date_rows) adds a per-regime breakdown.
    A factor can be monotone in bull_calm and inverted in bear_stress; pooling
    them can flatten a real conditional relationship or universalise an accident.
    """
    usable_idx = [i for i, rows in enumerate(per_date_rows) if rows]
    usable = [per_date_rows[i] for i in usable_idx]
    if not usable:
        return None
    out = _curve(usable, n_bins)
    out["horizon_sessions"] = horizon_sessions

    if regimes is not None:
        by_regime = {}
        for i in usable_idx:
            by_regime.setdefault(regimes[i] or "unknown", []).append(per_date_rows[i])
        # Only worth reporting where there is more than one regime AND enough
        # dates in it to be anything other than a single observation restated.
        if len(by_regime) > 1:
            out["by_regime"] = {
                r: _curve(rows, n_bins) for r, rows in sorted(by_regime.items())
                if len(rows) >= 2
            }
    return out


def _curve(usable: list[list[dict]], n_bins: int) -> dict:
    sums = [0.0] * n_bins
    counts = [0] * n_bins
    ns = [0] * n_bins
    per_date_spread: list[float] = []
    per_date_ic: list[float] = []
    per_date_top_n: list[float] = []
    top_n_size = None
    n_scored = n_missing = 0
    for rows in usable:
        vals: list[float | None] = [None] * n_bins
        for r in rows:
            i = r["decile"] - 1
            if r["avg_fwd"] is not None:
                sums[i] += r["avg_fwd"]
                counts[i] += 1
                ns[i] += r["n"]
                vals[i] = r["avg_fwd"]
        if vals[0] is not None and vals[-1] is not None:
            per_date_spread.append(vals[0] - vals[-1])
        meta = (rows[0] or {}).get("_meta") or {}
        if meta.get("rank_ic") is not None:
            per_date_ic.append(meta["rank_ic"])
        if meta.get("top_n_return") is not None:
            per_date_top_n.append(meta["top_n_return"])
            top_n_size = meta.get("top_n")
        n_scored += int(meta.get("n_scored") or 0)
        n_missing += int(meta.get("n_missing") or 0)

    deciles = [{"decile": i + 1,
                "avg_fwd": round(sums[i] / counts[i], 6) if counts[i] else None,
                "n": ns[i]} for i in range(n_bins)]
    avgs = [d["avg_fwd"] for d in deciles]
    pairs = [(a, b) for a, b in zip(avgs, avgs[1:]) if a is not None and b is not None]
    return {
        "n_dates": len(usable),
        "deciles": deciles,
        "top_minus_bottom": (round(avgs[0] - avgs[-1], 6)
                             if avgs[0] is not None and avgs[-1] is not None else None),
        "monotone_fraction": (round(sum(1 for a, b in pairs if a >= b) / len(pairs), 4)
                              if pairs else None),
        "spread_ci": bootstrap_ci(per_date_spread),
        "per_date_ic": _ic_stats(per_date_ic),
        # Delisted / halted names have no endpoint price. They are EXCLUDED here,
        # never carried at their last print — treating a disappeared name as flat
        # inflates the deciles it concentrates in (the low ones), which shrinks
        # top-minus-bottom and makes the ranking look worse than it is.
        # What the BOOK would have earned, not what the ordering implies. A 25-name
        # book is the top ~1.75% of the universe; whether decile 6 beats decile 2
        # cannot touch its P&L, so a flat middle and a paying head are perfectly
        # consistent and must be reported separately rather than averaged into one
        # verdict about "the ranking".
        "top_n": top_n_size,
        "top_n_avg_return": (round(sum(per_date_top_n) / len(per_date_top_n), 6)
                             if per_date_top_n else None),
        "top_n_ci": bootstrap_ci(per_date_top_n),
        "missing_endpoint_rate": (round(n_missing / n_scored, 4) if n_scored else None),
        "n_scored": n_scored,
        "n_missing_endpoint": n_missing,
    }


def _ic_stats(ics: list[float]) -> dict | None:
    if not ics:
        return None
    n = len(ics)
    mean = sum(ics) / n
    return {
        "n_dates": n,
        "mean": round(mean, 6),
        "median": round(sorted(ics)[n // 2], 6),
        "share_positive": round(sum(1 for x in ics if x > 0) / n, 4),
        "min": round(min(ics), 6),
        "max": round(max(ics), 6),
        "ci": bootstrap_ci(ics),
    }


# ── date selection ────────────────────────────────────────────────────────────

def sample_evenly(items: list, max_n: int) -> list:
    """Deterministic even sampling preserving order (first and last kept)."""
    if len(items) <= max_n:
        return list(items)
    if max_n <= 1:
        return [items[-1]]
    step = (len(items) - 1) / (max_n - 1)
    idxs = sorted({round(i * step) for i in range(max_n)})
    return [items[i] for i in idxs]


def space_out(keys: Sequence, min_gap: int, max_n: int | None = None) -> list[int]:
    """Indices of `keys` (ascending, comparable, e.g. session indices) kept at
    least `min_gap` apart, newest-first so the most recent anchor is always in.

    This is what makes the observations INDEPENDENT. Six anchors drawn from a
    70-day window with a 20-session forward horizon share most of their return
    path, so a bootstrap over them understates the true interval badly — they are
    not six samples, they are closer to two.
    """
    order = sorted(range(len(keys)), key=lambda i: keys[i], reverse=True)
    kept: list[int] = []
    last = None
    for i in order:
        if last is None or (last - keys[i]) >= min_gap:
            kept.append(i)
            last = keys[i]
            if max_n is not None and len(kept) >= max_n:
                break
    return sorted(kept)
