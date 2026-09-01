"""Is the corpus fit for Wealth Core to plan on? Answered per CHECK, not per row.

`docs/sentinel-deployment.md` §8 says it plainly: **"126 rows" is not the test.**
A row count is satisfied by 126 rows of anything — a corpus with no as-traded
price, or with a three-week hole in the middle, or covering 400 securities
because identity resolution silently dropped the rest. Each of those produces a
plan, and the plan is wrong in a way nothing downstream reports.

So each clause of the contract is its own named check with its own verdict, and
the command fails on the FIRST unmet one while still reporting every result. An
operator needs to know which clause failed, not that "readiness = false".

## The checks, and what each one is actually protecting

```text
sessions            a canonical trading calendar exists at all
continuity          126 CONSECUTIVE sessions to the frontier — a gap in the
                    middle satisfies a count and breaks momentum
freshness           the frontier is recent. A stale corpus plans yesterday's
                    book with today's confidence
signal domain       SEP.close present: momentum and the trailing-stop peak
raw close           as-traded present: marking and the 4% admission size
raw open            as-traded open present: every fill happens at one
volume              ADV20 and signal dollar volume, both eligibility gates
identity            securities resolve to permatickers; unresolved bars are
                    dropped, and a mass drop looks exactly like a thin market
issuer keys         an issuer group per security, or the GOOG/GOOGL defect
                    cannot be detected at all
actions             corporate actions present near the frontier
corpus version      a published version exists for a decision to RECORD
corpus coherence    no unpublished candidate intersects the production causal
                    closure; safely old candidates remain invisible, reported,
                    and strict full-history certification-blocking
```

`WARN` exists for the one case that is genuinely a judgement call — coverage
below the preferred 252-session window but above the required 126. Everything
else is PASS or FAIL, because a data contract that can be partially satisfied is
one nobody enforces.
"""
from __future__ import annotations

import datetime as _dt
import math
import statistics
from dataclasses import dataclass, field
from typing import Optional

from sentinel.feed import calendar as _cal
from sentinel.feed import publication as _publication
from sentinel.feed.requirements import PREFERRED_SESSIONS, REQUIRED_SPY_SESSIONS
from stock_strategy_shared.wealth_core.eligibility import EligibilityConfig
from stock_strategy_shared.wealth_core.signals import (
    LONG_LOOKBACK_SESSIONS,
    REQUIRED_CLOSES,
)

#: The engine's own requirement, not a number chosen here: `momentum` reads
#: closes[-(LONG_LOOKBACK_SESSIONS + 1)], so 127 closes are needed before a
#: security can be scored at all.
REQUIRED_SESSIONS = REQUIRED_CLOSES

# The newest cross-section is compared with the recent, production-shaped
# population rather than with an absolute ticker count.  IPOs/delistings make an
# exact equality wrong; losing more than one fifth of the population in one
# ingest is not an ordinary market event and must not establish a frontier.
FRONTIER_POPULATION_LOOKBACK = 20
MIN_FRONTIER_POPULATION_RATIO = 0.80

# MAX_FRONTIER_AGE_DAYS IS GONE, not retuned. It was 4 calendar days — "a
# weekend plus a holiday" — and a day budget cannot express "a session I should
# have": at the width a Thanksgiving weekend needs, a Tuesday frontier read on
# Friday scored 3 and passed with Wednesday and Thursday missing. See
# `calendar.freshness`, which asks the exact question instead. Deliberately not
# left importable at a smaller value: the next freshness question would be
# answered in days again.

PASS, WARN, FAIL = "PASS", "WARN", "FAIL"

#: PUBLISHED IS WHAT READABLE MEANS, and readiness must measure what a reader
#: sees. Bound once, from the single definition in `publication`, and
#: interpolated into every bar query below. Universe current-state reads use the
#: publication-maintained bounded projection instead of replaying raw snapshots.
_VISIBLE_BARS = _publication.visible_predicate("b")


def _window_start(frontier: str) -> str:
    """Earliest calendar date the continuity window can reach back to.

    Bounds the SQL scan so a 20-year corpus is not read to check one year. A
    generous multiplier rather than a tight one: ~252 sessions is ~366 calendar
    days, and under-reaching would manufacture the very gaps this check hunts.
    """
    return (_dt.date.fromisoformat(frontier)
            - _dt.timedelta(days=int(PREFERRED_SESSIONS * 1.8))).isoformat()


@dataclass
class Check:
    name: str
    status: str
    detail: str
    value: object = None

    @property
    def ok(self) -> bool:
        return self.status != FAIL


