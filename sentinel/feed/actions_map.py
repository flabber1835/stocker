"""SHARADAR/ACTIONS -> authoritative split ratios and dividends. PURE.

The Sentinel-specific ACTIONS mapping lives here, while split orientation is a
shared pure rule in `stock_strategy_shared.split_reconciliation`.  Sentinel may
not import a retired Stocker SERVICE, and the production and canonical replay
paths may not own separate share-count semantics.

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

## The orientation rule that is easy to get backwards

```text
ACTIONS `value` IS NOT BY ITSELF AN ORIENTATION WITNESS
    Sharadar has emitted both canonical share multipliers and reverse-split
    denominators. A value greater than one can therefore mean either a forward
    multiplier or the denominator of a reverse event. The independently
    derived price-domain ratio decides between `value` and `1/value`. If it
    agrees with neither, the event is unresolved and is not applied.

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

from sentinel.core.terminal import DIVIDEND_ACTIONS, SHARE_SPLIT_ACTIONS
from stock_strategy_shared.split_reconciliation import (
    SPLIT_AGREEMENT_TOLERANCE,
    SPLIT_AUTHORITATIVE_APPLIED,
    SPLIT_CORROBORATED_BRIDGED,
    SPLIT_CORROBORATED_DIRECT,
    SPLIT_CORROBORATED_QUANTIZED,
    SPLIT_CORROBORATED_SHIFTED,
    SPLIT_DERIVED_ONLY,
    SPLIT_PENDING_BRIDGE,
    SPLIT_RESOLVED_NO_EVENT,
    SPLIT_UNRESOLVED,
    SplitAuthority,
    resolve_split_orientation,
)


def snap_to_session(day: str, sessions_sorted: Sequence[str]):
    """The first trading session on or after `day`, or None past the window."""
    i = bisect.bisect_left(sessions_sorted, str(day))
    return sessions_sorted[i] if i < len(sessions_sorted) else None


def split_ratios_from_actions(rows: Iterable[Mapping],
                              sessions_sorted: Sequence[str]
                              ) -> dict[tuple[str, str], float]:
    """(ticker, session) -> raw positive ACTIONS value.

    The direct value is corroborated later against the independent price-domain
    ratio. ``adrratiosplit`` rows are not included because they describe the
    depositary ratio rather than a listed-share transformation.
    """
    out, _ambiguous = split_rows_from_actions(rows, sessions_sorted)
    return out


def split_rows_from_actions(rows: Iterable[Mapping],
                            sessions_sorted: Sequence[str]
                            ) -> tuple[dict[tuple[str, str], float], list[dict]]:
    """Return unambiguous split values plus explicit multiplicity evidence.

    Only Sharadar ``split`` rows are listed-instrument share authority.
    ``adrratiosplit`` is a distinct depositary-ratio action and remains source
    provenance. Picking the first/last of distinct stock-split rows or
    multiplying them would invent economics, so those remain explicit.
    """
    from sentinel.feed.action_source import source_row_id

    grouped: dict[tuple[str, str], dict[str, float | None]] = {}
    for r in rows:
        if (r.get("action") or "").lower() not in SHARE_SPLIT_ACTIONS:
            continue
        v = r.get("value")
        session = snap_to_session(str(r["date"]), sessions_sorted)
        if session is None:
            continue
        identity = str(r.get("source_row_id") or source_row_id(r))
        try:
            usable = None if v is None or float(v) <= 0 else float(v)
        except (TypeError, ValueError):
            usable = None
        grouped.setdefault((str(r["ticker"]), session), {})[identity] = usable
    out: dict[tuple[str, str], float] = {}
    ambiguous = []
    for key, identities in sorted(grouped.items()):
        values = list(identities.values())
        distinct = {value for value in values if value is not None}
        if (not any(value is None for value in values)
                and len(distinct) == 1):
            out[key] = distinct.pop()
        else:
            ambiguous.append({
                "ticker": key[0], "session": key[1],
                "distinct_rows": len(identities),
                "distinct_values": sorted(distinct),
                "invalid_value_rows": sum(v is None for v in values),
            })

    session_index = {str(session): i
                     for i, session in enumerate(sessions_sorted)}
    previous = {}
    collisions = set()
    for key, value in sorted(out.items()):
        i = session_index.get(key[1])
        if i is None or i == 0:
            continue
        probe = (key[0], str(sessions_sorted[i - 1]))
        if probe in previous:
            collisions.add(probe)
        previous[probe] = (key, value)
    for probe in collisions:
        previous.pop(probe, None)
    return SplitAuthority(
        out, previous_session_candidates=previous), ambiguous


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


def split_disagreements(report, authoritative: Mapping[tuple[str, str], float]
                        ) -> list[dict]:
    """Where the DERIVED ratio and the STATED one describe different events.

    Reported, never silently resolved. Neither value wins: ACTIONS states the
    direct listed-share multiplier while the price domains independently
    corroborate it, and a material disagreement means one input is wrong. The
    shared resolver applies no transformation and this function makes the
    disagreement durable instead of turning it into a share count nobody
    questions.

    THE UNSNAPPED DERIVED RATIO IS THE ONE COMPARED, and that is the fix for a
    real blind spot. `split_ratio_from_domains` snaps its inference to a
    near-integer so the FALLBACK produces a reconcilable share count — but 1.48
    snaps to 1.0, which is the "no split" value, so the derived side recorded
    nothing and a stated 1.5 had nothing to disagree with. The check silently
    stopped checking on exactly the ratios it was added for. Snapping is also
    wrong in the other direction here: `round(1.5)` is 2, so every legitimate
    3:2 would have read as a disagreement.
    """
    out = []
    unsnapped = getattr(report, "derived_splits_unsnapped", None) or {}
    snapped = getattr(report, "derived_splits", None) or {}
    dispositions = getattr(report, "split_dispositions", None) or {}
    for (ticker, session), stated in sorted(authoritative.items()):
        item = dispositions.get((ticker, session))
        if item is not None and item.get("disposition") != SPLIT_UNRESOLVED:
            continue
        derived = unsnapped.get((ticker, session))
        source = "unsnapped"
        if derived is None:
            derived, source = snapped.get((ticker, session)), "snapped"
        if derived is None and item is not None:
            derived, source = item.get("derived"), "stream"
        if derived is None:
            continue
        if item is None:
            _ratio, disposition = resolve_split_orientation(
                float(stated), float(derived))
            if disposition != SPLIT_UNRESOLVED:
                continue
        out.append({"ticker": ticker, "session": session,
                    "stated": float(stated), "derived": float(derived),
                    "derived_source": source})
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
    seam = getattr(report, "seam_splits_uncorroborated", None) or {}
    dispositions = getattr(report, "split_dispositions", None) or {}
    return [{"ticker": t, "session": s, "derived": float(v)}
            for (t, s), v in sorted((report.derived_splits or {}).items())
            if (t, s) not in authoritative and (t, s) not in seam
            and ((t, s) not in dispositions
                 or dispositions[(t, s)].get("disposition")
                 == SPLIT_DERIVED_ONLY)]


__all__ = ["SPLIT_AGREEMENT_TOLERANCE", "SPLIT_AUTHORITATIVE_APPLIED",
           "SPLIT_CORROBORATED_BRIDGED", "SPLIT_CORROBORATED_DIRECT",
           "SPLIT_CORROBORATED_QUANTIZED", "SPLIT_CORROBORATED_SHIFTED",
           "SPLIT_DERIVED_ONLY", "SPLIT_PENDING_BRIDGE",
           "SPLIT_RESOLVED_NO_EVENT", "SPLIT_UNRESOLVED",
           "dividends_from_actions",
           "resolve_split_orientation",
           "snap_to_session", "split_disagreements", "split_ratios_from_actions",
           "split_rows_from_actions",
           "splits_only_derived", "unusable_dividend_rows",
           "unusable_dividend_rows_detail"]
