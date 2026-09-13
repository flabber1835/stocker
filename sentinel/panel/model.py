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
from decimal import Decimal, InvalidOperation
from typing import Mapping, Optional

from sentinel.operational_status import (
    FAIL,
    OK,
    PENDING,
    UNKNOWN,
    WARN,
    RecoveryEvidence,
    effective_status,
)

#: Performance is permitted only inside the versioned trial-verification
#: projection.  Kept as a compatibility name so old callers fail visibly if
#: they still expect the former condition-only contract.
NO_PERFORMANCE_HERE = False

MAXIMUM_FUTURE_SKEW = timedelta(seconds=5)

_STATUS_RANK = {OK: 0, PENDING: 1, WARN: 2, FAIL: 3, UNKNOWN: 3}

TRIAL_ROW_KEYS = frozenset({
    "trial_verification", "actual_account", "trial_return",
    "trial_drawdown", "trial_annualized", "trial_intent",
})

SHADOW_ROW_KEYS = frozenset({
    "shadow_verification", "shadow_nav", "shadow_return",
})

FINANCIAL_AUTHORITY_ROW_KEYS = TRIAL_ROW_KEYS | SHADOW_ROW_KEYS
# Verification verdicts are current safety facts.  The numeric P/L/account
# projections remain informational for operational health, but a withdrawn
# trial/shadow verification must be able to turn the headline red.
OPERATIONAL_INFORMATIONAL_ROW_KEYS = (
    FINANCIAL_AUTHORITY_ROW_KEYS
    - {"trial_verification", "shadow_verification"})


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
    #: Required-current facts fail red when stale unless a bounded reviewed
    #: recovery is durably active. Historical/informational rows leave this
    #: false and retain the old visible-staleness behavior.
    required_current: bool = False
    recovery: Optional[RecoveryEvidence] = None
    #: Producer-derived validity boundary. This is preferred over an elapsed
    #: duration when the next durable cycle/session deadline is known.
    valid_until: Optional[datetime] = None

    def staleness(self, now: datetime) -> Optional[timedelta]:
        return None if self.as_of is None else now - self.as_of

    def is_stale(self, now: datetime) -> bool:
        if self.valid_until is not None:
            return now > self.valid_until
        if self.as_of is None or self.freshness is None:
            return False
        return (now - self.as_of) > self.freshness

    def is_future(self, now: datetime) -> bool:
        return (self.as_of is not None
                and self.as_of - now > MAXIMUM_FUTURE_SKEW)

    def effective_status(self, now: datetime) -> str:
        """Apply the shared operator recoverability policy."""
        return effective_status(
            self.status, stale=self.is_stale(now), future=self.is_future(now),
            required_current=self.required_current, recovery=self.recovery,
            now=now)


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
        """The worst row wins; only optional PENDING rows are omitted.

        A half-built system is full of pending rows; letting them drive the
        headline would leave it permanently amber. A required-current PENDING
        fact is a failed dependency and therefore still participates as red.
        """
        live = [
            r.effective_status(self.now) for r in self.rows
            if r.status != PENDING or r.required_current
        ]
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
        live = [
            r.effective_status(self.now) for r in self.rows
            if (r.key not in OPERATIONAL_INFORMATIONAL_ROW_KEYS
                and (r.status != PENDING or r.required_current))
        ]
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
                 valid_until: Optional[datetime] = None,
                 recovery: Optional[RecoveryEvidence] = None,
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
                   freshness=timedelta(minutes=10), required_current=True,
                   recovery=recovery, valid_until=valid_until)
    if controller_active:
        return Row("exposure", "Exposure", f"{exposure:.2f} NOT ADOPTED", WARN,
                   f"canonical controller decision has no current plan{where}",
                   as_of, freshness=timedelta(minutes=10),
                   required_current=True, recovery=recovery,
                   valid_until=valid_until)
    status = PENDING if adopted else WARN
    detail = ("durable current rollout pins exposure at 1.00"
              if adopted else "pinned rollout has no current plan")
    return Row("exposure", "Exposure", f"{exposure:.2f} PINNED", status,
               detail + where, as_of, freshness=timedelta(minutes=10),
               required_current=True, recovery=recovery,
               valid_until=valid_until)


#: A verdict older than this describes a corpus that has since been through a
#: daily ingest. Shown, never hidden — but labelled, because a stale PASS
#: presented as current is the one way an old verdict does harm.
VERDICT_STALE_AFTER = timedelta(hours=26)


