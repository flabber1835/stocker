"""The read-only panel's DATA MODEL. PURE: no DB, no network, no clock reads.

WHY A PURE MODEL BEHIND A ONE-PAGE UI. The panel's whole job is to answer "is
anything silently wrong?", and a renderer that reaches into a database while it
draws cannot be tested against the states worth drawing — a stalled seed, a lost
ownership log, a book that blocked rather than settled. Those are exactly the
states nobody can reproduce on demand. So IO happens in `sources.py`, the shapes
below are built from plain values, and `render.py` only formats them.

THE DESIGN RULE, and it comes from this system's actual failures rather than
from taste:

    THIS SYSTEM'S CHARACTERISTIC FAILURE IS NOT A CRASH. IT IS SOMETHING THAT
    LOOKS HEALTHY.

In one evening: a detached seed that died on a missing dependency read exactly
like a running seed; a stale image emitted a valid-looking hash; a book that
BLOCKS its terminations still completes and still reports a plausible CAGR. A
dashboard that shows the happy numbers larger and the caveats smaller makes
every one of those worse.

So:

    every value carries the time it was last TRUE, not the time it was fetched
    anything past its freshness budget renders STALE rather than plain
    a value that cannot be computed renders UNKNOWN, never 0 and never blank
    performance appears only beside an explicit trial-verification verdict
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional

#: Performance is permitted only inside the versioned trial-verification
#: projection.  Kept as a compatibility name so old callers fail visibly if
#: they still expect the former condition-only contract.
NO_PERFORMANCE_HERE = False

MAXIMUM_FUTURE_SKEW = timedelta(seconds=5)

OK = "ok"
"""Measured, fresh, and within contract."""

WARN = "warn"
"""True but wants attention — stale inside tolerance, or a degraded reading."""

FAIL = "fail"
"""Measured and wrong. Something needs a human."""

PENDING = "pending"
"""Not built or not yet reached. Distinct from FAIL because "no execution path
exists yet" is a project state, not an outage — conflating them trains an
operator to ignore red."""

UNKNOWN = "unknown"
"""Could not be read. NEVER rendered as zero: the difference between "no
unresolved terminals" and "nobody could count them" is the entire point."""

_STATUS_RANK = {OK: 0, PENDING: 1, WARN: 2, FAIL: 3, UNKNOWN: 3}

TRIAL_ROW_KEYS = frozenset({
    "trial_verification", "actual_account", "trial_return",
    "trial_drawdown", "trial_annualized", "trial_intent",
})

SHADOW_ROW_KEYS = frozenset({
    "shadow_verification", "shadow_nav", "shadow_return",
})

FINANCIAL_AUTHORITY_ROW_KEYS = TRIAL_ROW_KEYS | SHADOW_ROW_KEYS


@dataclass(frozen=True)
class Row:
    """One line of the panel.

    `as_of` is when the underlying fact was last TRUE — not when this object was
    built. A row assembled at 22:47 from a feed whose clock froze at 22:08 is a
    22:08 row, and rendering it with the build time would turn a stall into a
    reassurance. That mistake is precisely what `feed-status` prints a warning
    about, and a UI has more room to make it.
    """
    key: str
    label: str
    value: str
    status: str = OK
    detail: str = ""
    as_of: Optional[datetime] = None
    #: How old this row's fact may be before it reads STALE. None = timeless
    #: (an ownership event is true until superseded; a feed frontier is not).
    freshness: Optional[timedelta] = None

    def staleness(self, now: datetime) -> Optional[timedelta]:
        return None if self.as_of is None else now - self.as_of

    def is_stale(self, now: datetime) -> bool:
        if self.as_of is None or self.freshness is None:
            return False
        return (now - self.as_of) > self.freshness

    def is_future(self, now: datetime) -> bool:
        return (self.as_of is not None
                and self.as_of - now > MAXIMUM_FUTURE_SKEW)

    def effective_status(self, now: datetime) -> str:
        """A stale OK is a WARN. Staleness cannot IMPROVE a status — a row that
        is already failing does not become merely stale."""
        if self.is_future(now):
            return FAIL
        if self.is_stale(now) and _STATUS_RANK[self.status] < _STATUS_RANK[WARN]:
            return WARN
        return self.status


