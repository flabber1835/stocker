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

from sentinel.core.terminal import DIVIDEND_ACTIONS, SPLIT_ACTIONS

#: How far a derived ratio may sit from the authoritative one before the
#: disagreement is treated as a fault rather than as rounding. Splits are
#: stated in clean fractions, so a real agreement is exact to well within this;
#: anything outside it means the two sources describe different events.
SPLIT_AGREEMENT_TOLERANCE = 0.01

SPLIT_AUTHORITATIVE_APPLIED = "authoritative_applied"
SPLIT_CORROBORATED_DIRECT = "corroborated_direct"
SPLIT_CORROBORATED_RECIPROCAL = "corroborated_reciprocal"
SPLIT_UNRESOLVED = "unresolved"


def _ratios_close(left: float, right: float, tolerance: float) -> bool:
    return abs(float(left) - float(right)) <= (
        tolerance * max(abs(float(left)), abs(float(right)), 1e-12))


def resolve_split_orientation(
        stated: float, derived: float | None, *,
        tolerance: float = SPLIT_AGREEMENT_TOLERANCE) -> tuple[float, str]:
    """Return the canonical post/pre multiplier and its evidence disposition.

    The price-domain ratio is independent orientation evidence. Agreement with
    ``stated`` preserves a forward multiplier; agreement with ``1/stated``
    proves that ACTIONS supplied a reverse-split denominator. A material value
    greater than one with no usable price witness is ambiguous and fails closed
    as ``1.0``. Values at or below one are already in canonical reverse-split
    form and may be applied from ACTIONS alone.
    """
    value = float(stated)
    if value <= 0:
        return 1.0, SPLIT_UNRESOLVED
    evidence = None if derived is None else float(derived)
    if evidence is not None and evidence > 0:
        if _ratios_close(evidence, value, tolerance):
            return value, SPLIT_CORROBORATED_DIRECT
        reciprocal = 1.0 / value
        if _ratios_close(evidence, reciprocal, tolerance):
            # Vendor reverse denominators are sometimes slightly noisy
            # (30.003, 9.00009, 6.99986).  Once independent price evidence
            # proves reciprocal orientation, snap a near-integral denominator
            # so a 1-for-30 event is represented as exactly 1/30.
            denominator = round(value)
            if (denominator > 0
                    and _ratios_close(value, denominator, tolerance)
                    and _ratios_close(evidence, 1.0 / denominator, tolerance)):
                reciprocal = 1.0 / denominator
            return reciprocal, SPLIT_CORROBORATED_RECIPROCAL
        if not _ratios_close(evidence, 1.0, tolerance):
            return 1.0, SPLIT_UNRESOLVED
    if value <= 1.0:
        return value, SPLIT_AUTHORITATIVE_APPLIED
    return 1.0, SPLIT_UNRESOLVED


def snap_to_session(day: str, sessions_sorted: Sequence[str]):
    """The first trading session on or after `day`, or None past the window."""
    i = bisect.bisect_left(sessions_sorted, str(day))
    return sessions_sorted[i] if i < len(sessions_sorted) else None


def split_ratios_from_actions(rows: Iterable[Mapping],
                              sessions_sorted: Sequence[str]
                              ) -> dict[tuple[str, str], float]:
    """(ticker, session) -> raw positive ACTIONS value.

    Orientation is deliberately deferred until the normaliser has the
    independent price-domain ratio. Treating this map as canonical is the
    historical defect that multiplied a 1-for-30 holding by 30.
    """
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
    for (ticker, session), stated in sorted(authoritative.items()):
        derived = unsnapped.get((ticker, session))
        source = "unsnapped"
        if derived is None:
            derived, source = snapped.get((ticker, session)), "snapped"
        if derived is None:
            continue
        _canonical, disposition = resolve_split_orientation(
            float(stated), float(derived), tolerance=tolerance)
        if disposition == SPLIT_UNRESOLVED:
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
    return [{"ticker": t, "session": s, "derived": float(v)}
            for (t, s), v in sorted((report.derived_splits or {}).items())
            if (t, s) not in authoritative and (t, s) not in seam]


__all__ = ["SPLIT_AGREEMENT_TOLERANCE", "SPLIT_AUTHORITATIVE_APPLIED",
           "SPLIT_CORROBORATED_DIRECT", "SPLIT_CORROBORATED_RECIPROCAL",
           "SPLIT_UNRESOLVED", "dividends_from_actions",
           "resolve_split_orientation",
           "snap_to_session", "split_disagreements", "split_ratios_from_actions",
           "splits_only_derived", "unusable_dividend_rows",
           "unusable_dividend_rows_detail"]