def feed_row(*, frontier: Optional[str], sessions_behind: Optional[int],
             ready: Optional[bool], checks_passed: int, checks_total: int,
             as_of: Optional[datetime], error: Optional[str] = None,
             ingest_running: bool = False,
             checked_at: Optional[datetime] = None,
             ingest_updated_at: Optional[datetime] = None,
             frontier_ahead: bool = False) -> Row:
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
            return Row("feed", "Feed", "BUILDING", WARN,
                       f"frontier not readable during an ingest — {error}",
                       as_of, required_current=True,
                       recovery=RecoveryEvidence(
                           phase="FEED_INGEST", automatic=True,
                           deadline=(ingest_updated_at + timedelta(minutes=15)
                                     if ingest_updated_at else None)))
        return Row("feed", "Feed", "UNREADABLE", UNKNOWN,
                   f"could not read the feed — {error}", as_of)
    if frontier is None:
        return Row("feed", "Feed", "EMPTY", WARN,
                   "no sessions ingested yet — run feed-seed", as_of,
                   required_current=True)
    if frontier_ahead:
        return Row("feed", "Feed", f"{frontier} · FRONTIER AHEAD", FAIL,
                   "frontier is in the future or is not an exchange session",
                   as_of, required_current=True)
    behind = ("" if sessions_behind is None
              else f" · {sessions_behind} session{'s' if sessions_behind != 1 else ''} behind")
    # THREE states, not two. `ready is None` means the contract check did not
    # COMPLETE — it is the expensive read and it times out against a corpus
    # being bulk-loaded. Reporting that as "contract NOT READY" would raise a
    # red alarm every time someone opened the panel during a seed, which is
    # both wrong and the fastest way to teach an operator to ignore the colour.
    # Same rule as the crash brake's `evaluable`: one flag must not answer both
    # "the evidence says no" and "there is no evidence".
    if sessions_behind is None:
        return Row("feed", "Feed", f"{frontier} · LAG UNKNOWN", UNKNOWN,
                   "exchange-session currency could not be established",
                   as_of, required_current=True)
    if ready is None:
        return Row("feed", "Feed", f"{frontier}{behind}", WARN,
                   "contract NOT CHECKED — no verdict has ever been stored. "
                   "Run `check-data`; this is 'we have not asked', not 'the "
                   "corpus failed'.", as_of, required_current=True,
                   valid_until=(checked_at + VERDICT_STALE_AFTER
                                if checked_at else None))
    verdict = ("contract READY" if ready else "contract NOT READY")

    # WHEN IT WAS MEASURED, always, and an explicit warning once it is old.
    # The page no longer computes the contract — it reads the last stored
    # verdict — so the age is the only thing separating a current answer from
    # one that predates a re-ingest. Undated, a day-old PASS reads as now.
    age = ""
    if checked_at is not None:
        age = f" · checked {checked_at.isoformat()}"

    status = OK if ready else FAIL
    if ready and sessions_behind > 0:
        status = WARN if ingest_running else FAIL
    return Row("feed", "Feed", f"{frontier}{behind}", status,
               f"{verdict} {checks_passed}/{checks_total}{age}", as_of,
               required_current=True,
               recovery=(RecoveryEvidence(
                   phase="FEED_INGEST", automatic=True,
                   deadline=(ingest_updated_at + timedelta(minutes=15)
                             if ingest_updated_at else None))
                         if ingest_running and sessions_behind > 0 else None),
               valid_until=(checked_at + VERDICT_STALE_AFTER
                            if checked_at else None))


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
                   f"{kind} {pct:.0f}% · {chunks_done}/{chunks_total}", WARN,
                   detail, updated_at, freshness=timedelta(minutes=15),
                   required_current=True,
                   recovery=RecoveryEvidence(
                       phase="FEED_INGEST", automatic=True,
                       deadline=(updated_at + timedelta(minutes=15)
                                 if updated_at else None)))
    return Row("ingest", "Ingest", f"{kind} complete", OK, detail, updated_at)


def book_row(*, available: Optional[bool], slots_used: Optional[int] = None,
             slots_total: Optional[int] = None, nav: Optional[float] = None,
             cash: Optional[float] = None, blocked: Optional[int] = None,
             unresolved_terminals: Optional[int] = None,
             unpriced_securities: Optional[int] = None,
             pending_actions: Optional[int] = None,
             as_of: Optional[datetime] = None,
             valid_until: Optional[datetime] = None,
             recovery: Optional[RecoveryEvidence] = None,
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
               status, detail, as_of, freshness=timedelta(minutes=10),
               required_current=True, recovery=recovery,
               valid_until=valid_until)


