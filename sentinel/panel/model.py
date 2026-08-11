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
    no performance number appears at all — see `NO_PERFORMANCE_HERE`
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional

#: Deliberately absent from this panel: CAGR, total return, P&L, any equity
#: curve. The certification rule is that no Wealth Core performance number may
#: be reported without the settlement counters and the per-episode terminal
#: audit beside it — and a dashboard is precisely where a bare number gets
#: screenshotted and quoted without them. The panel reports CONDITION, and the
#: settlement counters ARE the honest headline.
NO_PERFORMANCE_HERE = True

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

    def effective_status(self, now: datetime) -> str:
        """A stale OK is a WARN. Staleness cannot IMPROVE a status — a row that
        is already failing does not become merely stale."""
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

    def row(self, key: str) -> Optional[Row]:
        return next((r for r in self.rows if r.key == key), None)


# ── the rows ─────────────────────────────────────────────────────────────────

def ownership_row(*, state: Optional[str], at: Optional[datetime],
                  error: Optional[str] = None) -> Row:
    """The single most safety-critical fact Sentinel owns.

    If the ownership log is lost, the next start classifies a Sentinel-owned
    book as a legacy Stocker book and liquidates it. It must be impossible to
    look at this panel and not know which side of that boundary you are on, so
    it is row one and it is never abbreviated.

    Timeless by design (`freshness=None`): an established handover does not go
    stale. It is true until something supersedes it.
    """
    if error:
        return Row("ownership", "Ownership", "UNREADABLE", UNKNOWN,
                   f"the log could not be read — {error}", at)
    if state in ("SENTINEL_OWNERSHIP_ESTABLISHED",
                 "WEALTH_CORE_BOOTSTRAP_ALLOWED"):
        return Row("ownership", "Ownership", "FLAT CONFIRMED", OK,
                   "Sentinel owns this account", at)
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


def exposure_row(*, exposure: float, controller_active: bool) -> Row:
    """`1.00 PINNED` and `1.00 computed` are different facts and the panel must
    never let them look alike.

    Until items F-H land, the actuator is pinned and nothing varies exposure —
    §6 of the deployment doc stages it that way on purpose. When the controller
    is switched on, this row is where an operator learns that the number is now
    a DECISION. Spelling out PINNED means the change is visible rather than
    inferred from a value that did not move.
    """
    if controller_active:
        return Row("exposure", "Exposure", f"{exposure:.2f}", OK,
                   "controller active", None)
    return Row("exposure", "Exposure", f"{exposure:.2f} PINNED", PENDING,
               "controller not active — exposure does not vary", None)


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


def book_row(*, available: bool, slots_used: Optional[int] = None,
             slots_total: Optional[int] = None, nav: Optional[float] = None,
             cash: Optional[float] = None, blocked: Optional[int] = None,
             unresolved_terminals: Optional[int] = None,
             pending_actions: Optional[int] = None,
             as_of: Optional[datetime] = None) -> Row:
    """The book, with `blocked` and `unresolved` on the SAME LINE as the NAV.

    Not a layout preference. An unresolved terminal freezes admissions while
    every other number looks fine, and `resolved_equity` goes None while a
    plausible total is still printable. Putting the caveats beside the NAV means
    you cannot read the NAV without reading whether it can be trusted.

    `available=False` until item E persists a live book. Rendered PENDING, not
    FAIL: "the execution path is not built" is a project state, and colouring it
    like an outage teaches an operator to ignore red.
    """
    if not available:
        return Row("book", "Book", "NOT YET LIVE", PENDING,
                   "no persisted book — awaiting the execution projection "
                   "(deployment item E)", as_of)
    flags = []
    if blocked:
        flags.append(f"BLOCKED {blocked}")
    if unresolved_terminals:
        flags.append(f"UNRESOLVED TERMINALS {unresolved_terminals}")
    status = FAIL if flags else OK
    detail = " · ".join(flags) if flags else (
        f"cash ${cash:,.0f} · {pending_actions or 0} pending")
    return Row("book", "Book",
               f"{slots_used}/{slots_total} slots · NAV ${nav:,.0f}",
               status, detail, as_of, freshness=timedelta(days=4))


def terminals_row(*, counters: Optional[dict],
                  as_of: Optional[datetime] = None) -> Row:
    """The settlement counters, which are the honest headline.

    A book that BLOCKS its terminations completes and reports a plausible
    return, so these are the only place that failure is visible. The specific
    reading worth surfacing: `derived_last_mark_settlements == 0` alongside a
    nonzero `unresolved_terminal_events` means the book is blocking rather than
    settling, and every number downstream of it is unevaluable.
    """
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


def broker_row(*, available: bool, positions: Optional[int] = None,
               agrees: Optional[bool] = None,
               as_of: Optional[datetime] = None) -> Row:
    """Broker state, shown for RECONCILIATION only.

    The dependency direction is `shadow -> Sentinel -> broker`, never the
    reverse, so this row must never read as an input to anything. It answers one
    question — does the paper account match what the shadow believes — and the
    shadow is authoritative when they disagree.
    """
    if not available:
        return Row("broker", "Broker", "NOT SYNCED", PENDING,
                   "no broker read yet", as_of)
    if agrees is False:
        return Row("broker", "Broker", f"{positions} positions", FAIL,
                   "DISAGREES with the shadow — the shadow is authoritative",
                   as_of, freshness=timedelta(days=4))
    return Row("broker", "Broker", f"{positions} positions", OK,
               "agrees with the shadow", as_of, freshness=timedelta(days=4))


__all__ = ["FAIL", "NO_PERFORMANCE_HERE", "OK", "PENDING", "Panel", "Row",
           "UNKNOWN", "WARN", "book_row", "broker_row", "exposure_row",
           "feed_row", "ingest_row", "ownership_row", "terminals_row"]