@dataclass(frozen=True)
class Panel:
    rows: list[Row] = field(default_factory=list)
    now: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    #: Set when a SOURCE failed rather than a check — the panel could not read
    #: the world. Rendered at the top, because every row below it is suspect.
    source_errors: list[str] = field(default_factory=list)
    #: Already-earned durable financial evidence for read-only detail sections.
    trial_details: dict = field(default_factory=dict)
    trial_history: list[dict] = field(default_factory=list)

    @property
    def overall(self) -> str:
        """The worst row wins, and PENDING never counts.

        A half-built system is full of pending rows; letting them drive the
        headline would leave it permanently amber and teach the reader that the
        colour means nothing.
        """
        live = [r.effective_status(self.now) for r in self.rows
                if r.status is not PENDING]
        if self.source_errors:
            live.append(FAIL)
        return max(live, key=lambda s: _STATUS_RANK[s]) if live else PENDING

    @property
    def operational(self) -> str:
        """Current non-trial authority required before verified styling.

        Historical financial evidence remains immutable, but it may not turn a
        screen green while a current required source is stale, unreadable, or
        failing.  PENDING retains its existing meaning: a deliberately absent
        non-runtime capability is not an outage.
        """
        live = [r.effective_status(self.now) for r in self.rows
                if (r.key not in FINANCIAL_AUTHORITY_ROW_KEYS
                    and r.status is not PENDING)]
        if self.source_errors:
            live.append(FAIL)
        return max(live, key=lambda s: _STATUS_RANK[s]) if live else OK

    def row(self, key: str) -> Optional[Row]:
        return next((r for r in self.rows if r.key == key), None)


# ── the rows ─────────────────────────────────────────────────────────────────

def trial_verification_row(*, verdict: Optional[str], session: Optional[str],
                           reason_codes=(), verified_at: Optional[datetime] = None,
                           error: Optional[str] = None) -> Row:
    if error:
        return Row("trial_verification", "Trial verification",
                   "TRIAL NOT VERIFIED — EVIDENCE UNREADABLE", UNKNOWN,
                   error, verified_at)
    if verdict != "VERIFIED" or not session:
        reason = str(next(iter(reason_codes), "NO SESSION CERTIFICATE"))
        return Row("trial_verification", "Trial verification",
                   f"TRIAL NOT VERIFIED — {reason.replace('_', ' ')}", FAIL,
                   "performance is informational until every financial clause "
                   "earns one immutable session certificate", verified_at)
    return Row("trial_verification", "Trial verification",
               f"TRIAL VERIFIED THROUGH {session}", OK,
               "actual broker economics, publication, strategy state, cycle, "
               "book, reconstructed close cash and independent close NAV are "
               "bound by one durable record",
               verified_at)


def trial_metric_row(key: str, label: str, value: Optional[str], *,
                     verified: bool, detail: str,
                     as_of: Optional[datetime]) -> Row:
    if value is None:
        return Row(key, label, "UNAVAILABLE", UNKNOWN, detail, as_of)
    return Row(key, label, value, OK if verified else WARN,
               detail if verified else f"UNVERIFIED · {detail}", as_of)


def shadow_verification_row(
        *, verdict: Optional[str], verification: Optional[str],
        session: Optional[str], sessions_lag: Optional[int] = None,
        error: Optional[str] = None, unreadable: bool = False) -> Row:
    """The broker-free performance authority used by reviewed dual mode."""
    if unreadable:
        return Row(
            "shadow_verification", "Certified shadow strategy",
            "SHADOW NOT VERIFIED — EVIDENCE UNREADABLE", UNKNOWN,
            error or "the certified shadow ledger could not be read")
    if error:
        return Row(
            "shadow_verification", "Certified shadow strategy",
            "SHADOW NOT VERIFIED — VERIFICATION WITHDRAWN", FAIL, error)
    lag = int(sessions_lag or 0)
    if (verdict != "SHADOW_GO" or verification != "VERIFIED"
            or not session or lag != 0):
        reason = (f"{lag} SESSION(S) BEHIND" if lag else
                  "NO CURRENT VERIFIED SESSION")
        return Row(
            "shadow_verification", "Certified shadow strategy",
            f"SHADOW NOT VERIFIED — {reason}", FAIL,
            "strategy performance is authoritative only while the complete "
            "broker-free lineage and current Sharadar corpus revalidate")
    return Row(
        "shadow_verification", "Certified shadow strategy",
        f"SHADOW VERIFIED THROUGH {session}", OK,
        "sole strategy-performance authority · canonical Wealth Core plus "
        "accepted Sharadar inputs · independent of Alpaca PAPER accounting")


def shadow_metric_row(
        key: str, label: str, value: Optional[str], *, verified: bool,
        detail: str) -> Row:
    if value is None:
        return Row(key, label, "UNAVAILABLE", UNKNOWN, detail)
    return Row(
        key, label, value, OK if verified else WARN,
        detail if verified else f"NOT CURRENT · {detail}")


