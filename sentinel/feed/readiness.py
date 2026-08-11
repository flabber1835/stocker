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
corpus coherence    no committed rows belong to an ingest nothing published —
                    those are invisible to every reader, and a corpus quietly
                    frozen at last Tuesday looks identical to a healthy one
```

`WARN` exists for the one case that is genuinely a judgement call — coverage
below the preferred 252-session window but above the required 126. Everything
else is PASS or FAIL, because a data contract that can be partially satisfied is
one nobody enforces.
"""
from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field
from typing import Optional

from sentinel.feed import calendar as _cal
from sentinel.feed import publication as _publication
from stock_strategy_shared.wealth_core.eligibility import EligibilityConfig
from stock_strategy_shared.wealth_core.signals import (
    LONG_LOOKBACK_SESSIONS,
    REQUIRED_CLOSES,
)

#: The engine's own requirement, not a number chosen here: `momentum` reads
#: closes[-(LONG_LOOKBACK_SESSIONS + 1)], so 127 closes are needed before a
#: security can be scored at all.
REQUIRED_SESSIONS = REQUIRED_CLOSES

#: §8's preferred startup window. Above REQUIRED and below this is a WARN: the
#: engine will run, with no margin for a vendor gap.
PREFERRED_SESSIONS = 252

#: Calendar days the frontier may lag before the corpus is stale. Four days
#: covers a normal weekend plus a holiday; beyond that, a daily fetch has been
#: failing and nobody noticed.
MAX_FRONTIER_AGE_DAYS = 4

PASS, WARN, FAIL = "PASS", "WARN", "FAIL"

#: PUBLISHED IS WHAT READABLE MEANS, and readiness must measure what a reader
#: sees. Bound once, from the single definition in `publication`, and
#: interpolated into every query below: two hand-written copies of a visibility
#: rule is how a report starts describing a corpus the engine cannot load.
_VISIBLE_BARS = _publication.visible_predicate("b")
_VISIBLE_ACTIONS = _publication.visible_predicate("a")


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
        report = publication.coherence(conn)
    except Exception as exc:                              # noqa: BLE001
        # FAIL, never skip. A visibility rule that cannot be evaluated has not
        # been satisfied, and every count in this report is scoped by it.
        r.add("corpus coherence", FAIL,
              f"corpus coherence could not be evaluated: {exc!r}. Every other "
              f"check here measures the PUBLISHED corpus, so none of them can "
              f"be trusted until this one answers.", None)
        return

    if report.coherent:
        r.add("corpus coherence", PASS,
              "every committed row belongs to a published ingest", 0)
    else:
        r.add("corpus coherence", FAIL,
              f"{report.unpublished_rows:,} committed row(s) belong to "
              f"{len(report.unpublished_runs)} ingest run(s) that never "
              f"published: {list(report.unpublished_runs)}. Those rows are "
              f"INVISIBLE to every reader, so the corpus is frozen at the last "
              f"published version while the fetch appears to be working. "
              f"Publish them — the rows are committed and the upserts are "
              f"idempotent, so no re-ingest is needed.",
              report.to_dict())

    published = publication.current(conn)
    if published is not None:
        r.add("corpus version", PASS,
              f"v{published.version} (previous "
              f"{published.previous_version})", published.version)
        return

    stamped = _q1(conn, "SELECT COUNT(*) FROM sentinel_bars"
                        " WHERE last_written_run_id IS NOT NULL") or 0
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
    today = today or _dt.date.today().isoformat()

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

    total = _q1(conn, "SELECT COUNT(DISTINCT session) FROM sentinel_bars b"
                      f" WHERE {_VISIBLE_BARS}")
    r.add("sessions", PASS, f"{total:,} distinct sessions to {frontier}", total)

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
    with conn.cursor() as cur:
        cur.execute("SELECT DISTINCT session FROM sentinel_bars b"
                    " WHERE session >= %s"
                    f"   AND {_VISIBLE_BARS} ORDER BY session",
                    (_window_start(frontier),))
        actual = [str(x[0]) for x in cur.fetchall()]

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

    # ── freshness ────────────────────────────────────────────────────────────
    age = (_dt.date.fromisoformat(today) - _dt.date.fromisoformat(frontier)).days
    if age > MAX_FRONTIER_AGE_DAYS:
        r.add("freshness", FAIL,
              f"the newest session is {frontier}, {age} days old. A daily fetch "
              f"has been failing: planning on this corpus produces yesterday's "
              f"book with today's confidence.", age)
    else:
        r.add("freshness", PASS, f"frontier {frontier} ({age}d old)", age)

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
    listed = _q1(conn, "SELECT COUNT(DISTINCT permaticker) FROM sentinel_universe")
    if not listed:
        r.add("identity", FAIL,
              "sentinel_universe is EMPTY, so every bar was keyed on its ticker "
              "or dropped. Ticker reuse splices two unrelated companies into one "
              "security and computes momentum across the seam.", 0)
    else:
        r.add("identity", PASS,
              f"{securities:,} securities priced, {listed:,} identities stored",
              securities)

    # ── issuer keys ──────────────────────────────────────────────────────────
    # Without these the GOOG/GOOGL class of defect is not merely present, it is
    # UNDETECTABLE: the duplicate-issuer invariant has nothing to compare.
    with_related = _q1(conn, "SELECT COUNT(*) FROM sentinel_universe"
                             " WHERE related_tickers IS NOT NULL") or 0
    if listed and with_related == 0:
        r.add("issuer keys", FAIL,
              "no security carries related_tickers, so every issuer key falls "
              "back to the permaticker and two share classes of one company "
              "cannot be detected as the same issuer.", 0)
    elif listed:
        r.add("issuer keys", PASS,
              f"{with_related:,} securities carry related tickers", with_related)

    # ── corporate actions ────────────────────────────────────────────────────
    recent_actions = _q1(conn, "SELECT COUNT(*) FROM sentinel_actions a"
                               " WHERE session >= %s"
                               f"   AND {_VISIBLE_ACTIONS}",
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
                  f"resolved {len(acc.resolved)} · excluded {len(acc.excluded)} "
                  f"· unresolved {len(acc.unresolved)}")

        if not acc.conservation_holds():
            # Cannot happen by construction, which is exactly why it is checked:
            # the accounting's whole value is that it adds up, and an assertion
            # nobody makes is a property nobody has.
            r.add("terminal identity", FAIL,
                  f"CONSERVATION VIOLATED — {counts}. A row was neither used "
                  f"nor accounted for.", acc.to_dict())
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