@dataclass
class Readiness:
    checks: list[Check] = field(default_factory=list)

    def add(self, name, status, detail, value=None) -> Check:
        c = Check(name, status, detail, value)
        self.checks.append(c)
        return c

    @property
    def ready(self) -> bool:
        return all(c.ok for c in self.checks) and bool(self.checks)

    @property
    def failures(self) -> list[Check]:
        return [c for c in self.checks if c.status == FAIL]


# ── persisted verdicts ───────────────────────────────────────────────────────
#
# A page must not compute a contract. See `save_snapshot` below and the schema
# comment on `sentinel_readiness_snapshots`.

#: Beyond this a verdict describes a corpus that has since been through a daily
#: ingest, so it is reported but must not authorise anything. One session's
#: worth plus margin — the question a readiness verdict answers is "may we plan
#: on this corpus", and the corpus changes once a day.
SNAPSHOT_TRUST_SECONDS = 26 * 3600


@dataclass(frozen=True)
class ReadinessSnapshot:
    """A verdict somebody else computed, and how old it is."""

    computed_at: object
    ready: bool
    checks_passed: int
    checks_total: int
    checks: list
    age_seconds: float

    @property
    def stale(self) -> bool:
        return self.age_seconds > SNAPSHOT_TRUST_SECONDS

    @property
    def trustworthy(self) -> bool:
        """What a caller should GATE on. `ready` is what was measured.

        Two fields, deliberately. Collapsing them either discards a usable
        verdict the moment it ages, or lets a day-old PASS authorise a bootstrap
        against a corpus that has been re-ingested since. What was measured does
        not change with age; whether it may still be acted on does.
        """
        return self.ready and not self.stale

    @property
    def failures(self) -> list:
        return [c for c in self.checks if c.get("status") == FAIL]

    def to_dict(self) -> dict:
        return {"computed_at": (self.computed_at.isoformat()
                                if self.computed_at else None),
                "age_seconds": round(self.age_seconds, 1),
                "ready": self.ready, "stale": self.stale,
                "trustworthy": self.trustworthy,
                "checks_passed": self.checks_passed,
                "checks_total": self.checks_total,
                "failures": self.failures}


def save_snapshot(conn, result: "Readiness") -> None:
    """Persist a verdict so a page never has to compute one.

    Called wherever the check ALREADY runs — `check-data` computes a full
    verdict and prints it to a terminal that scrolls. Persisting it costs one
    insert and is the entire supply side of this feature.

    `value` is dropped from the stored form: it holds whatever each check found
    useful, including the terminal-accounting dict and a full missing-session
    list, and none of it is read by a reader that has the name, the status and
    the detail. A snapshot that grows without bound is a snapshot nobody keeps.
    """
    import json

    payload = [{"name": c.name, "status": c.status, "detail": c.detail}
               for c in result.checks]
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO sentinel_readiness_snapshots (ready, checks_passed,"
            " checks_total, checks) VALUES (%s,%s,%s,%s)",
            (result.ready, sum(1 for c in result.checks if c.ok),
             len(result.checks), json.dumps(payload)))
    conn.commit()


def latest_snapshot(conn) -> Optional[ReadinessSnapshot]:
    """The most recent verdict, or None if nothing has ever computed one.

    NONE IS NOT NOT-READY. "We have not asked" and "the corpus failed a clause"
    are different facts, and reporting the first as the second says a corpus
    failed a check it was never measured against — the same conflation the
    ownership readers had to have removed.
    """
    import json

    with conn.cursor() as cur:
        cur.execute(
            "SELECT computed_at, ready, checks_passed, checks_total, checks,"
            " EXTRACT(EPOCH FROM (NOW() - computed_at))"
            " FROM sentinel_readiness_snapshots"
            " ORDER BY computed_at DESC, snapshot_id DESC LIMIT 1")
        row = cur.fetchone()
    if row is None:
        return None
    checks = row[4] if isinstance(row[4], list) else json.loads(row[4] or "[]")
    return ReadinessSnapshot(
        computed_at=row[0], ready=bool(row[1]), checks_passed=int(row[2]),
        checks_total=int(row[3]), checks=checks, age_seconds=float(row[5]))


def _q1(conn, sql, params=()):
    with conn.cursor() as cur:
        cur.execute(sql, params)
        row = cur.fetchone()
    return row[0] if row else None