def paper_reconciliation_row(
        *, state: str, cycle_state: Optional[str] = None,
        detail: str = "", error: Optional[str] = None) -> Row:
    """Operational PAPER transport; never a performance authority."""
    if error:
        return Row(
            "paper_reconciliation", "Alpaca PAPER mirror",
            "PAPER NOT VERIFIED · STATUS UNREADABLE", UNKNOWN, error)
    normalized = str(state or "").upper()
    cycle = str(cycle_state or "").upper()
    suffix = f" · cycle {cycle}" if cycle else ""
    if normalized == "MISMATCH":
        return Row(
            "paper_reconciliation", "Alpaca PAPER mirror",
            "PAPER NOT VERIFIED · MISMATCH · BLOCKED", FAIL,
            (detail or "a durable PAPER discrepancy blocks future mutations")
            + suffix)
    if normalized == "CLEAN":
        return Row(
            "paper_reconciliation", "Alpaca PAPER mirror",
            "PAPER NOT VERIFIED · MIRROR CLEAN", OK,
            (detail or "orders and positions match the informational plan")
            + suffix)
    if normalized == "NOT_STARTED":
        return Row(
            "paper_reconciliation", "Alpaca PAPER mirror",
            "PAPER NOT VERIFIED · NOT STARTED", WARN,
            (detail or "no informational PAPER plan has been transported")
            + suffix)
    return Row(
        "paper_reconciliation", "Alpaca PAPER mirror",
        "PAPER NOT VERIFIED · PENDING", WARN,
        (detail or "ordinary order/fill or post-close unit evidence is pending")
        + suffix)

def ownership_row(*, state: Optional[str], at: Optional[datetime],
                  error: Optional[str] = None) -> Row:
    """The single most safety-critical fact Sentinel owns.

    The canonical PostgreSQL binding is the only ownership authority. Losing a
    retired JSONL audit file cannot re-arm migration, and ordinary startup has
    no liquidation path. It must still be impossible to look at this panel and
    not know which side of the explicit handover boundary the database records,
    so ownership is row one and is never abbreviated.

    Timeless by design (`freshness=None`): an established handover does not go
    stale. It is true until something supersedes it.  That is an ownership
    fact, not a current-position fact: the account may hold a Sentinel book
    after the historically flat handover.
    """
    if error:
        return Row("ownership", "Ownership", "UNREADABLE", UNKNOWN,
                   f"the canonical binding could not be read — {error}", at)

    # The panel source consumes OwnershipView.state.value directly. These are
    # the canonical database-backed ownership facts; never reinterpret them as
    # stages of the retired handover state machine.
    if state == "OWNED":
        return Row(
            "ownership", "Ownership", "SENTINEL OWNED", OK,
            "canonical PostgreSQL account binding establishes Sentinel "
            "ownership; see Broker for current positions", at)
    if state == "NOT_OWNED":
        return Row(
            "ownership", "Ownership", "NOT ESTABLISHED", WARN,
            "canonical PostgreSQL account binding is absent — Sentinel must "
            "not treat the account as owned", at)
    if state in (None, "UNKNOWN"):
        return Row(
            "ownership", "Ownership", "UNKNOWN", UNKNOWN,
            "canonical ownership state is unknown; no ownership authority is "
            "inferred from audit files", at)

    # Legacy vocabulary is retained only for old direct model callers. The
    # production panel source above never emits these strings; PostgreSQL's
    # OwnershipView enum is authoritative.
    if state in ("SENTINEL_OWNERSHIP_ESTABLISHED",
                 "WEALTH_CORE_BOOTSTRAP_ALLOWED"):
        return Row("ownership", "Ownership", "SENTINEL OWNED", OK,
                   "historical flat handover recorded; see Broker for current "
                   "positions", at)
    # UNINITIALIZED is the state of a store that has never been written, which
    # is where every deployment starts. It is NOT "in progress" — nothing has
    # begun — and saying so would misreport the most important row on the page
    # in the most common condition it will ever be read in.
    if state in (None, "UNKNOWN", "UNINITIALIZED"):
        return Row("ownership", "Ownership", "NOT ESTABLISHED", WARN,
                   "legacy book not yet retired — Wealth Core must not bootstrap",
                   at)
    # Everything between UNINITIALIZED and ESTABLISHED is a real handover that
    # stopped part-way, and that IS worth calling out: a liquidation that
    # submitted and never confirmed flat leaves an account nobody owns cleanly.
    return Row("ownership", "Ownership", state.replace("_", " "), WARN,
               "handover incomplete — it stopped part-way", at)


def exposure_row(*, exposure: Optional[float],
                 controller_active: Optional[bool], adopted: bool = True,
                 session: Optional[str] = None,
                 as_of: Optional[datetime] = None,
                 error: Optional[str] = None) -> Row:
    """`1.00 PINNED` and `1.00 computed` are different facts and the panel must
    never let them look alike.

    Until items F-H land, the actuator is pinned and nothing varies exposure —
    §6 of the deployment doc stages it that way on purpose. When the controller
    is switched on, this row is where an operator learns that the number is now
    a DECISION. Spelling out PINNED means the change is visible rather than
    inferred from a value that did not move.
    """
    if error or exposure is None or controller_active is None:
        return Row("exposure", "Exposure", "UNKNOWN", UNKNOWN,
                   error or "no durable controller/plan exposure", as_of)
    where = f" · decision {session}" if session else ""
    if controller_active and adopted:
        return Row("exposure", "Exposure", f"{exposure:.2f}", OK,
                   f"durable current controller plan{where}", as_of,
                   freshness=timedelta(days=4))
    if controller_active:
        return Row("exposure", "Exposure", f"{exposure:.2f} NOT ADOPTED", WARN,
                   f"canonical controller decision has no current plan{where}",
                   as_of, freshness=timedelta(days=4))
    status = PENDING if adopted else WARN
    detail = ("durable current rollout pins exposure at 1.00"
              if adopted else "pinned rollout has no current plan")
    return Row("exposure", "Exposure", f"{exposure:.2f} PINNED", status,
               detail + where, as_of,
               freshness=(timedelta(days=4) if as_of else None))


