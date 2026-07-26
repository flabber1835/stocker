"""Auto-revert decision: is the DISPLACED champion beating the one that
replaced it?

Pure. No DB, no filesystem, no clock — the caller assembles the paired daily
spans and this decides. Keeping it pure is what makes a config-changing rule
testable at the boundaries that matter (too little data, a hair-thin edge, a
one-day outlier) instead of only in a live deploy.

The comparison is TARGET vs TARGET, both theoretical, over the same fixed
session horizon. Comparing realized account equity against a theoretical shadow
would be biased: realized carries costs, slippage and execution timing that the
shadow does not, so the champion would lose a rigged race.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RevertVerdict:
    revert: bool
    reason: str
    n_days: int = 0
    avg_spread: float | None = None      # displaced − champion, per span
    days_displaced_ahead: int = 0


def revert_decision(pairs: list[tuple[float, float]], *,
                    min_sessions: int, margin: float) -> RevertVerdict:
    """`pairs` = [(champion_return, displaced_return)] — one entry per day whose
    forward horizon has FULLY elapsed, both scored over the same span.

    Reverts only when the displaced champion is ahead by at least `margin` on
    average AND was ahead on a MAJORITY of days. The majority condition is not
    redundant with the mean: one crash day in the champion's book can carry an
    average on its own, and reverting the live config on a single outlier is
    exactly the whipsaw this system spends its orphan timers avoiding.

    Fail-closed everywhere: too few days, no data, or a mean inside the margin
    all return revert=False. Absence of evidence must never move the config."""
    if margin < 0:
        raise ValueError("margin must be >= 0 — a negative margin would revert "
                         "on the champion merely being level")
    clean = [(float(c), float(d)) for c, d in pairs
             if c is not None and d is not None]
    n = len(clean)
    if n < min_sessions:
        return RevertVerdict(False, f"only {n} fully-elapsed span(s), need "
                                    f"{min_sessions}", n_days=n)
    spreads = [d - c for c, d in clean]
    avg = sum(spreads) / n
    ahead = sum(1 for s in spreads if s > 0)
    if avg < margin:
        return RevertVerdict(
            False, f"displaced champion ahead by {avg:+.4f} over {n} spans — "
                   f"inside the {margin:+.4f} margin, keeping the promotion",
            n_days=n, avg_spread=round(avg, 6), days_displaced_ahead=ahead)
    if ahead * 2 <= n:
        return RevertVerdict(
            False, f"mean spread {avg:+.4f} clears the margin but the displaced "
                   f"champion led on only {ahead}/{n} spans — concentrated in a "
                   "few days, not a persistent edge",
            n_days=n, avg_spread=round(avg, 6), days_displaced_ahead=ahead)
    return RevertVerdict(
        True, f"displaced champion ahead by {avg:+.4f} on average over {n} spans "
              f"and led on {ahead}/{n} — reverting the promotion",
        n_days=n, avg_spread=round(avg, 6), days_displaced_ahead=ahead)


def weighted_return(target: dict, returns: dict) -> float | None:
    """Weight-averaged return of a {ticker: weight} target given
    {ticker: return}. Renormalizes over the priced names ONLY, so a name with
    no price does not silently count as 0% — that would flatter whichever side
    has more missing data. None when nothing is priced. Pure."""
    if not target:
        return None
    num = den = 0.0
    for t, w in target.items():
        r = returns.get(t)
        if r is None:
            continue
        try:
            w = float(w)
            num += w * float(r)
            den += w
        except (TypeError, ValueError):
            continue
    return (num / den) if den > 0 else None