def terminals_row(*, counters: Optional[dict] = None,
                  current_unresolved: Optional[int] = None,
                  current_pending: Optional[int] = None,
                  as_of: Optional[datetime] = None,
                  valid_until: Optional[datetime] = None,
                  recovery: Optional[RecoveryEvidence] = None,
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
                       freshness=timedelta(minutes=10), required_current=True,
                       valid_until=valid_until)
        if current_pending:
            return Row("terminals", "Terminals", value, WARN,
                       "terms are still inside the documented carry window",
                       as_of, freshness=timedelta(minutes=10),
                       required_current=True, recovery=recovery,
                       valid_until=valid_until)
        return Row("terminals", "Terminals", "CLEAR", OK,
                   "no unresolved or carried terminal event in canonical state; "
                   "cumulative settlement mix is not persisted here",
                   as_of, freshness=timedelta(minutes=10),
                   required_current=True, recovery=recovery,
                   valid_until=valid_until)
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
               recovery: Optional[RecoveryEvidence] = None,
               valid_until: Optional[datetime] = None,
               error: Optional[str] = None) -> Row:
    """Broker state, shown for RECONCILIATION only.

    The dependency direction is `shadow -> Sentinel -> broker`, never the
    reverse, so this row must never read as an input to anything. The rich form
    shows the newest persisted observation and command-journal hazards without
    claiming a reconciliation verdict that was not made durable. The legacy
    `agrees` form remains for pure-model callers that already hold a verdict.
    """
    if error or available is None:
        return Row(
            "broker", "Broker", "RETRYING" if recovery else "UNKNOWN",
            WARN if recovery else UNKNOWN,
            error or "durable broker evidence could not be read", as_of,
            required_current=True, recovery=recovery,
            valid_until=valid_until)
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
                       as_of, freshness=timedelta(minutes=10),
                       required_current=True, valid_until=valid_until)
        return Row("broker", "Broker", f"{positions} positions", OK,
                   "agrees with the shadow", as_of,
                   freshness=timedelta(minutes=10), required_current=True,
                   valid_until=valid_until)

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
                   detail, as_of, freshness=timedelta(minutes=10),
                   required_current=True, recovery=recovery,
                   valid_until=valid_until)
    if complete != "COMPLETE":
        return Row("broker", "Broker", value, FAIL,
                   detail, as_of, freshness=timedelta(minutes=10),
                   required_current=True, recovery=recovery,
                   valid_until=valid_until)
    if runtime != "RUNNING" or uncertain:
        if uncertain:
            detail += f" · {uncertain} indeterminate command(s)"
        status = WARN if recovery is not None else FAIL
        return Row("broker", "Broker", value, status,
                   detail, as_of, freshness=timedelta(minutes=10),
                   required_current=True, recovery=recovery,
                   valid_until=valid_until)
    return Row("broker", "Broker", value, OK, detail, as_of,
               freshness=timedelta(minutes=10), required_current=True,
               recovery=recovery, valid_until=valid_until)


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
        return Row("automation", "Automation", "DISABLED", WARN,
                   f"supervisor-healthy and operationally inert · {kill} · "
                   f"{suffix}", updated_at)
    if killed:
        return Row("automation", "Automation", "ENABLED · KILLED", FAIL,
                   f"operator action required; broker access is blocked · "
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
                          recovery_deadline: Optional[datetime] = None,
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
                   WARN, lease, heartbeat_at, required_current=bool(enabled),
                   recovery=RecoveryEvidence(
                       phase="LEADER_ELECTION", automatic=True,
                       deadline=recovery_deadline))
    return Row("automation_leader", "Automation leader",
               f"{holder} · fence {fence}", OK, lease, heartbeat_at,
               freshness=timedelta(seconds=30), required_current=bool(enabled),
               valid_until=expires_at)


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
                         attempt_count: Optional[int] = None,
                         phase_attempt_count: Optional[int] = None,
                         phase_max_attempts: Optional[int] = None,
                         first_failure_at: Optional[str] = None,
                         exception_fingerprint: Optional[str] = None,
                         terminal_reason: Optional[str] = None,
                         prepare_at: Optional[datetime] = None,
                         execution_open_at: Optional[datetime] = None,
                         execute_at: Optional[datetime] = None,
                         execution_close_at: Optional[datetime] = None,
                         created_at: Optional[datetime] = None,
                         completed_at: Optional[datetime] = None,
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
                       WARN if enabled else PENDING), detail,
                   required_current=bool(enabled))
    normalized = str(state or "").upper()
    detail = (
        f"cycle {cycle_id} · decision {decision_session or 'unknown'} · "
        f"effective {effective_session or 'unknown'} · next wake "
        f"{next_wake_at.isoformat() if next_wake_at else 'none'} · last "
        f"clean reconciliation {clean_reconciliation_id or 'none'}")
    if failure_code or failure_detail:
        detail += (f" · failure {failure_code or 'UNCLASSIFIED'}: "
                   f"{failure_detail or 'no detail'}")
    recovery = None
    if normalized == "RETRY_WAIT":
        status = WARN
        recovery = RecoveryEvidence(
            phase="AUTOMATION_RETRY",
            automatic=True,
            attempt=(phase_attempt_count if phase_attempt_count is not None
                     else attempt_count),
            maximum_attempts=phase_max_attempts,
            next_attempt_at=next_wake_at,
            operator_required=bool(terminal_reason))
    elif failure_code or failure_detail:
        status = FAIL
    elif not normalized:
        status = UNKNOWN
    elif normalized in {"BLOCKED", "MISSED_STATE_ONLY", "SUPERSEDED"}:
        status = FAIL
    elif normalized == "SUCCEEDED":
        status = OK if clean_reconciliation_id else FAIL
        if not clean_reconciliation_id:
            detail += " · invalid success: clean reconciliation is absent"
    else:
        status = WARN if enabled else PENDING
        deadlines = {
            "DISCOVERED": prepare_at,
            "REFRESHING_DATA": execution_open_at,
            "PREPARING": execution_open_at,
            "PLAN_READY": execution_close_at,
            "WAITING_OPEN": execution_close_at,
            "EXECUTING": execution_close_at,
            "RECONCILING": execution_close_at,
        }
        recovery = RecoveryEvidence(
            phase=f"AUTOMATION_{normalized or 'UNKNOWN'}",
            automatic=True, next_attempt_at=next_wake_at,
            deadline=deadlines.get(normalized))
    return Row("automation_cycle", "Automation cycle",
               normalized or "UNKNOWN", status, detail, updated_at,
               required_current=bool(enabled), recovery=recovery)