#: A verdict older than this describes a corpus that has since been through a
#: daily ingest. Shown, never hidden — but labelled, because a stale PASS
#: presented as current is the one way an old verdict does harm.
VERDICT_STALE_AFTER = timedelta(hours=26)


def feed_row(*, frontier: Optional[str], sessions_behind: Optional[int],
             ready: Optional[bool], checks_passed: int, checks_total: int,
             as_of: Optional[datetime], error: Optional[str] = None,
             ingest_running: bool = False,
             checked_at: Optional[datetime] = None) -> Row:
    """The data contract, not a row count.

    §8 is explicit that "126 rows" is not the test, so this reports the contract
    VERDICT and how far behind the frontier is. A feed that is complete but four
    sessions stale supports no decision, and a row count would call it healthy.
    """
    if error:
        # A frontier that will not answer WHILE A SEED IS WRITING THAT TABLE is
        # a feed mid-ingest, not an unreadable one. Calling it UNREADABLE was
        # technically true and operationally wrong: the corpus is being built,
        # which the row below already says, and an alarm here would fire for
        # hours every time a seed runs. The ingest row is authoritative during
        # an ingest; this row defers to it.
        if ingest_running:
            return Row("feed", "Feed", "BUILDING", PENDING,
                       f"frontier not readable during an ingest — {error}",
                       as_of)
        return Row("feed", "Feed", "UNREADABLE", UNKNOWN,
                   f"could not read the feed — {error}", as_of)
    if frontier is None:
        return Row("feed", "Feed", "EMPTY", WARN,
                   "no sessions ingested yet — run feed-seed", as_of)
    behind = ("" if sessions_behind is None
              else f" · {sessions_behind} session{'s' if sessions_behind != 1 else ''} behind")
    # THREE states, not two. `ready is None` means the contract check did not
    # COMPLETE — it is the expensive read and it times out against a corpus
    # being bulk-loaded. Reporting that as "contract NOT READY" would raise a
    # red alarm every time someone opened the panel during a seed, which is
    # both wrong and the fastest way to teach an operator to ignore the colour.
    # Same rule as the crash brake's `evaluable`: one flag must not answer both
    # "the evidence says no" and "there is no evidence".
    if ready is None:
        return Row("feed", "Feed", f"{frontier}{behind}", WARN,
                   "contract NOT CHECKED — no verdict has ever been stored. "
                   "Run `check-data`; this is 'we have not asked', not 'the "
                   "corpus failed'.", as_of, freshness=timedelta(days=4))
    verdict = ("contract READY" if ready else "contract NOT READY")

    # WHEN IT WAS MEASURED, always, and an explicit warning once it is old.
    # The page no longer computes the contract — it reads the last stored
    # verdict — so the age is the only thing separating a current answer from
    # one that predates a re-ingest. Undated, a day-old PASS reads as now.
    age = ""
    stale = False
    if checked_at is not None:
        delta = datetime.now(timezone.utc) - checked_at
        stale = delta > VERDICT_STALE_AFTER
        hours = delta.total_seconds() / 3600
        age = (f" · checked {hours:.0f}h ago" if hours >= 1
               else f" · checked {delta.total_seconds() / 60:.0f}m ago")
        if stale:
            age += " — STALE, re-run check-data"

    status = OK if ready else FAIL
    if ready and stale:
        # Reported, not downgraded to a failure. The verdict was a PASS and
        # saying otherwise would be inventing a result; what is uncertain is
        # whether it still applies.
        status = WARN
    return Row("feed", "Feed", f"{frontier}{behind}", status,
               f"{verdict} {checks_passed}/{checks_total}{age}", as_of,
               freshness=timedelta(days=4))


