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

import datetime as _dt
from dataclasses import dataclass
from datetime import date
from functools import lru_cache
from typing import Iterable, Optional, Sequence

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


def next_session(after: date | str) -> str:
    """The first XNYS session strictly after ``after``.

    Decision close ``t`` becomes executable at the next eligible session, not
    at the next calendar day and never on ``t`` itself. Keeping this beside the
    continuity calendar prevents a CLI from inventing a separate weekend and
    holiday rule at the broker boundary.
    """
    import pandas as pd                      # noqa: PLC0415

    anchor = pd.Timestamp(str(after)) + pd.Timedelta(days=1)
    return _calendar().date_to_session(
        anchor, direction="next").date().isoformat()


# ── freshness, in SESSIONS ───────────────────────────────────────────────────
#
# `readiness` used to answer this in calendar days:
#
#     MAX_FRONTIER_AGE_DAYS = 4          # "a weekend plus a holiday"
#     if (today - frontier).days > 4: FAIL
#
# A day budget cannot express "a session I should have". It must be wide enough
# for the longest legitimate gap, and at that width it also swallows real
# outages inside an ordinary week — a Tuesday frontier read on Friday scores 3
# and passes with Wednesday and Thursday missing. Narrowing it only changes
# WHICH outages fit; it detects none of them, and starts failing over Christmas.
# The number is wrong in both directions simultaneously, which is the signature
# of a question being asked in the wrong units.
#
# The exact question — "is the frontier the latest session that has already
# CLOSED?" — needs no slack at all. The calendar knows which days were sessions
# and the clock knows which are finished, so a market that did not trade cannot
# make the corpus stale and a session that traded and is missing is stale by
# exactly one session.

#: The ordinary-session close, retained as display vocabulary only. It is NOT a
#: timing authority: XNYS half-days close at 13:00 ET, and every decision below
#: reads the pinned exchange calendar's actual per-session schedule.
SESSION_CLOSE_HOUR_ET = 16

#: IANA rather than a fixed offset: the ET/EDT transition moves, and a hardcoded
#: -05:00 would mis-classify the hour after the close for eight months a year.
EXCHANGE_TZ = "America/New_York"


@dataclass(frozen=True)
class Freshness:
    """Is the corpus current, measured against the exchange rather than a clock."""

    #: The latest XNYS session that has already closed. None when unevaluable.
    expected_session: Optional[str]
    frontier: Optional[str]
    #: Sessions that closed and are not in the corpus, oldest first. The LIST,
    #: not a count: "stale" tells an operator nothing they can act on, three
    #: dates tell them exactly which fetches to re-run.
    missing_sessions: tuple = ()
    #: False when the calendar could not be consulted or there is no frontier.
    #: A third state, deliberately — see `fresh`.
    evaluable: bool = True
    #: The corpus holds something the exchange cannot account for: a session
    #: dated in the FUTURE, or a date XNYS never held at all. A different fault
    #: with a different cause (a wrong clock, or a vendor emitting a weekend
    #: row) and a different remedy — re-running the fetch would not change it —
    #: so it is reported on its own rather than folded into staleness.
    #:
    #: NOT the same as holding today's session before its close. That is EARLY,
    #: and early is fine: the session exists, its date has arrived, and the
    #: vendor simply published ahead of the 16:00 boundary this module uses to
    #: decide what is OWED. Conflating the two made a perfectly current corpus
    #: read as anomalous every time an ingest landed before the close.
    ahead: bool = False
    #: The frontier is a real session later than the latest closed one. Benign,
    #: reported so the distinction above is visible rather than implied.
    early: bool = False
    reason: str = ""

    @property
    def sessions_behind(self) -> int:
        return len(self.missing_sessions)

    @property
    def fresh(self) -> bool:
        """UNEVALUABLE IS NOT FRESH. NEITHER IS ANOMALOUS.

        The rule the crash brake had to learn: one boolean cannot answer both
        *the evidence says current* and *there is no evidence*. Defaulting the
        second to True would let a missing calendar certify a corpus nobody
        checked.

        `ahead` is excluded for the same reason one step along. It is not
        staleness — nothing is missing — but a frontier the exchange cannot
        account for is not a green light either, and a caller reading only this
        property would take it as one. The three states stay separable through
        `evaluable` / `ahead` / `missing_sessions`; what they must never do is
        collapse into a True.
        """
        return self.evaluable and not self.missing_sessions and not self.ahead

    def to_dict(self) -> dict:
        return {"fresh": self.fresh, "evaluable": self.evaluable,
                "expected_session": self.expected_session,
                "frontier": self.frontier,
                "sessions_behind": self.sessions_behind,
                "missing_sessions": list(self.missing_sessions),
                "ahead": self.ahead, "early": self.early,
                "reason": self.reason}


def session_window(session: date | str) -> tuple[_dt.datetime, _dt.datetime]:
    """The calendar-defined XNYS open/close interval in exchange-local time.

    A named effective session is an authority, not merely a date. Resolving its
    schedule here keeps preparation freshness and the broker-submit gateway on
    one clock, including 13:00 ET half-day closes. A non-session is refused
    rather than silently moved to a neighbouring trading day.
    """
    import pandas as pd                      # noqa: PLC0415 — with the calendar
    from zoneinfo import ZoneInfo             # noqa: PLC0415

    label = pd.Timestamp(str(session))
    cal = _calendar()
    if not cal.is_session(label):
        raise ValueError(f"{session} is not an {EXCHANGE} session")
    tz = ZoneInfo(EXCHANGE_TZ)
    opened = cal.session_open(label).to_pydatetime().astimezone(tz)
    closed = cal.session_close(label).to_pydatetime().astimezone(tz)
    return opened, closed