_AUTOMATION_STEP_DEFINITIONS = (
    ("discovery", "1 · Cycle discovery"),
    ("data", "2 · Data refresh"),
    ("prepare", "3 · Plan preparation"),
    ("open", "4 · Market-open wait"),
    ("transport", "5 · Order transport"),
    ("reconcile", "6 · Broker reconciliation"),
    ("complete", "7 · Cycle completion"),
)
_AUTOMATION_STATE_STEP = {
    "DISCOVERED": 0,
    "REFRESHING_DATA": 1,
    "PREPARING": 2,
    "PLAN_READY": 3,
    "WAITING_OPEN": 3,
    "EXECUTING": 4,
    "RECONCILING": 5,
    "SUCCEEDED": 6,
    "MISSED_STATE_ONLY": 6,
    "SUPERSEDED": 6,
    "BLOCKED": 6,
}
_AUTOMATION_RETRY_STEP = {
    "REFRESH": 1,
    "PREFLIGHT_RECOVER": 1,
    "PREPARE": 2,
    "EXECUTE": 4,
    "RECOVER": 5,
}


def automation_step_rows(
        *, installed: Optional[bool], enabled: Optional[bool] = None,
        cycle: Optional[Mapping] = None, events=(),
        error: Optional[str] = None) -> list[Row]:
    """Expand one durable cycle into explicit, non-authoritative progress.

    Later permitted transitions prove earlier gates were passed, even when an
    optional intermediate state was skipped. They never prove a future step.
    """
    if error or installed is None:
        detail = error or "automation step evidence could not be read"
        return [
            Row(f"automation_step_{key}", label, "UNKNOWN", UNKNOWN, detail)
            for key, label in _AUTOMATION_STEP_DEFINITIONS
        ]
    if not installed:
        return [
            Row(f"automation_step_{key}", label, "NOT INSTALLED", PENDING,
                "automation is not installed")
            for key, label in _AUTOMATION_STEP_DEFINITIONS
        ]
    if not enabled:
        return [
            Row(f"automation_step_{key}", label, "MAINTENANCE", PENDING,
                "automation is deliberately disabled")
            for key, label in _AUTOMATION_STEP_DEFINITIONS
        ]
    cycle = dict(cycle or {})
    if not cycle.get("cycle_id"):
        return [
            Row(
                f"automation_step_{key}", label,
                "MISSING" if index == 0 else "NOT REACHED",
                FAIL if index == 0 else PENDING,
                "enabled automation has no durable current cycle",
                required_current=index == 0)
            for index, (key, label) in enumerate(
                _AUTOMATION_STEP_DEFINITIONS)
        ]

    state = str(cycle.get("state") or "").upper()
    diagnostic = cycle.get("diagnostic")
    diagnostic = dict(diagnostic) if isinstance(diagnostic, Mapping) else {}
    retry_phase = str(
        cycle.get("retry_phase") or diagnostic.get("retry_phase") or ""
    ).upper()
    terminal = state in {"SUCCEEDED", "MISSED_STATE_ONLY", "SUPERSEDED", "BLOCKED"}

    normalized_events = []
    for event in events or ():
        if not isinstance(event, Mapping):
            continue
        normalized_events.append(dict(event))
    observed_indices = []
    step_times: dict[int, datetime] = {}
    for event in normalized_events:
        for field in ("from_state", "to_state"):
            event_state = str(event.get(field) or "").upper()
            if event_state in _AUTOMATION_STATE_STEP:
                index = _AUTOMATION_STATE_STEP[event_state]
                observed_indices.append(index)
                at = event.get("at")
                if isinstance(at, datetime):
                    step_times[index] = max(step_times.get(index, at), at)

    state_index = _AUTOMATION_STATE_STEP.get(state)
    if state == "RETRY_WAIT":
        state_index = _AUTOMATION_RETRY_STEP.get(
            retry_phase, max(observed_indices, default=0))
    progress_index = max(
        [index for index in observed_indices if index < 6]
        + ([state_index] if state_index is not None and state_index < 6 else []),
        default=0)

    deadlines = {
        0: cycle.get("prepare_at"),
        1: cycle.get("execution_open_at"),
        2: cycle.get("execution_open_at"),
        3: cycle.get("execution_close_at"),
        4: cycle.get("execution_close_at"),
        5: cycle.get("execution_close_at"),
    }
    retry = RecoveryEvidence(
        phase=f"AUTOMATION_{retry_phase or 'RETRY'}",
        automatic=True,
        attempt=(cycle.get("phase_attempt_count")
                 if cycle.get("phase_attempt_count") is not None
                 else cycle.get("attempt_count")),
        maximum_attempts=cycle.get("phase_max_attempts"),
        next_attempt_at=cycle.get("next_wake_at"),
        operator_required=bool(cycle.get("terminal_reason")),
    )
    failed_index = None
    if terminal and state != "SUCCEEDED":
        failed_index = _AUTOMATION_RETRY_STEP.get(retry_phase, progress_index)

    rows: list[Row] = []
    for index, (key, label) in enumerate(_AUTOMATION_STEP_DEFINITIONS):
        row_key = f"automation_step_{key}"
        if index == 6 and terminal:
            success = (
                state == "SUCCEEDED"
                and bool(cycle.get("clean_reconciliation_id")))
            rows.append(Row(
                row_key, label, state, OK if success else FAIL,
                (f"clean reconciliation {cycle.get('clean_reconciliation_id')}"
                 if success else
                 f"{cycle.get('failure_code') or state}: "
                 f"{cycle.get('failure_detail') or ('clean reconciliation is absent'
                    if state == 'SUCCEEDED' else 'operator action required')}"),
                cycle.get("completed_at") or cycle.get("updated_at"),
                required_current=True))
            continue
        if failed_index == index:
            rows.append(Row(
                row_key, label, "FAILED", FAIL,
                f"{cycle.get('failure_code') or state}: "
                f"{cycle.get('failure_detail') or 'operator action required'}",
                cycle.get("updated_at"), required_current=True))
            continue
        if terminal:
            passed = index < progress_index or (
                state == "SUCCEEDED" and index < 6)
        else:
            passed = state_index is not None and index < state_index
        if passed:
            rows.append(Row(
                row_key, label, "COMPLETE", OK,
                f"durable cycle advanced beyond this gate to {state}",
                step_times.get(index) or cycle.get("updated_at")))
            continue
        if not terminal and index == state_index:
            if state == "RETRY_WAIT":
                attempt = retry.attempt if retry.attempt is not None else "?"
                maximum = (retry.maximum_attempts
                           if retry.maximum_attempts is not None else "?")
                value = f"RETRY {attempt}/{maximum}"
                detail = (
                    f"{retry_phase or 'UNKNOWN'} · next "
                    f"{cycle.get('next_wake_at') or 'unknown'}")
                recovery = retry
            else:
                value = state
                detail = (
                    f"current automatic step · deadline "
                    f"{deadlines.get(index) or 'unknown'}")
                recovery = RecoveryEvidence(
                    phase=f"AUTOMATION_{key.upper()}", automatic=True,
                    next_attempt_at=cycle.get("next_wake_at"),
                    deadline=deadlines.get(index))
            rows.append(Row(
                row_key, label, value, WARN, detail,
                cycle.get("updated_at"), required_current=True,
                recovery=recovery))
            continue
        rows.append(Row(
            row_key, label, "NOT REACHED", PENDING,
            "future step in the current durable cycle"))
    return rows