def ingest_row(*, kind: Optional[str], status: Optional[str],
               chunks_done: int, chunks_total: int, rows_written: int,
               current_chunk: Optional[str], updated_at: Optional[datetime],
               error_message: Optional[str] = None) -> Row:
    """The running (or last) ingest.

    This row exists because of a specific failure: a `feed-seed` launched
    DETACHED died instantly on a missing dependency and was indistinguishable
    from a seed that was running — the recommended way to survive a dropped SSH
    session is also the way to not notice the command failed. A frozen
    `updated_at` is the tell, so the freshness budget here is TIGHT and a stalled
    run goes amber on its own.
    """
    if status is None:
        return Row("ingest", "Ingest", "NONE", PENDING, "no ingest has run", None)
    pct = (100.0 * chunks_done / chunks_total) if chunks_total else 0.0
    where = f" · {current_chunk}" if current_chunk else ""
    detail = f"{rows_written:,} rows{where}"
    if status == "failed":
        return Row("ingest", "Ingest", f"{kind} FAILED", FAIL,
                   error_message or detail, updated_at)
    if status == "running":
        return Row("ingest", "Ingest",
                   f"{kind} {pct:.0f}% · {chunks_done}/{chunks_total}", OK,
                   detail, updated_at, freshness=timedelta(minutes=15))
    return Row("ingest", "Ingest", f"{kind} complete", OK, detail, updated_at)


def book_row(*, available: Optional[bool], slots_used: Optional[int] = None,
             slots_total: Optional[int] = None, nav: Optional[float] = None,
             cash: Optional[float] = None, blocked: Optional[int] = None,
             unresolved_terminals: Optional[int] = None,
             unpriced_securities: Optional[int] = None,
             pending_actions: Optional[int] = None,
             as_of: Optional[datetime] = None,
             error: Optional[str] = None) -> Row:
    """The book, with `blocked` and `unresolved` on the SAME LINE as the NAV.

    Not a layout preference. An unresolved terminal freezes admissions while
    every other number looks fine, and `resolved_equity` goes None while a
    plausible total is still printable. Putting the caveats beside the NAV means
    you cannot read the NAV without reading whether it can be trusted.

    `available=False` means the database was read successfully and no canonical
    state has yet been prepared. An unreadable/malformed state is UNKNOWN, never
    folded into that known absence.
    """
    if error or available is None:
        return Row("book", "Book", "UNKNOWN", UNKNOWN,
                   error or "canonical state could not be read", as_of)
    if not available:
        return Row("book", "Book", "NOT PREPARED", PENDING,
                   "no canonical SessionState has been persisted", as_of)
    if None in (slots_used, slots_total, nav, cash):
        return Row("book", "Book", "UNKNOWN", UNKNOWN,
                   "canonical state lacks book valuation or slot fields", as_of)
    flags = []
    if blocked:
        flags.append("BLOCKED")
    if unresolved_terminals:
        flags.append(f"UNRESOLVED TERMINALS {unresolved_terminals}")
    if unpriced_securities:
        flags.append(f"UNPRICED {unpriced_securities}")
    status = FAIL if flags else OK
    detail = " · ".join(flags) if flags else (
        f"cash ${cash:,.0f} · {pending_actions or 0} pending")
    return Row("book", "Book",
               f"{slots_used}/{slots_total} slots · NAV ${nav:,.0f}",
               status, detail, as_of, freshness=timedelta(days=4))


def terminals_row(*, counters: Optional[dict] = None,
                  current_unresolved: Optional[int] = None,
                  current_pending: Optional[int] = None,
                  as_of: Optional[datetime] = None,
                  error: Optional[str] = None) -> Row:
    """The settlement counters, which are the honest headline.

    A book that BLOCKS its terminations completes and reports a plausible
    return, so these are the only place that failure is visible. The specific
    reading worth surfacing: `derived_last_mark_settlements == 0` alongside a
    nonzero `unresolved_terminal_events` means the book is blocking rather than
    settling, and every number downstream of it is unevaluable.
    """
    if error:
        return Row("terminals", "Terminals", "UNKNOWN", UNKNOWN, error, as_of)
    if current_unresolved is not None or current_pending is not None:
        if current_unresolved is None or current_pending is None:
            return Row("terminals", "Terminals", "UNKNOWN", UNKNOWN,
                       "canonical terminal state is incomplete", as_of)
        value = (f"unresolved {current_unresolved} · "
                 f"carried {current_pending}")
        if current_unresolved:
            return Row("terminals", "Terminals",
                       f"UNRESOLVED {current_unresolved}", FAIL,
                       value + " · canonical current state", as_of,
                       freshness=timedelta(days=4))
        if current_pending:
            return Row("terminals", "Terminals", value, WARN,
                       "terms are still inside the documented carry window",
                       as_of, freshness=timedelta(days=4))
        return Row("terminals", "Terminals", "CLEAR", OK,
                   "no unresolved or carried terminal event in canonical state; "
                   "cumulative settlement mix is not persisted here",
                   as_of, freshness=timedelta(days=4))
    if not counters:
        return Row("terminals", "Terminals", "NONE YET", PENDING,
                   "no terminal events resolved on this book", as_of)
    g = lambda k: int(counters.get(k, 0) or 0)                    # noqa: E731
    unresolved, last_mark = g("unresolved_terminal_events"), g(
        "derived_last_mark_settlements")
    parts = (f"exact {g('exact_terminal_settlements')}"
             f" · print {g('market_exit_terminal_settlements')}"
             f" · last-mark {last_mark}"
             f" · zero {g('orphan_zero_writeoffs')}"
             f" · carried {g('pending_terms_carried')}")
    if unresolved and not last_mark:
        return Row("terminals", "Terminals", f"UNRESOLVED {unresolved}", FAIL,
                   "blocking rather than settling — downstream numbers are "
                   "unevaluable · " + parts, as_of)
    if unresolved:
        return Row("terminals", "Terminals", f"unresolved {unresolved}", WARN,
                   parts, as_of)
    return Row("terminals", "Terminals", parts, OK,
               "no unresolved terminal events", as_of)


