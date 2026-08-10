"""SHARADAR/ACTIONS -> authoritative split ratios and dividends. PURE.

CARRIED FORWARD from `services/backtester/app/wealth_core_replay.py`, the same
way `sentinel/core/terminal.py` carries the terminal mapping: Sentinel may not
import a retired Stocker SERVICE, and the behaviour must not diverge because of
it. `tests/sentinel/test_actions_map.py` pins the two against each other.

WHY THIS EXISTS AT ALL — the defect it closes. `ingest.seed` and `ingest.daily`
fetched ACTIONS, wrote it to `sentinel_actions`, and then called
`normalise_sep_rows` WITHOUT `authoritative_splits=` or `dividends=`, both of
which that function already supported. So the Sentinel corpus carried

    dividend_per_share = 0.0        everywhere
    split_ratio                     inferred from the price domains, always

while the module docstring said ACTIONS was fetched first precisely so derived
ratios could be checked against it. The data was loaded, ignored, and described
as authoritative.

## Why the derived ratio is not good enough, specifically now

`split_ratio_from_domains` recovers the ratio from the adjusted/unadjusted price
pair and then SNAPS it to a near-integer, because it was built when every split
the engine cared about was integral. A genuine 3:2 is 1.5 — equidistant from 1
and 2 — so tiny floating error in either direction decides whether the book
applies no split or a doubling.

That was survivable while `apply_splits` truncated to whole shares anyway. S5
made fractional entitlement exact and canonical, so an approximate ratio is now
the largest remaining source of share-count error, and the vendor states the
exact figure in a column the ingest was already reading.

## The two rules that are easy to get backwards

```text
A FORWARD 2:1 IS `value = 2.0`, AND THAT IS ALREADY THE SHARE MULTIPLIER
    shares_after = shares_before x ratio. No inversion. Worth stating because
    the DERIVED ratio needs one: the adjustment factor FALLS through a forward
    split, so `before/after` is the share ratio there and `after/before` would
    HALVE a position on a 2:1.

THE ACTIONS DATE IS THE EX-DATE, AND IT IS A CALENDAR DATE
    It can land on a weekend or a holiday. An event dated on a non-session
    never fires, which leaves the entitlement outstanding for the rest of the
    run, so it is snapped forward to the first real session.
```

Multiple distributions on one ticker and session are SUMMED, never overwritten:
an ordinary and a special dividend can share an ex-date, and keeping the last
row read would silently drop one.
"""
from __future__ import annotations

import bisect
from typing import Iterable, Mapping, Sequence

from sentinel.core.terminal import DIVIDEND_ACTIONS, SPLIT_ACTIONS

#: How far a derived ratio may sit from the authoritative one before the
#: disagreement is treated as a fault rather than as rounding. Splits are
#: stated in clean fractions, so a real agreement is exact to well within this;
#: anything outside it means the two sources describe different events.
SPLIT_AGREEMENT_TOLERANCE = 0.01


def snap_to_session(day: str, sessions_sorted: Sequence[str]):
    """The first trading session on or after `day`, or None past the window."""
    i = bisect.bisect_left(sessions_sorted, str(day))
    return sessions_sorted[i] if i < len(sessions_sorted) else None


def split_ratios_from_actions(rows: Iterable[Mapping],
                              sessions_sorted: Sequence[str]
                              ) -> dict[tuple[str, str], float]:
    """(ticker, session) -> authoritative SHARE ratio, no inversion."""
    out: dict[tuple[str, str], float] = {}
    for r in rows:
        if (r.get("action") or "").lower() not in SPLIT_ACTIONS:
            continue
        v = r.get("value")
        if v is None or float(v) <= 0:
            continue
        session = snap_to_session(str(r["date"]), sessions_sorted)
        if session is None:
            continue
        out[(str(r["ticker"]), session)] = float(v)
    return out


def dividends_from_actions(rows: Iterable[Mapping],
                           sessions_sorted: Sequence[str]
                           ) -> dict[tuple[str, str], float]:
    """(ticker, session) -> cash dividend per share, on the EX-DATE."""
    out: dict[tuple[str, str], float] = {}
    for r in rows:
        if (r.get("action") or "").lower() not in DIVIDEND_ACTIONS:
            continue
        v = r.get("value")
        if v is None or float(v) <= 0:
            # A dividend with no stated amount is not a zero dividend, it is an
            # unusable row. Nothing accrues — understating rather than inventing
            # a number — and `unusable_dividend_rows` counts it so the omission
            # is never silent.
            continue
        session = snap_to_session(str(r["date"]), sessions_sorted)
        if session is None:
            continue
        key = (str(r["ticker"]), session)
        out[key] = out.get(key, 0.0) + float(v)
    return out


def unusable_dividend_rows(rows: Iterable[Mapping]) -> int:
    """Dividend rows with no usable amount. Counted so the drop is visible."""
    return len(unusable_dividend_rows_detail(rows))


def unusable_dividend_rows_detail(rows: Iterable[Mapping]) -> list[dict]:
    """The same rows, NAMED, so they can be persisted as corpus anomalies.

    A count tells a certification that something was dropped; it cannot tell it
    WHICH security, on which session, and therefore whether it mattered. The
    distinction being preserved is between "no distribution" and "a
    distribution whose amount the vendor never stated" — the corpus stores 0.0
    for both, and only this record separates them.
    """
    out = []
    for r in rows:
        if (r.get("action") or "").lower() not in DIVIDEND_ACTIONS:
            continue
        v = r.get("value")
        if v is None or float(v) <= 0:
            out.append({"ticker": str(r.get("ticker")),
                        "date": str(r.get("date")),
                        "action": str(r.get("action")), "value": v})
    return out


def split_disagreements(report, authoritative: Mapping[tuple[str, str], float],
                        *, tolerance: float = SPLIT_AGREEMENT_TOLERANCE
                        ) -> list[dict]:
    """Where the DERIVED ratio and the STATED one describe different events.

    Reported, never silently resolved. The authoritative value wins — it is the
    vendor's statement of the corporate action, while the derived value is an
    inference from two prices — but a material disagreement means one of the two
    inputs is wrong about this security, and that is a fact about the corpus an
    operator has to see. Silently preferring either one turns a data problem
    into a share count nobody questions.
    """
    out = []
    for (ticker, session), stated in sorted(authoritative.items()):
        derived = (report.derived_splits or {}).get((ticker, session))
        if derived is None:
            continue
        if abs(float(derived) - float(stated)) > tolerance:
            out.append({"ticker": ticker, "session": session,
                        "stated": float(stated), "derived": float(derived)})
    return out


def splits_only_derived(report, authoritative: Mapping[tuple[str, str], float]
                        ) -> list[dict]:
    """Splits the PRICE DOMAINS show and ACTIONS has no row for.

    The other half of the disagreement, and the one that is easy to leave
    silent because the fallback handles it: with no authoritative row the
    derived ratio is used, which is the right behaviour and still means the two
    sources describe different histories for that security. Reported separately
    from a VALUE disagreement because the cause differs — a gap in ACTIONS
    coverage rather than one source being wrong about a figure — and folding
    them together would let a thin actions feed read as agreement.
    """
    return [{"ticker": t, "session": s, "derived": float(v)}
            for (t, s), v in sorted((report.derived_splits or {}).items())
            if (t, s) not in authoritative]


__all__ = ["SPLIT_AGREEMENT_TOLERANCE", "dividends_from_actions",
           "snap_to_session", "split_disagreements", "split_ratios_from_actions",
           "splits_only_derived", "unusable_dividend_rows",
           "unusable_dividend_rows_detail"]