def automation_alerts_row(*, installed: Optional[bool],
                          pending: Optional[int] = None,
                          dead_letter: Optional[int] = None,
                          unacknowledged: Optional[int] = None,
                          retry_attempt: Optional[int] = None,
                          retry_max_attempts: Optional[int] = None,
                          next_attempt_at: Optional[datetime] = None,
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
    status = FAIL if dead_letter or unacknowledged else (
        WARN if pending else OK)
    return Row("automation_alerts", "Automation alerts", value, status,
               "SELECT-only projection of the durable alert outbox", as_of,
               required_current=True,
               recovery=(RecoveryEvidence(
                   phase="ALERT_DELIVERY", automatic=True,
                   attempt=retry_attempt,
                   maximum_attempts=retry_max_attempts,
                   next_attempt_at=next_attempt_at)
                         if pending and not dead_letter and not unacknowledged
                         else None))


def alert_dispatcher_row(*, installed: Optional[bool],
                         dispatchers: Optional[list[dict]] = None,
                         push_required: bool = False,
                         active_subscriptions: Optional[int] = None,
                         retired_subscriptions: Optional[int] = None,
                         last_push_success_at: Optional[datetime] = None,
                         last_push_failure_at: Optional[datetime] = None,
                         retry_attempt: Optional[int] = None,
                         retry_max_attempts: Optional[int] = None,
                         next_attempt_at: Optional[datetime] = None,
                         maximum_age_seconds: float = 30,
                         error: Optional[str] = None) -> Row:
    """Durable alert-dispatcher and first-party delivery health."""
    if error or installed is None:
        return Row("alert_dispatcher", "Alert delivery", "UNKNOWN", UNKNOWN,
                   error or "alert dispatcher health could not be read")
    if not installed:
        return Row("alert_dispatcher", "Alert delivery", "NOT INSTALLED",
                   PENDING, "no durable alert-dispatcher health schema exists")
    if not dispatchers:
        return Row("alert_dispatcher", "Alert delivery", "NO DISPATCHER",
                   FAIL, "health schema exists but no dispatcher has registered")

    failed = []
    degraded = []
    for item in dispatchers:
        identity = str(item.get("dispatcher_id") or "unknown")
        state = str(item.get("state") or "UNKNOWN").upper()
        age = item.get("heartbeat_age_seconds")
        if (not isinstance(age, (int, float)) or age < 0
                or age > maximum_age_seconds or state == "FAILED"
                or state not in {"STARTING", "HEALTHY", "DEGRADED"}):
            failed.append(identity)
        elif state != "HEALTHY":
            degraded.append(identity)
    healthy = len(dispatchers) - len(failed) - len(degraded)
    value = (f"{healthy} healthy · {len(degraded)} degraded · "
             f"{len(failed)} failed")
    missing_push = push_required and active_subscriptions == 0
    unknown_push = push_required and active_subscriptions is None
    status = FAIL if failed or missing_push or unknown_push else (
        WARN if degraded else OK)
    detail_parts = []
    for item in dispatchers:
        detail_parts.append(
            f"{item.get('dispatcher_id') or 'unknown'} "
            f"{item.get('state') or 'UNKNOWN'} · heartbeat "
            f"{item.get('heartbeat_age_seconds')}s · failures "
            f"{item.get('consecutive_failures')} · last success "
            f"{item.get('last_success_at') or 'none'} · "
            f"{item.get('last_error') or 'no error'}")
    if push_required:
        detail_parts.append(
            "Web Push subscriptions "
            f"{active_subscriptions if active_subscriptions is not None else 'UNKNOWN'} active"
            f" · {retired_subscriptions if retired_subscriptions is not None else 'UNKNOWN'} retired"
            f" · last success {last_push_success_at or 'none'}"
            f" · last failure {last_push_failure_at or 'none'}")
    as_of = max(
        (item.get("heartbeat_at") for item in dispatchers
         if item.get("heartbeat_at") is not None), default=None)
    return Row("alert_dispatcher", "Alert delivery", value, status,
               " | ".join(detail_parts), as_of, required_current=True,
                   recovery=(RecoveryEvidence(
                   phase="ALERT_TRANSPORT", automatic=True,
                   attempt=retry_attempt,
                   maximum_attempts=retry_max_attempts,
                   next_attempt_at=next_attempt_at)
                         if degraded and not failed and not missing_push
                         and not unknown_push else None))


def alpaca_account_row(
        *, available: Optional[bool], broker: Optional[str] = None,
        account_id: Optional[str] = None,
        expected_account_id: Optional[str] = None,
        status: Optional[str] = None, flags: Optional[dict] = None,
        equity=None, cash=None, buying_power=None, multiplier=None,
        observed_at: Optional[datetime] = None,
        valid_until: Optional[datetime] = None,
        recovery: Optional[RecoveryEvidence] = None,
        error: Optional[str] = None) -> Row:
    """Latest account result already admitted through the execution membrane."""
    if error or available is None:
        return Row(
            "alpaca_account", "Alpaca Account",
            "RETRYING" if recovery else "UNKNOWN",
            WARN if recovery else UNKNOWN,
            error or "durable account evidence could not be read", observed_at,
            required_current=True, recovery=recovery,
            valid_until=valid_until)
    if not available:
        return Row(
            "alpaca_account", "Alpaca Account", "NO DURABLE SNAPSHOT", FAIL,
            "run the guarded account-snapshot path; the panel never polls Alpaca",
            observed_at, required_current=True)
    normalized_broker = str(broker or "").lower()
    normalized_status = str(status or "").upper()
    if (normalized_broker != "alpaca" or not account_id
            or not expected_account_id):
        return Row(
            "alpaca_account", "Alpaca Account", "IDENTITY UNKNOWN", UNKNOWN,
            "broker, observed account, and bound account are all required",
            observed_at, required_current=True)
    if account_id != expected_account_id:
        return Row(
            "alpaca_account", "Alpaca Account", "IDENTITY MISMATCH", FAIL,
            f"observed {account_id} · bound {expected_account_id}", observed_at,
            required_current=True)
    if any(value is None for value in (
            equity, cash, buying_power, multiplier)):
        return Row(
            "alpaca_account", "Alpaca Account", "ECONOMICS INCOMPLETE", UNKNOWN,
            f"account {account_id} lacks equity/cash/buying-power/multiplier",
            observed_at, required_current=True)
    try:
        equity_value = Decimal(str(equity))
        cash_value = Decimal(str(cash))
        buying_power_value = Decimal(str(buying_power))
        multiplier_value = Decimal(str(multiplier))
    except (InvalidOperation, TypeError, ValueError) as exc:
        return Row(
            "alpaca_account", "Alpaca Account", "ECONOMICS INVALID", FAIL,
            f"account {account_id} has non-decimal economics", observed_at,
            required_current=True)
    flags = dict(flags or {})
    blocking = sorted(
        key for key in (
            "trading_blocked", "account_blocked", "trade_suspended_by_user")
        if flags.get(key) is True)
    economics_failures = []
    if not all(value.is_finite() for value in (
            equity_value, cash_value, buying_power_value, multiplier_value)):
        economics_failures.append("non-finite economics")
    else:
        if equity_value <= 0:
            economics_failures.append("nonpositive equity")
        if cash_value < 0:
            economics_failures.append("negative cash")
        if buying_power_value < 0:
            economics_failures.append("negative buying power")
        if multiplier_value != Decimal(1):
            economics_failures.append("multiplier is not cash-only 1")
        if abs(buying_power_value - cash_value) > Decimal("1.00"):
            economics_failures.append(
                "buying power differs from cash by more than $1")
    state_ok = (
        normalized_status == "ACTIVE" and not blocking
        and not economics_failures)
    value = f"{normalized_status or 'UNKNOWN'} · {account_id}"
    detail = (
        f"equity ${equity_value:,.2f} · cash ${cash_value:,.2f} · "
        f"buying power ${buying_power_value:,.2f} · multiplier {multiplier_value}"
        + (f" · FLAGS {', '.join(blocking)}" if blocking else
           " · no blocking flags")
        + (f" · CONTRACT {', '.join(economics_failures)}"
           if economics_failures else " · cash-only contract valid"))
    return Row(
        "alpaca_account", "Alpaca Account", value,
        OK if state_ok else FAIL, detail, observed_at,
        freshness=timedelta(minutes=10), required_current=True,
        recovery=recovery, valid_until=valid_until)


def backup_restore_row(
        *, base_at: Optional[datetime], restore_at: Optional[datetime],
        runtime_at: Optional[datetime] = None,
        base_proof: Optional[dict] = None,
        restore_proof: Optional[dict] = None,
        runtime_proof: Optional[dict] = None,
        now: datetime, recovery: Optional[RecoveryEvidence] = None,
        runtime_valid_until: Optional[datetime] = None,
        error: Optional[str] = None) -> Row:
    """Daily base-backup and monthly restore-drill evidence."""
    stamps = [stamp for stamp in (base_at, restore_at, runtime_at) if stamp]
    as_of = max(stamps) if stamps else None
    if error:
        return Row("backup_restore", "Backup / Restore", "UNKNOWN", UNKNOWN,
                   error, as_of, required_current=True)
    missing = []
    if base_at is None:
        missing.append("base backup")
    if restore_at is None:
        missing.append("restore drill")
    if runtime_at is None:
        missing.append("runtime restore chain")
    if missing:
        return Row(
            "backup_restore", "Backup / Restore", "MISSING EVIDENCE", FAIL,
            "missing " + " and ".join(missing), as_of, required_current=True)
    assert base_at is not None and restore_at is not None and runtime_at is not None
    base_age = now - base_at
    restore_age = now - restore_at
    lag_failures = []
    hard_failures = []
    if base_age > timedelta(hours=26):
        lag_failures.append("base backup exceeds 26h objective")
    if restore_age > timedelta(days=31):
        hard_failures.append("restore drill exceeds 31d objective")
    if runtime_valid_until is None or now > runtime_valid_until:
        lag_failures.append("runtime restore-chain proof is past its cadence")
    base_proof = dict(base_proof or {})
    restore_proof = dict(restore_proof or {})
    runtime_proof = dict(runtime_proof or {})
    base_name_value = str(base_proof.get("base_backup") or "")
    system_id = str(base_proof.get("system_identifier") or "")
    if not all(base_proof.get(key) for key in (
            "base_backup", "marker", "marker_lsn", "marker_wal",
            "system_identifier")):
        hard_failures.append("complete base/WAL proof is malformed")
    try:
        wal_segments = int(runtime_proof.get("wal_segments") or 0)
    except (TypeError, ValueError):
        wal_segments = 0
    if (runtime_proof.get("enabled") is not True
            or runtime_proof.get("wal_integrity") != "sha256-sidecar-v1"
            or not runtime_proof.get("recoverable_from_wal")
            or not runtime_proof.get("recoverable_through_wal")
            or wal_segments < 1):
        hard_failures.append("runtime restore-chain authority is invalid")
    if (str(runtime_proof.get("base_backup") or "") != base_name_value
            or str(runtime_proof.get("system_identifier") or "") != system_id):
        hard_failures.append("runtime chain disagrees with base backup")
    # A monthly semantic drill normally names an older daily base generation.
    # It remains valid through its 31-day objective as long as it proves the
    # same database system identity; requiring it to name today's base would
    # make every successful daily backup falsely turn the panel red.
    if (restore_proof.get("physical_only") is not False
            or not restore_proof.get("base_backup")
            or str(restore_proof.get("system_identifier") or "") != system_id
            or not restore_proof.get("marker")
            or not restore_proof.get("target_lsn")):
        hard_failures.append("full semantic restore proof is invalid")
    base_name = base_name_value or "invalid"
    value = (
        f"BASE {base_age.total_seconds() / 3600:.1f}h · "
        f"RESTORE {restore_age.total_seconds() / 86400:.1f}d")
    runtime = (
        f" · runtime chain {runtime_at.isoformat()}" if runtime_at else
        " · no later runtime-chain proof")
    detail = f"{base_name}{runtime}"
    failures = [*hard_failures, *lag_failures]
    if failures:
        detail += " · " + " · ".join(failures)
    recoverable = bool(lag_failures and not hard_failures and recovery is not None)
    return Row(
        "backup_restore", "Backup / Restore", value,
        WARN if recoverable else (FAIL if failures else OK), detail, as_of,
        required_current=True, recovery=(recovery if recoverable else None))


def runtime_identity_row(
        *, runtime_git: Optional[str], runtime_image: Optional[str],
        reviewed_git: Optional[str], reviewed_image: Optional[str],
        certificate_sha256: Optional[str], lifecycle_current: Optional[bool],
        authority_verdict: Optional[str], checked_at: Optional[datetime],
        valid_until: Optional[datetime] = None,
        error: Optional[str] = None) -> Row:
    """Compare runtime observations with signed reviewed artifact claims."""
    if error:
        return Row("runtime_identity", "Runtime Identity", "UNKNOWN", UNKNOWN,
                   error, checked_at, required_current=True)
    missing = [name for name, value in (
        ("runtime Git", runtime_git), ("runtime image", runtime_image),
        ("reviewed Git", reviewed_git), ("reviewed image", reviewed_image),
        ("certificate", certificate_sha256), ("authority verdict", authority_verdict),
        ("checked at", checked_at),
    ) if not value]
    if missing:
        return Row(
            "runtime_identity", "Runtime Identity", "INCOMPLETE", FAIL,
            "missing " + ", ".join(missing), checked_at,
            required_current=True)
    matches = (
        lifecycle_current is True
        and str(authority_verdict).upper() == "PASS"
        and runtime_git == reviewed_git
        and runtime_image == reviewed_image)
    value = (
        f"GIT {str(runtime_git)[:12]} · IMAGE {str(runtime_image)[:19]}")
    detail = (
        f"reviewed Git {reviewed_git} · reviewed image {reviewed_image} · "
        f"certificate {str(certificate_sha256)[:12]} · "
        f"lifecycle {'current' if lifecycle_current else 'invalid'} · "
        f"authority {str(authority_verdict).upper()}")
    return Row(
        "runtime_identity", "Runtime Identity", value,
        OK if matches else FAIL, detail, checked_at,
        freshness=timedelta(minutes=5), required_current=True,
        valid_until=valid_until)


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
        reviewed_git_commit: Optional[str] = None,
        reviewed_image_digest: Optional[str] = None,
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
              f"{lifecycle}; reviewed Git "
              f"{reviewed_git_commit or 'missing'} · reviewed image "
              f"{reviewed_image_digest or 'missing'}")
    digest = f" · {certificate_sha256[:12]}" if certificate_sha256 else ""
    return Row("authority", "Paper execution authority",
               f"{verdict}{digest}", status, detail, checked_at,
               freshness=timedelta(minutes=5), required_current=True)


__all__ = ["FAIL", "FINANCIAL_AUTHORITY_ROW_KEYS",
           "OPERATIONAL_INFORMATIONAL_ROW_KEYS", "NO_PERFORMANCE_HERE",
           "OK", "PENDING", "Panel", "Row", "SHADOW_ROW_KEYS",
           "TRIAL_ROW_KEYS", "UNKNOWN", "WARN", "automation_alerts_row",
           "alert_dispatcher_row",
           "automation_cycle_row", "automation_leader_row", "automation_row",
           "automation_step_rows",
           "alpaca_account_row", "backup_restore_row", "book_row", "broker_row",
           "execution_authority_row", "exposure_row", "feed_row", "ingest_row",
           "ownership_row", "paper_reconciliation_row", "runtime_identity_row",
           "shadow_metric_row", "shadow_verification_row", "terminals_row"]