def broker_row(*, available: Optional[bool], positions: Optional[int] = None,
               agrees: Optional[bool] = None,
               completeness: Optional[str] = None,
               runtime_state: Optional[str] = None,
               working_orders: Optional[int] = None,
               active_commands: Optional[int] = None,
               uncertain_commands: Optional[int] = None,
               command_as_of: Optional[datetime] = None,
               as_of: Optional[datetime] = None,
               error: Optional[str] = None) -> Row:
    """Broker state, shown for RECONCILIATION only.

    The dependency direction is `shadow -> Sentinel -> broker`, never the
    reverse, so this row must never read as an input to anything. The rich form
    shows the newest persisted observation and command-journal hazards without
    claiming a reconciliation verdict that was not made durable. The legacy
    `agrees` form remains for pure-model callers that already hold a verdict.
    """
    if error or available is None:
        return Row("broker", "Broker", "UNKNOWN", UNKNOWN,
                   error or "durable broker evidence could not be read", as_of)
    if not available:
        return Row("broker", "Broker", "NOT SYNCED", PENDING,
                   "no durable broker observation yet", as_of)
    if positions is None:
        return Row("broker", "Broker", "UNKNOWN", UNKNOWN,
                   "broker observation has no position count", as_of)

    # Backward-compatible pure-model surface for callers that already have a
    # reconciliation verdict but not the richer durable observation fields.
    if completeness is None and runtime_state is None:
        if agrees is False:
            return Row("broker", "Broker", f"{positions} positions", FAIL,
                       "DISAGREES with the shadow — the shadow is authoritative",
                       as_of, freshness=timedelta(days=4))
        return Row("broker", "Broker", f"{positions} positions", OK,
                   "agrees with the shadow", as_of,
                   freshness=timedelta(days=4))

    complete = str(completeness or "").upper()
    runtime = str(runtime_state or "").upper()
    working = int(working_orders or 0)
    active = int(active_commands or 0)
    uncertain = int(uncertain_commands or 0)
    value = f"{positions} positions · {working} working"
    journal_age = (f" · journal {command_as_of.isoformat()}"
                   if command_as_of else "")
    detail = (f"observation {complete or 'UNKNOWN'} · reconciliation "
              f"{runtime or 'UNKNOWN'} · {active} active command(s)"
              f"{journal_age}")
    if not complete or not runtime:
        return Row("broker", "Broker", value, UNKNOWN,
                   detail, as_of, freshness=timedelta(days=4))
    if complete != "COMPLETE":
        return Row("broker", "Broker", value, FAIL,
                   detail, as_of, freshness=timedelta(days=4))
    if runtime != "RUNNING" or uncertain:
        if uncertain:
            detail += f" · {uncertain} indeterminate command(s)"
        return Row("broker", "Broker", value, FAIL,
                   detail, as_of, freshness=timedelta(days=4))
    return Row("broker", "Broker", value, OK, detail, as_of,
               freshness=timedelta(days=4))


def automation_row(*, installed: Optional[bool] = False,
                   enabled: Optional[bool] = None,
                   killed: Optional[bool] = None,
                   generation: Optional[int] = None,
                   updated_at: Optional[datetime] = None,
                   error: Optional[str] = None) -> Row:
    """Durable automation policy, distinct from supervisor health."""
    if error or installed is None:
        return Row("automation", "Automation", "UNKNOWN", UNKNOWN,
                   error or "automation installation could not be read",
                   updated_at)
    if not installed:
        return Row("automation", "Automation", "NOT INSTALLED", PENDING,
                   "no durable automation control schema exists")
    if enabled is None or killed is None or generation is None:
        return Row("automation", "Automation", "CORRUPT", FAIL,
                   "durable automation control singleton is incomplete",
                   updated_at)
    suffix = f"generation {generation}"
    if not enabled:
        kill = "kill engaged" if killed else "kill released"
        return Row("automation", "Automation", "DISABLED", PENDING,
                   f"supervisor-healthy and operationally inert · {kill} · "
                   f"{suffix}", updated_at)
    if killed:
        return Row("automation", "Automation", "ENABLED · KILLED", WARN,
                   f"supervisor-healthy but broker access is blocked · "
                   f"{suffix}", updated_at)
    return Row("automation", "Automation", "ENABLED · KILL RELEASED", OK,
               f"operational policy permits leader election · {suffix}",
               updated_at)