def latest_closed_session(now_et=None) -> str:
    """The most recent XNYS session whose close has passed.

    Anchored on the CLOSE, not on the date. Anchoring on today would report
    every corpus as a session behind from midnight until the evening ingest —
    true for most of every weekday, which is an alarm nobody reads.
    """
    import pandas as pd                      # noqa: PLC0415

    now = _now_et(now_et)
    cal = _calendar()
    today = pd.Timestamp(now.date())

    # On a session date, today's session is owed exactly when its own scheduled
    # close has passed. A hard-coded 16:00 boundary delays half-day preparation
    # and, worse, can let an execution gateway believe a 13:00-close session is
    # still open. On a non-session date the most recent prior session has, by
    # definition, already closed.
    candidate = cal.date_to_session(today, direction="previous")
    if candidate.date() == now.date():
        _opened, closed = session_window(candidate.date().isoformat())
        if now < closed:
            index = cal.sessions.get_loc(candidate)
            if index <= 0:                                  # pragma: no cover
                raise CalendarUnavailable(
                    "the XNYS calendar has no session before the current open")
            candidate = cal.sessions[index - 1]
    return candidate.date().isoformat()


def freshness(frontier: Optional[str], now_et=None) -> Freshness:
    """Compare the corpus frontier against the sessions that have closed."""
    if not frontier:
        return Freshness(
            expected_session=None, frontier=None, evaluable=False,
            reason="the corpus is empty, so there is no frontier to judge. "
                   "That is a LOAD failure, not a staleness one, and the "
                   "sessions check reports it in its own right.")
    try:
        expected = latest_closed_session(now_et)
    except CalendarUnavailable as exc:
        return Freshness(
            expected_session=None, frontier=str(frontier), evaluable=False,
            reason=f"the session calendar is unavailable, so freshness cannot "
                   f"be established: {exc}. UNKNOWN rather than fresh — a check "
                   f"that cannot ask its question must not answer it.")

    frontier = str(frontier)
    if frontier > expected:
        # THREE different things live past the close boundary, and only two of
        # them are faults. Separating them matters because the first version of
        # this treated all three as anomalous, which flagged every corpus whose
        # ingest happened to land before 16:00 ET.
        today = _now_et(now_et).date().isoformat()
        if frontier not in sessions_in_range(frontier, frontier):
            return Freshness(
                expected_session=expected, frontier=frontier, ahead=True,
                reason=f"the corpus frontier {frontier} is not an XNYS session "
                       f"at all — the vendor emitted a row for a day the "
                       f"exchange did not hold. Not a staleness fault; "
                       f"re-running the fetch would not change it.")
        if frontier > today:
            return Freshness(
                expected_session=expected, frontier=frontier, ahead=True,
                reason=f"the corpus holds {frontier}, a session in the FUTURE "
                       f"relative to {today}. A clock is wrong — this system's "
                       f"or the vendor's. Not a staleness fault.")
        _opened, closed = session_window(frontier)
        return Freshness(
            expected_session=expected, frontier=frontier, early=True,
            reason=f"frontier {frontier} is today's session, published before "
                   f"its {closed:%H:%M} ET close. Current, and "
                   f"ahead of what is owed rather than behind it.")

    missing = tuple(s for s in sessions_in_range(frontier, expected)
                    if s > frontier)
    if not missing:
        return Freshness(expected_session=expected, frontier=frontier,
                         reason=f"frontier {frontier} is the latest closed "
                                f"XNYS session")
    return Freshness(
        expected_session=expected, frontier=frontier, missing_sessions=missing,
        reason=f"{len(missing)} session(s) have closed since the frontier "
               f"{frontier} and are not in the corpus: "
               f"{', '.join(missing[:8])}"
               f"{f' (+{len(missing) - 8} more)' if len(missing) > 8 else ''}")


def _now_et(now_et=None):
    """Whatever the caller supplied, in exchange time.

    An ISO string is accepted so a test can name a moment exactly; a naive one
    is INTERPRETED as exchange-local rather than UTC, because every date this
    module reasons about is an exchange date and silently shifting by five hours
    would move the 16:00 boundary across a day end.
    """
    from zoneinfo import ZoneInfo             # noqa: PLC0415

    tz = ZoneInfo(EXCHANGE_TZ)
    if now_et is None:
        return _dt.datetime.now(tz)
    if isinstance(now_et, str):
        now_et = _dt.datetime.fromisoformat(now_et)
    if now_et.tzinfo is None:
        return now_et.replace(tzinfo=tz)
    return now_et.astimezone(tz)


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


__all__ = ["CalendarUnavailable", "EXCHANGE", "EXCHANGE_TZ", "Freshness",
           "SESSION_CLOSE_HOUR_ET", "calendar_version", "freshness",
           "latest_closed_session", "missing_sessions", "next_session",
           "previous_sessions", "session_window",
           "sessions_in_range", "unexpected_sessions"]