def _add_version_checks(conn, r: "Readiness") -> None:
    """`corpus version` and `corpus coherence` — two faults, two verdicts.

    Deliberately NOT one check. They have different causes and different
    remedies: a missing version means nothing has ever been published (a corpus
    built by hand, or one predating provenance), while an incoherence means a
    specific ingest committed rows and then failed to publish them. Folding them
    together would let the common one mask the dangerous one.
    """
    publication = _publication
    try:
        report = publication.operational_coherence(conn, persist=True)
    except Exception as exc:                              # noqa: BLE001
        # FAIL, never skip. A visibility rule that cannot be evaluated has not
        # been satisfied, and every count in this report is scoped by it.
        r.add("corpus coherence", FAIL,
              f"production operational coherence could not be evaluated: {exc!r}. Every other "
              f"check here measures the PUBLISHED corpus, so none of them can "
              f"be trusted until this one answers.", None)
        return

    if report.coherent:
        historical = len(report.historical_only)
        detail = "no unpublished candidate intersects production dependencies"
        if historical:
            detail += (f"; {historical} unpublished run(s) are durably "
                       "classified historical-only and still block full certification")
        r.add("corpus coherence", PASS, detail, report.to_dict())
    else:
        r.add("corpus coherence", FAIL,
              f"{len(report.blocking)} unpublished ingest run(s) intersect "
              f"the production dependency closure: "
              f"{[item.run_id for item in report.blocking]}. Candidate rows "
              f"are INVISIBLE; reconcile a covering retry and never publish "
              f"unresolved evidence merely to clear this readiness failure.",
              report.to_dict())

    published = publication.current(conn)
    if published is not None:
        r.add("corpus version", PASS,
              f"v{published.version} (previous "
              f"{published.previous_version})", published.version)
        return

    stamped = sum(int(_q1(
        conn, f"SELECT COUNT(*) FROM {table}"
              " WHERE last_written_run_id IS NOT NULL") or 0)
        for table in ("sentinel_bars", "sentinel_actions",
                      "sentinel_action_observations",
                      "sentinel_spy_total_return", "sentinel_defensive_bars",
                      "sentinel_universe",
                      "sentinel_bar_split_repairs",
                      "sentinel_corpus_anomalies"))
    if stamped:
        # Covered by the coherence FAIL above; named separately so the operator
        # sees the consequence as well as the cause.
        r.add("corpus version", FAIL,
              "the corpus has never been published, so no decision can record "
              "a data_version — and a divergence report could not then tell a "
              "replay disagreement apart from a vendor restatement.", None)
    else:
        # A corpus written entirely without provenance: a hand-built fixture, or
        # one loaded before `last_written_run_id` existed. Every row is visible
        # and the corpus is usable; what is missing is the ability to STAMP a
        # decision. WARN rather than FAIL — refusing here would make an upgrade
        # look like data loss, which is the same reason NULL rows stay visible.
        r.add("corpus version", WARN,
              "no corpus version has ever been published and no row carries an "
              "ingest id. The corpus is readable, but a decision made on it "
              "cannot record a data_version. Run an ingest to publish one.",
              None)