def automation_leader_row(*, installed: Optional[bool],
                          enabled: Optional[bool] = None,
                          killed: Optional[bool] = None,
                          holder: Optional[str] = None,
                          fence: Optional[int] = None,
                          heartbeat_at: Optional[datetime] = None,
                          expires_at: Optional[datetime] = None,
                          active: Optional[bool] = None,
                          error: Optional[str] = None) -> Row:
    """Current database-fenced leader lease, evaluated by database time."""
    if error or installed is None:
        return Row("automation_leader", "Automation leader", "UNKNOWN",
                   UNKNOWN, error or "leader lease could not be read")
    if not installed:
        return Row("automation_leader", "Automation leader", "NOT INSTALLED",
                   PENDING, "no durable leader lease exists")
    lease = (f"holder {holder or 'none'} · fence "
             f"{fence if fence is not None else 'unknown'} · heartbeat "
             f"{heartbeat_at.isoformat() if heartbeat_at else 'none'} · "
             f"expiry {expires_at.isoformat() if expires_at else 'none'}")
    if enabled is None or killed is None or active is None:
        return Row("automation_leader", "Automation leader", "UNKNOWN",
                   UNKNOWN, lease, heartbeat_at)
    if not enabled or killed:
        return Row("automation_leader", "Automation leader",
                   "INACTIVE BY POLICY", PENDING, lease, heartbeat_at)
    if not active:
        return Row("automation_leader", "Automation leader", "NO LIVE LEADER",
                   WARN, lease, heartbeat_at)
    return Row("automation_leader", "Automation leader",
               f"{holder} · fence {fence}", OK, lease, heartbeat_at)


def automation_cycle_row(*, installed: Optional[bool],
                         enabled: Optional[bool] = None,
                         cycle_id: Optional[str] = None,
                         state: Optional[str] = None,
                         decision_session: Optional[str] = None,
                         effective_session: Optional[str] = None,
                         next_wake_at: Optional[datetime] = None,
                         clean_reconciliation_id: Optional[str] = None,
                         failure_code: Optional[str] = None,
                         failure_detail: Optional[str] = None,
                         updated_at: Optional[datetime] = None,
                         error: Optional[str] = None) -> Row:
    """Latest durable cycle, including its next wake and last clean proof."""
    if error or installed is None:
        return Row("automation_cycle", "Automation cycle", "UNKNOWN", UNKNOWN,
                   error or "automation cycle could not be read", updated_at)
    if not installed:
        return Row("automation_cycle", "Automation cycle", "NOT INSTALLED",
                   PENDING, "no durable automation cycle schema exists")
    if not cycle_id:
        detail = ("no daily cycle has been recorded · next wake "
                  f"{next_wake_at.isoformat() if next_wake_at else 'none'}")
        if failure_code or failure_detail:
            detail += (f" · failure {failure_code or 'UNCLASSIFIED'}: "
                       f"{failure_detail or 'no detail'}")
        return Row("automation_cycle", "Automation cycle", "NO CYCLES",
                   FAIL if failure_code or failure_detail else (
                       WARN if enabled else PENDING), detail)
    normalized = str(state or "").upper()
    detail = (
        f"cycle {cycle_id} · decision {decision_session or 'unknown'} · "
        f"effective {effective_session or 'unknown'} · next wake "
        f"{next_wake_at.isoformat() if next_wake_at else 'none'} · last "
        f"clean reconciliation {clean_reconciliation_id or 'none'}")
    if failure_code or failure_detail:
        detail += (f" · failure {failure_code or 'UNCLASSIFIED'}: "
                   f"{failure_detail or 'no detail'}")
    if not normalized:
        status = UNKNOWN
    elif normalized == "BLOCKED":
        status = FAIL
    elif normalized == "RETRY_WAIT":
        status = WARN
    elif normalized in {"SUCCEEDED", "MISSED_STATE_ONLY", "SUPERSEDED"}:
        status = OK
    else:
        status = OK if enabled else PENDING
    return Row("automation_cycle", "Automation cycle",
               normalized or "UNKNOWN", status, detail, updated_at)


def automation_alerts_row(*, installed: Optional[bool],
                          pending: Optional[int] = None,
                          dead_letter: Optional[int] = None,
                          unacknowledged: Optional[int] = None,
                          as_of: Optional[datetime] = None,
                          error: Optional[str] = None) -> Row:
    """Durable outbox pressure; missing data never renders as zero."""
    if error or installed is None:
        return Row("automation_alerts", "Automation alerts", "UNKNOWN",
                   UNKNOWN, error or "alert outbox could not be read", as_of)
    if not installed:
        return Row("automation_alerts", "Automation alerts", "NOT INSTALLED",
                   PENDING, "no durable alert outbox exists")
    if pending is None or dead_letter is None or unacknowledged is None:
        return Row("automation_alerts", "Automation alerts", "UNKNOWN",
                   UNKNOWN, "alert counts are incomplete", as_of)
    value = (f"{pending} pending · {dead_letter} DLQ · "
             f"{unacknowledged} unacked")
    status = FAIL if dead_letter else (
        WARN if pending or unacknowledged else OK)
    return Row("automation_alerts", "Automation alerts", value, status,
               "SELECT-only projection of the durable alert outbox", as_of)


