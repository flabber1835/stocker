"""The authoritative US-equity session calendar. DETERMINISTIC: no network.

WHY THIS EXISTS. `readiness` claimed to check that the corpus held N
CONSECUTIVE sessions and did not: it selected the most recent N distinct
sessions, counted them, and reported "N consecutive sessions available". A
corpus of 300 sessions with one deleted from the middle returned 299 sessions,
`continuity: PASS`, and `ready: True` — measured 2026-08-09.

A count cannot express consecutiveness. Only a comparison against an
INDEPENDENT expectation can, because the corpus cannot be its own witness: if a
session is missing from the corpus, the corpus does not know it should have been
there.

WHY NOT CALENDAR-DAY ADJACENCY. The obvious repair — "each session should be
one day after the last" — is wrong on every weekend and every holiday, and
"within three days" is wrong across Thanksgiving and Christmas. Inventing
holiday logic here would produce a check that fails on Good Friday and passes on
a real outage.

WHY NOT INFER THE CALENDAR FROM THE CORPUS. Using a benchmark's own bars (SPY
prints every session, so a SPY bar means a session existed) is circular in the
one case that matters: a day where the whole ingest failed has no SPY bar
either, so the gap defines itself away.

SO: `exchange_calendars`, XNYS, the same library and the same calendar the
scheduler already resolves. Not a second opinion about when the market is open.

DETERMINISM. The rules are embedded in the pinned library — no service is
called, and the same version answers the same question forever. That makes the
calendar a VERSIONED DEPENDENCY of any certification: a run that passed
readiness under one calendar version is only reproducible under that version.
`CALENDAR_VERSION` is reported so a readiness verdict names the authority it
consulted.

WHAT THIS IS NOT. It is about the CORPUS/SESSION axis only: did a trading
session produce any bars at all. It says nothing about whether a particular
SECURITY has a row on a particular session — IPOs, delistings, halts and vendor
gaps are per-security eligibility questions with their own checks, and demanding
every security on every session would fail on the first IPO.
"""
from __future__ import annotations

from datetime import date
from functools import lru_cache
from typing import Iterable, Sequence

#: The exchange whose sessions define "a trading day" for this deployment.
#: US equities, so XNYS — and the SAME identifier the scheduler resolves, so the
#: two cannot drift into disagreeing about whether a day existed.
EXCHANGE = "XNYS"


class CalendarUnavailable(RuntimeError):
    """The session calendar could not be loaded.

    Raised rather than degraded, and the caller turns it into a readiness
    FAILURE rather than a pass. A continuity check with no calendar cannot
    detect a gap, and reporting PASS in that state is precisely the defect this
    module was written to remove — silently answering a question it can no
    longer ask.
    """


@lru_cache(maxsize=1)
def _calendar():
    try:
        import exchange_calendars as xcals   # noqa: PLC0415 — heavy, load once
    except ModuleNotFoundError as exc:       # pragma: no cover - env guard
        raise CalendarUnavailable(
            "exchange_calendars is not installed, so session continuity cannot "
            "be verified. A corpus with a hole in it is indistinguishable from "
            "a complete one without it."
        ) from exc
    return xcals.get_calendar(EXCHANGE)


def calendar_version() -> str:
    """Reported alongside a readiness verdict, so the answer names its authority.

    A continuity PASS is only reproducible under the calendar that produced it;
    an unrecorded version turns a certification input into an ambient fact.
    """
    try:
        import exchange_calendars as xcals   # noqa: PLC0415
        return f"{EXCHANGE}/exchange_calendars {xcals.__version__}"
    except ModuleNotFoundError:              # pragma: no cover - env guard
        return f"{EXCHANGE}/unavailable"


def sessions_in_range(start: date | str, end: date | str) -> list[str]:
    """Every exchange session in [start, end], inclusive, as ISO dates."""
    import pandas as pd                      # noqa: PLC0415 — with the calendar

    s = _calendar().sessions_in_range(pd.Timestamp(str(start)),
                                      pd.Timestamp(str(end)))
    return [d.date().isoformat() for d in s]


def previous_sessions(end: date | str, count: int) -> list[str]:
    """The `count` sessions ending AT `end` inclusive, oldest first.

    ANCHORED AT `end` — the frontier — deliberately. Anchoring on today instead
    would diagnose a corpus as incomplete every evening between the close and
    the ingest, and during a seed it would report the entire unbuilt history as
    missing. Corpus CONSTRUCTION and corpus COMPLETENESS are different
    questions; this one is only ever asked about what has already been built.
    """
    import pandas as pd                      # noqa: PLC0415

    cal = _calendar()
    anchor = cal.date_to_session(pd.Timestamp(str(end)), direction="previous")
    # `count - 1` steps back from the anchor, which is itself the last session.
    idx = cal.sessions.get_loc(anchor)
    lo = max(0, idx - (count - 1))
    return [d.date().isoformat() for d in cal.sessions[lo:idx + 1]]


def missing_sessions(expected: Sequence[str], actual: Iterable[str]) -> list[str]:
    """Sessions the calendar says existed and the corpus does not hold.

    A LIST, not a boolean. "continuity=false" tells an operator nothing they can
    act on; two dates tell them exactly which fetch to re-run.
    """
    have = {str(a) for a in actual}
    return [s for s in expected if s not in have]


def unexpected_sessions(expected: Sequence[str], actual: Iterable[str]) -> list[str]:
    """Sessions the corpus holds that the calendar says did not exist.

    Reported separately and NOT treated as a gap, because it is a different
    fault with a different cause — a vendor emitting a weekend row, or a
    calendar/vendor disagreement about a half-day — and neither is a hole in the
    history. Folding them together would let one mask the other.
    """
    want = set(expected)
    return sorted({str(a) for a in actual} - want)


__all__ = ["CalendarUnavailable", "EXCHANGE", "calendar_version",
           "missing_sessions", "previous_sessions", "sessions_in_range",
           "unexpected_sessions"]