def check_readiness(conn, *, today: Optional[str] = None,
                    cfg: EligibilityConfig | None = None) -> Readiness:
    """Every clause of the §8 contract, against Sentinel's own corpus."""
    cfg = cfg or EligibilityConfig()
    r = Readiness()
    # Operational callers that omit --today ask whether the corpus is ready
    # now, including whether today's XNYS session has closed. A date-only
    # default silently means midnight ET and can therefore pass yesterday's
    # frontier after the close while authority gates correctly refuse it.
    today = today or _dt.datetime.now(_dt.timezone.utc).isoformat()

    # ── the corpus version, BEFORE anything is measured ──────────────────────
    # Every number below describes what a READER sees, and what a reader sees is
    # decided by publication. Measuring first and versioning afterwards would
    # report a frontier the engine cannot load.
    _add_version_checks(conn, r)

    # THE VISIBLE frontier, not the physical one. `latest_session` answers where
    # an ingest RESUMES and is deliberately unfiltered; using it here would print
    # a date the loader will not read and make an unpublished ingest look like a
    # healthy fetch.
    frontier = _q1(conn, "SELECT MAX(session) FROM sentinel_bars b"
                         f" WHERE {_VISIBLE_BARS}")
    if frontier is None:
        r.add("sessions", FAIL,
              "the corpus is EMPTY. Run `feed-seed`; Wealth Core cannot plan "
              "from nothing, and an empty corpus reads downstream as a market "
              "with no eligible securities rather than as a missing load.")
        return r
    frontier = str(frontier)

    # Session DEPTH is an operational warmup fact, not a lifetime corpus
    # statistic.  The old COUNT(DISTINCT session) filtered every visible bar in
    # the ~23M-row relation and was repeated by preparation guards.  Read only
    # the deliberately generous recent window that continuity already needs,
    # and reuse the same session axis below.  Publication visibility is kept
    # byte-for-byte identical, so rows from an unpublished ingest stay hidden.
    with conn.cursor() as cur:
        cur.execute("SELECT DISTINCT session FROM sentinel_bars b"
                    " WHERE session >= %s"
                    f"   AND {_VISIBLE_BARS} ORDER BY session",
                    (_window_start(frontier),))
        actual = [str(x[0]) for x in cur.fetchall()]
    total = len(actual)
    r.add("sessions", PASS,
          f"{total:,} visible sessions in the bounded readiness window to "
          f"{frontier}", total)

    # A single valid bar used to establish the newest session and barely moved
    # the 127-session aggregate domain percentages.  Compare the frontier's
    # security population with the preceding sessions so a truncated last page
    # cannot masquerade as a tradeable close.
    with conn.cursor() as cur:
        cur.execute(
            "SELECT session, COUNT(DISTINCT security_id) FROM sentinel_bars b"
            " WHERE session <= %s"
            f"   AND {_VISIBLE_BARS}"
            " GROUP BY session ORDER BY session DESC LIMIT %s",
            (frontier, FRONTIER_POPULATION_LOOKBACK + 1))
        populations = [(str(s), int(n)) for s, n in cur.fetchall()]
    frontier_population = populations[0][1] if populations else 0
    baseline_counts = [n for _s, n in populations[1:]]
    if not baseline_counts:
        r.add("frontier population", FAIL,
              "no prior session population exists, so the newest cross-section "
              "cannot be shown materially complete", frontier_population)
    else:
        baseline = float(statistics.median(baseline_counts))
        minimum = max(1, math.ceil(baseline * MIN_FRONTIER_POPULATION_RATIO))
        value = {"frontier": frontier_population, "recent_median": baseline,
                 "minimum": minimum, "lookback": len(baseline_counts)}
        if frontier_population < minimum:
            r.add("frontier population", FAIL,
                  f"only {frontier_population:,} securities are present on "
                  f"{frontier}; recent median is {baseline:,.1f} and the "
                  f"material-completeness floor is {minimum:,} "
                  f"({MIN_FRONTIER_POPULATION_RATIO:.0%}). A partial newest "
                  f"page cannot establish a tradeable frontier.", value)
        else:
            r.add("frontier population", PASS,
                  f"{frontier_population:,} securities on {frontier} versus "
                  f"recent median {baseline:,.1f}", value)

    expected_spy = _cal.previous_sessions(frontier, REQUIRED_SPY_SESSIONS)
    from sentinel.feed.store import published_spy_total_return

    spy_rows = [(session, float(close)) for session, close in
                published_spy_total_return(conn, expected_spy[0], frontier)]
    actual_spy = [session for session, close in spy_rows
                  if math.isfinite(close) and close > 0]
    bad_spy = [session for session, close in spy_rows
               if not math.isfinite(close) or close <= 0]
    missing_spy = sorted(set(expected_spy) - set(actual_spy))
    unexpected_spy = sorted(set(actual_spy) - set(expected_spy))
    benchmark_value = {"required": REQUIRED_SPY_SESSIONS,
                       "present": len(actual_spy),
                       "missing": missing_spy,
                       "unexpected": unexpected_spy,
                       "invalid": bad_spy}
    if actual_spy != expected_spy or bad_spy:
        r.add("frontier benchmark", FAIL,
              f"frontier {frontier} requires the exact published "
              f"{REQUIRED_SPY_SESSIONS}-session SPY total-return tail; "
              f"missing={missing_spy}, unexpected={unexpected_spy}, "
              f"invalid={bad_spy}",
              benchmark_value)
    else:
        r.add("frontier benchmark", PASS,
              f"SPY total-return tail is complete through {frontier}",
              benchmark_value)

    # BIL is the controller's defensive execution instrument, not an SEP
    # company. A cash residual is not a substitute for its missing mark: the
    # exact SFP tail must be independently published under the fixed identity.
    from sentinel.feed.store import published_defensive_bars

    defensive_rows = published_defensive_bars(
        conn, expected_spy[0], frontier)
    valid_defensive: list[str] = []
    invalid_defensive: list[str] = []
    for (session, security_id, ticker, open_signal, close_signal,
         close_adjusted, close_unadjusted) in defensive_rows:
        try:
            values_valid = all(
                math.isfinite(float(value)) and float(value) > 0
                for value in (open_signal, close_signal, close_adjusted,
                              close_unadjusted))
        except (TypeError, ValueError, OverflowError):
            values_valid = False
        if (security_id == "SENTINEL:BIL" and ticker == "BIL"
                and values_valid):
            valid_defensive.append(session)
        else:
            invalid_defensive.append(session)
    missing_defensive = sorted(set(expected_spy) - set(valid_defensive))
    unexpected_defensive = sorted(set(valid_defensive) - set(expected_spy))
    defensive_value = {
        "required": REQUIRED_SPY_SESSIONS,
        "present": len(valid_defensive),
        "missing": missing_defensive,
        "unexpected": unexpected_defensive,
        "invalid": invalid_defensive,
        "security_id": "SENTINEL:BIL",
        "ticker": "BIL",
    }
    if (valid_defensive != expected_spy or invalid_defensive):
        r.add(
            "defensive fund marks", FAIL,
            f"frontier {frontier} requires the exact published "
            f"{REQUIRED_SPY_SESSIONS}-session BIL open/close/total-return/raw "
            f"mark tail under "
            f"SENTINEL:BIL; missing={missing_defensive}, "
            f"unexpected={unexpected_defensive}, invalid={invalid_defensive}",
            defensive_value)
    else:
        r.add(
            "defensive fund marks", PASS,
            f"BIL open/close/total-return/raw mark tail is complete through "
            f"{frontier}",
            defensive_value)

    # ── continuity, against an INDEPENDENT calendar ──────────────────────────
    # THE DEFECT THIS REPLACES (measured 2026-08-09): this check used to select
    # the most recent N distinct sessions, count them, and report "N consecutive
    # sessions available". It never established consecutiveness. A 300-session
    # corpus with one session deleted from the middle returned 299 sessions,
    # continuity PASS and ready True.
    #
    # A COUNT CANNOT EXPRESS CONSECUTIVENESS. The corpus cannot be its own
    # witness either: if a session is missing, nothing in the corpus knows it
    # should have been there. So the expectation has to come from outside — the
    # XNYS calendar, the same one the scheduler resolves.
    #
    # The fix is deliberately NOT a larger threshold. Requiring 260 rows instead
    # of 252 changes which holes escape detection and detects none of them.
    #
    # ANCHORED AT THE FRONTIER, not at today: corpus CONSTRUCTION and corpus
    # COMPLETENESS are different questions, and anchoring on today would report
    # every evening between the close and the ingest — and the whole unbuilt
    # history during a seed — as missing.
    # `actual` was loaded once above and is intentionally reused here.
    # A preparation operation therefore has one bounded session-axis scan, not
    # a lifetime count followed by a second continuity scan.
    try:
        window = _cal.previous_sessions(frontier, PREFERRED_SESSIONS)
        # A GAP and a SHORT HISTORY are different faults and must not be
        # conflated. A corpus that begins after the window opens is not missing
        # its early sessions — it has never claimed to hold them, and reporting
        # them as MISSING_SESSIONS would turn "seeded 200 sessions so far" into
        # a red alarm listing 52 dates nobody lost.
        #
        # So gaps are hunted only INSIDE the corpus's own span, and depth is
        # judged separately below by counting what is actually there.
        expected = ([s for s in window if s >= actual[0]] if actual else [])
        missing = _cal.missing_sessions(expected, actual)
        # BOTH sides scoped to the window's span. `actual` reaches further back
        # than the window (the SQL bound is generous on purpose), so comparing
        # it against the window alone reported every older session as one the
        # calendar "does not recognise" — 49 of them on a 300-session corpus.
        # An agreement check that fires on ordinary history is one nobody reads.
        in_window = [s for s in actual if window and s >= window[0]]
        unexpected = _cal.unexpected_sessions(window, in_window)
        cal_name = _cal.calendar_version()
    except _cal.CalendarUnavailable as exc:
        # FAIL, never PASS. A continuity check with no calendar cannot detect a
        # gap, and answering a question it can no longer ask is the defect this
        # rewrite exists to remove.
        r.add("continuity", FAIL,
              f"session calendar unavailable, so continuity cannot be "
              f"verified: {exc}", None)
        expected, missing, unexpected, cal_name = [], [], [], "unavailable"

    if cal_name != "unavailable":
        # DEPTH is what the corpus actually holds inside the window — counted,
        # not inferred from the expectation, so a gap cannot flatter it.
        present = len([s for s in actual if s in set(window)])
        if missing:
            shown = ", ".join(missing[:8]) + (
                f" (+{len(missing) - 8} more)" if len(missing) > 8 else "")
            r.add("continuity", FAIL,
                  f"MISSING_SESSIONS ({len(missing)} of {len(expected)} "
                  f"expected by {cal_name}): {shown}", missing)
        elif present < REQUIRED_SESSIONS:
            r.add("continuity", FAIL,
                  f"only {present} sessions available; the engine needs "
                  f"{REQUIRED_SESSIONS} closes before any security can be "
                  f"scored (momentum reads "
                  f"closes[-{LONG_LOOKBACK_SESSIONS + 1}])", present)
        elif present < PREFERRED_SESSIONS:
            r.add("continuity", WARN,
                  f"{present} sessions, no gaps — above the required "
                  f"{REQUIRED_SESSIONS} but below the preferred "
                  f"{PREFERRED_SESSIONS}. The engine will run with no margin "
                  f"for a vendor gap.", present)
        else:
            r.add("continuity", PASS,
                  f"{present} sessions to {frontier}, no gaps against "
                  f"{cal_name}", present)

        # A SEPARATE fault with a different cause — a vendor emitting a weekend
        # row, or a calendar/vendor disagreement about a half-day. Not a hole in
        # the history, so not folded into the gap verdict where one could mask
        # the other.
        if unexpected:
            shown = ", ".join(unexpected[:5]) + (
                f" (+{len(unexpected) - 5} more)" if len(unexpected) > 5 else "")
            r.add("calendar_agreement", WARN,
                  f"{len(unexpected)} session(s) in the corpus that "
                  f"{cal_name} does not recognise: {shown}", unexpected)
        else:
            r.add("calendar_agreement", PASS,
                  f"every corpus session is a {cal_name} session", 0)

    # ── freshness, in SESSIONS ───────────────────────────────────────────────
    # Against the EXCHANGE, not a day count. `today` is honoured as the moment
    # to judge from — callers pass a date, which `_now_et` reads as exchange-
    # local midnight, so a date-only caller is asking "as of the start of that
    # day" and the latest closed session is the previous one. That is the
    # conservative reading: it never claims a session is owed before its close.
    fresh = _cal.freshness(frontier, now_et=today)
    if not fresh.evaluable:
        # FAIL, never PASS. Same rule as continuity: a check that could not ask
        # its question has not answered it.
        r.add("freshness", FAIL, fresh.reason, fresh.to_dict())
    elif fresh.ahead:
        r.add("freshness", FAIL, fresh.reason, fresh.to_dict())
    elif fresh.fresh:
        r.add("freshness", PASS, fresh.reason, fresh.to_dict())
    else:
        r.add("freshness", FAIL,
              f"{fresh.reason}. A daily fetch has been failing: planning on "
              f"this corpus produces an older session's book with today's "
              f"confidence.", fresh.to_dict())

    # ── the four price domains, over the WINDOW THAT WILL BE READ ────────────
    # Measured on the recent window rather than the whole corpus: a decade of
    # sparse early history would drown a hole in the sessions the engine is about
    # to use, which is the only stretch that can break today's plan.
    # Clamped: a corpus SHORTER than the required window has already failed
    # continuity, and the remaining checks should still report against whatever
    # it does hold rather than crash. A readiness report that raises tells the
    # operator less than the one failing check it was about to print.
    # From what the corpus ACTUALLY holds, not from the calendar's expectation:
    # these checks measure the density of columns in real rows, and anchoring
    # them on a session the corpus is missing would start the window at a date
    # with nothing in it.
    window_start = (actual[-min(REQUIRED_SESSIONS, len(actual))] if actual
                    else frontier)
    for column, label, protects in (
        ("close_signal", "signal domain", "momentum and the trailing-stop peak"),
        ("close_unadjusted", "raw close", "marking and the 4% admission size"),
        ("open_unadjusted", "raw open", "every fill"),
        ("volume", "volume", "ADV20 and signal dollar volume"),
    ):
        n, present = _domain_coverage(conn, column, window_start, frontier)
        share = 0.0 if not n else present / n
        if share < 0.90:
            r.add(label, FAIL,
                  f"{label} present on {share:.1%} of bars since {window_start}. "
                  f"It backs {protects}; below this the plan is not wrong in a "
                  f"way anything downstream reports.", round(share, 4))
        else:
            r.add(label, PASS, f"{share:.1%} coverage since {window_start}",
                  round(share, 4))

    # ── identity ─────────────────────────────────────────────────────────────
    securities = _q1(conn, "SELECT COUNT(DISTINCT security_id)"
                           " FROM sentinel_bars b WHERE session >= %s"
                           f"   AND {_VISIBLE_BARS}", (window_start,))
    # CURRENT identity cardinality comes from the publication-maintained read
    # model.  Counting raw dated snapshots here made this check grow with corpus
    # age and made historical copies look like additional live securities.
    listed = _q1(conn, "SELECT COUNT(DISTINCT permaticker)"
                       " FROM feed_universe_current")
    if not listed:
        r.add("identity", FAIL,
              "the current universe projection is EMPTY, so every bar was keyed "
              "on its ticker or dropped. Ticker reuse splices two unrelated "
              "companies into one security and computes momentum across the seam.",
              0)
    else:
        r.add("identity", PASS,
              f"{securities:,} securities priced, {listed:,} current identities",
              securities)

    # ── issuer keys ──────────────────────────────────────────────────────────
    # Without these the GOOG/GOOGL class of defect is not merely present, it is
    # UNDETECTABLE: the duplicate-issuer invariant has nothing to compare.
    # Distinct PERMATICKER is the semantic security count. A security may retain
    # multiple historical ticker pairings in the compact projection, and neither
    # those pairings nor dated snapshots are extra live securities.
    with_related = _q1(
        conn, "SELECT COUNT(DISTINCT permaticker) FROM feed_universe_current"
              " WHERE related_tickers IS NOT NULL") or 0
    if listed and with_related == 0:
        r.add("issuer keys", FAIL,
              "no security carries related_tickers, so every issuer key falls "
              "back to the permaticker and two share classes of one company "
              "cannot be detected as the same issuer.", 0)
    elif listed:
        r.add("issuer keys", PASS,
              f"{with_related:,} current securities carry related tickers",
              with_related)

    # ── corporate actions ────────────────────────────────────────────────────
    recent_actions = _q1(conn, "SELECT COUNT(*) FROM sentinel_active_actions"
                               " WHERE session >= %s",
                         (window_start,)) or 0
    if recent_actions == 0:
        r.add("actions", FAIL,
              f"no corporate actions since {window_start}. Over a window this "
              f"long that is a missing ingest, not a quiet market — splits and "
              f"terminal events would both go unseen.", 0)
    else:
        r.add("actions", PASS, f"{recent_actions:,} actions since {window_start}",
              recent_actions)

    # ── ingest refusals, made LOUD ───────────────────────────────────────────
    # A SEP row the vendor priced and the ingest could not name is dropped
    # before `sentinel_bars`. That is the correct handling — keying it on the
    # ticker would re-introduce the reuse splice — but it is also a hole in the
    # corpus that nothing downstream can see, so it is surfaced here in its own
    # right rather than only as an input to the terminal accounting.
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*), COUNT(DISTINCT ticker)"
                        " FROM sentinel_ingest_rejections"
                        " WHERE session BETWEEN %s AND %s AND reason = %s",
                        (window_start, frontier, "NO_IDENTITY"))
            n_rows, n_tick = cur.fetchone()
        # The OTHER drop, counted in its own right. A row the vendor supplied
        # with no as-traded close is refused for a different and equally
        # correct reason, and reporting only the identity failures under a
        # check named "ingest refusals" would let a corpus missing thousands of
        # priced rows read as "every priced row resolved".
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*), COUNT(DISTINCT ticker)"
                        " FROM sentinel_ingest_rejections"
                        " WHERE session BETWEEN %s AND %s AND reason = %s",
                        (window_start, frontier, "NO_RAW_CLOSE"))
            n_noclose, n_noclose_tick = cur.fetchone()

        if n_rows or n_noclose:
            parts = []
            if n_rows:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT DISTINCT ticker FROM sentinel_ingest_rejections"
                        " WHERE session BETWEEN %s AND %s AND reason = %s"
                        " ORDER BY ticker LIMIT 10",
                        (window_start, frontier, "NO_IDENTITY"))
                    names = ", ".join(str(t[0]) for t in cur.fetchall())
                parts.append(
                    f"PRICE_ROW_DROPPED_NO_IDENTITY: {n_rows:,} row(s) across "
                    f"{n_tick} ticker(s) the vendor priced and the ingest could "
                    f"not name: {names}")
            if n_noclose:
                parts.append(
                    f"PRICE_ROW_DROPPED_NO_RAW_CLOSE: {n_noclose:,} row(s) "
                    f"across {n_noclose_tick} ticker(s) with no as-traded price")
            # WARN, not FAIL, and deliberately so: a few unnameable instruments
            # are ordinary operationally. Whether they mattered to a SPECIFIC
            # replay is a different question with a fail-closed answer —
            # `sentinel rejection-audit`, which readiness must not pre-empt.
            r.add("ingest refusals", WARN,
                  " | ".join(parts) + " — run `rejection-audit` before "
                  "treating an interval as certified", (n_rows or 0) + (n_noclose or 0))
        else:
            r.add("ingest refusals", PASS,
                  "every priced row resolved to a permanent security", 0)
    except Exception as exc:                          # noqa: BLE001
        r.add("ingest refusals", WARN,
              f"ingest refusals could not be read: {exc!r}", None)

    # ── terminal identity, with CONSERVATION ─────────────────────────────────
    # `actions` above counts ROWS. It is satisfied by a table full of splits
    # while every termination in the window failed identity resolution and
    # silently never became a TerminalTerms — the book would then hold a
    # security that had been acquired, and nothing here would say so.
    #
    # THE INVARIANT: any economically relevant terminal action inside the
    # window that cannot be mapped unambiguously to a permanent security makes
    # Sentinel NOT READY. Not a warning — a target planned on it may hold
    # something that no longer exists.
    try:
        from sentinel.core.terminal import load_terminal_events
        from sentinel.feed.universe import load_resolver

        # THE OPERATIONAL WINDOW, not the 127-session domain window. `bootstrap`
        # loads terminal events over the whole 252-session warm-up — an
        # acquisition early in the warm-up still ends that security — so a gate
        # scoped to the shorter window would pass a corpus whose terminations
        # the book is about to read and cannot attribute.
        terminal_start = (actual[-min(PREFERRED_SESSIONS, len(actual))]
                          if actual else window_start)
        acc = load_terminal_events(
            conn, start=terminal_start, end=frontier,
            resolve_with_reason=load_resolver(conn).resolve_with_reason)
        counts = (f"discovered {acc.discovered} · relevant {acc.relevant} · "
                  f"resolved {len(acc.resolved)} · collapsed {len(acc.collapsed)} "
                  f"· excluded {len(acc.excluded)} · unresolved "
                  f"{len(acc.unresolved)}")

        if not acc.conservation_holds():
            # Cannot happen by construction, which is exactly why it is checked:
            # the accounting's whole value is that it adds up, and an assertion
            # nobody makes is a property nobody has.
            r.add("terminal identity", FAIL,
                  f"CONSERVATION VIOLATED — {counts}. A row was neither used "
                  f"nor accounted for.", acc.to_dict())
        elif not acc.normalized_stream_holds():
            # This is the exact event list bootstrap hands to run_sessions.
            # Readiness must not say READY for a stream whose duplicate guard
            # will reject it before producing a book.
            duplicates: dict[tuple[str, str], int] = {}
            for event in acc.events:
                key = (event.session, event.security_id)
                duplicates[key] = duplicates.get(key, 0) + 1
            bad = "; ".join(
                f"{session} security_id={security_id} count={count}"
                for (session, security_id), count in sorted(duplicates.items())
                if count > 1)
            r.add("terminal identity", FAIL,
                  f"NORMALIZED TERMINAL STREAM REJECTED — {counts}. "
                  f"Duplicate economic keys: {bad}", acc.to_dict())
        elif acc.unresolved:
            # The offending ROWS, not the count. "unresolved: 1" is a number an
            # operator cannot act on; a date, a ticker and a reason is a fetch
            # they can re-run or a mapping they can correct.
            listed = "; ".join(x.describe() for x in acc.unresolved[:10])
            more = (f" (+{len(acc.unresolved) - 10} more)"
                    if len(acc.unresolved) > 10 else "")
            r.add("terminal identity", FAIL,
                  f"{counts}\n      UNRESOLVED: {listed}{more}", acc.to_dict())
        else:
            excl = acc.exclusion_counts()
            detail = counts + (f" · exclusions {excl}" if excl else "")
            r.add("terminal identity", PASS, detail, acc.to_dict())
    except Exception as exc:                          # noqa: BLE001
        # FAIL, never skip. An accounting that cannot run has not proved
        # anything, and passing on that basis is the silence this check exists
        # to end.
        r.add("terminal identity", FAIL,
              f"terminal identity accounting could not run: {exc!r}", None)

    return r


def _domain_coverage(conn, column: str, start: str, end: str) -> tuple[int, int]:
    # `column` is from a fixed literal tuple above, never caller input — the only
    # reason interpolating it here is not an injection.
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT COUNT(*), COUNT({column}) FROM sentinel_bars b"
            f" WHERE session BETWEEN %s AND %s AND {_VISIBLE_BARS}",
            (start, end))
        n, present = cur.fetchone()
    return int(n or 0), int(present or 0)