def execution_authority_row(
        *, installed: Optional[bool] = False,
        runtime_verdict: Optional[str] = None,
        runtime_detail: Optional[str] = None,
        checked_at: Optional[datetime] = None,
        lifecycle_status: Optional[str] = None,
        certificate_sha256: Optional[str] = None,
        expires_at: Optional[datetime] = None,
        authority_mode: Optional[str] = None,
        historical_causality: Optional[str] = None,
        maximum_exposure: Optional[str] = None,
        authority_generation: Optional[int] = None,
        lifecycle_current: Optional[bool] = None,
        verdict_binding_matches: Optional[bool] = None,
        error: Optional[str] = None) -> Row:
    """Durable runtime verdict plus clearly non-authoritative lifecycle facts.

    Certificate presence, lifecycle state and expiry are useful facts, but are
    not a signature/environment/account verification.  Only a verdict already
    persisted by the automation authority checker may render as valid here.
    """
    if error or installed is None:
        return Row("authority", "Paper execution authority", "UNKNOWN",
                   UNKNOWN, error or "execution authority could not be read",
                   checked_at)
    lifecycle = (
        f"lifecycle-only: {lifecycle_status or 'no active certificate'}"
        f" · certificate "
        f"{certificate_sha256[:12] if certificate_sha256 else 'none'}"
        f" · expires {expires_at.isoformat() if expires_at else 'unknown'}"
        f" · mode {authority_mode or 'unknown'}"
        f" · historical causality {historical_causality or 'unknown'}"
        f" · maximum exposure {maximum_exposure or 'not separately bounded'}"
        f" · authority generation "
        f"{authority_generation if authority_generation is not None else 'none'}")
    if not installed:
        return Row("authority", "Paper execution authority", "NOT INSTALLED",
                   FAIL, "no durable certificate authority schema exists")
    lifecycle_failure = None
    if lifecycle_status != "ACTIVE":
        lifecycle_failure = (
            "durable certificate lifecycle is "
            f"{lifecycle_status or 'missing'}")
    elif not certificate_sha256:
        lifecycle_failure = "durable active certificate identity is missing"
    elif lifecycle_current is not True:
        lifecycle_failure = (
            "durable active certificate is not proven current and unrevoked")

    if lifecycle_failure is not None:
        verdict = str(runtime_verdict or "NO CURRENT AUTHORITY").upper()
        return Row("authority", "Paper execution authority",
                   f"{verdict} · LIFECYCLE INVALID", FAIL,
                   f"{lifecycle_failure}; persisted runtime verdict cannot "
                   f"override it; {lifecycle}", checked_at)
    if not runtime_verdict:
        return Row("authority", "Paper execution authority", "UNKNOWN",
                   UNKNOWN,
                   "no durable runtime authority verdict; " + lifecycle)
    verdict = str(runtime_verdict).upper()
    if verdict in {"VALID", "AUTHORIZED", "PASS"}:
        if verdict_binding_matches is not True:
            return Row(
                "authority", "Paper execution authority",
                f"{verdict} · VERDICT BINDING INVALID", FAIL,
                "persisted runtime verdict is not bound to the currently "
                f"active certificate; {lifecycle}", checked_at)
        status = OK
    elif verdict in {"UNKNOWN", "NOT_CHECKED", "UNCHECKED"}:
        status = UNKNOWN
    else:
        status = FAIL
    detail = (f"persisted runtime verdict: {runtime_detail or 'no detail'}; "
              f"{lifecycle}")
    digest = f" · {certificate_sha256[:12]}" if certificate_sha256 else ""
    return Row("authority", "Paper execution authority",
               f"{verdict}{digest}", status, detail, checked_at,
               freshness=timedelta(minutes=5))


__all__ = ["FAIL", "FINANCIAL_AUTHORITY_ROW_KEYS", "NO_PERFORMANCE_HERE",
           "OK", "PENDING", "Panel", "Row", "SHADOW_ROW_KEYS",
           "TRIAL_ROW_KEYS", "UNKNOWN", "WARN", "automation_alerts_row",
           "automation_cycle_row", "automation_leader_row", "automation_row",
           "book_row", "broker_row",
           "execution_authority_row", "exposure_row", "feed_row", "ingest_row",
           "ownership_row", "paper_reconciliation_row",
           "shadow_metric_row", "shadow_verification_row", "terminals_row"]
