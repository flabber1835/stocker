"""Where the panel's numbers come from. The ONLY module here that does IO.

EVERY READ IS INDIVIDUALLY GUARDED. A panel whose job is to reveal that
something is broken must not go blank when something is broken — if the feed
database is unreachable, the ownership row is still the fact the operator most
needs, and a 500 page would hide it. So each source is wrapped, a failure
becomes an UNKNOWN row plus a `source_errors` entry, and the page still renders.

READ-ONLY, and structurally so: this module opens connections, runs SELECTs and
reads a log file. It imports nothing that can submit an order, and the broker
adapter is deliberately not touched here — a page load must never produce
broker traffic, because a phone left on a desk refreshing every 30 seconds
would be an unattended API client.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from sentinel.panel import model

#: Wealth Core's slot count. Read from the engine config rather than hardcoded
#: the day a live book exists; until then it is only a denominator on a PENDING
#: row and is not worth an import cycle.
DEFAULT_SLOTS = 25

#: Seconds the panel will wait to OPEN a connection, and seconds any single
#: statement may run. Both are hard, and both exist because of the same
#: incident: the first version of this module issued unbounded queries, and the
#: page hung forever the first time it was opened — the readiness check runs
#: scans over `sentinel_bars` and the table was mid-bulk-load from a seed.
#:
#: A panel that HANGS is worse than one that reports UNKNOWN. Hanging is
#: indistinguishable from a dead server, gives an operator nothing to act on,
#: and does it precisely when the system is busiest — which is exactly when
#: someone opens the panel. Every source here must answer or be cut off.
CONNECT_TIMEOUT_SECONDS = 4
#: 8s, not 3s. The frontier is `MAX(session)` over an INDEXED column, so it is a
#: backwards index scan and ought to be instant — but on a NAS saturated by a
#: bulk COPY it still missed a 3s budget, because the pages it reads are the
#: ones being written. The panel is not latency-critical; the CONNECT timeout is
#: what bounds a genuine hang, and this only bounds a slow answer.
STATEMENT_TIMEOUT_MS = 8_000

#: The readiness contract is the EXPENSIVE read and the least urgent one: it
#: scans the corpus, and during an ingest it can legitimately take minutes. It
#: gets its own, tighter budget so a slow contract check costs the panel its
#: verdict but never its frontier, its ingest row or its ownership row.
READINESS_TIMEOUT_MS = 2_000


def _utc(dt) -> Optional[datetime]:
    """Normalise whatever the driver hands back. A naive timestamp compared
    against an aware `now` raises, and a panel that 500s because a database
    column had no timezone is a panel that fails exactly when it is needed."""
    if dt is None:
        return None
    if isinstance(dt, str):
        try:
            dt = datetime.fromisoformat(dt.replace("Z", "+00:00"))
        except ValueError:
            return None
    if not isinstance(dt, datetime):
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


def _bounded_dsn(dsn: str) -> str:
    """Append libpq's `connect_timeout` so opening the connection cannot hang.

    A statement timeout does nothing if the CONNECT never completes — a busy or
    unreachable Postgres leaves the socket waiting indefinitely by default, and
    the page hangs before it has run a single query.
    """
    if "connect_timeout" in dsn:
        return dsn
    sep = "&" if "?" in dsn else "?"
    return f"{dsn}{sep}connect_timeout={CONNECT_TIMEOUT_SECONDS}"


def _set_statement_timeout(conn, ms: int) -> None:
    """Server-side cutoff. A client-side one would leave the query RUNNING on a
    database that is already busy, which is the opposite of helping."""
    with conn.cursor() as cur:
        cur.execute(f"SET statement_timeout = {int(ms)}")


def _read(conn, fn, timeout_ms: int, *, default=None):
    """Run ONE read under its own timeout, and leave the connection USABLE.

    Returns `(value, error)` — `error` is None on success. The rollback is
    load-bearing rather than tidy: a timed-out statement leaves the transaction
    aborted, so without it the NEXT read fails with InFailedSqlTransaction and
    one slow query cascades into "the whole feed is unreadable". That cascade is
    exactly what this function exists to stop.
    """
    try:
        _set_statement_timeout(conn, timeout_ms)
        return fn(conn), None
    except Exception as exc:                         # noqa: BLE001
        try:
            conn.rollback()
        except Exception:                            # noqa: BLE001
            pass
        return default, _short(exc)


def _short(exc: Exception) -> str:
    """A timeout should read as a timeout, not as a driver traceback. An
    operator seeing this at 23:00 needs to know it was slow, not which
    exception class libpq chose."""
    name = type(exc).__name__
    if "timeout" in str(exc).lower() or "Cancel" in name:
        return "timed out"
    return f"{name}: {str(exc).strip().splitlines()[0][:120]}"


def _ownership(state_dir: Path, database_url: str = "") -> model.Row:
    """The BINDING, not the file.

    The panel used to read `ownership.jsonl` and report whatever it found. That
    was correct while the file was authoritative and became a second, competing
    reality the moment the binding moved into PostgreSQL — a panel showing NOT
    ESTABLISHED beside a runtime that is correctly trading is worse than a panel
    showing nothing, because it invites someone to act.

    An unreadable binding renders as UNKNOWN rather than as a reassuring "not
    established": the operator needs to see that the question could not be
    answered.
    """
    try:
        from sentinel import ownership_view
        from sentinel.feed import store as feed_store
        # BOUNDED, like every other read this page makes. See _bounded_dsn.
        view = ownership_view.read(
            database_url, state_dir,
            connect=lambda dsn: feed_store.connect(_bounded_dsn(dsn)))
        return model.ownership_row(state=view.state.value, at=None,
                                   error=None if view.state.value != "UNKNOWN"
                                   else view.detail)
    except Exception as exc:                        # noqa: BLE001 — see module doc
        return model.ownership_row(state=None, at=None, error=repr(exc))


def _feed_rows(database_url: str) -> tuple[list[model.Row], list[str]]:
    """The feed frontier, the contract verdict and the latest ingest.

    One connection for all three: three page-load connections to serve one
    screen is how a dashboard becomes the reason a database is busy.
    """
    if not database_url:
        return ([model.feed_row(frontier=None, sessions_behind=None, ready=None,
                                checks_passed=0, checks_total=0, as_of=None,
                                error="SENTINEL_DATABASE_URL is unset"),
                 model.ingest_row(kind=None, status=None, chunks_done=0,
                                  chunks_total=0, rows_written=0,
                                  current_chunk=None, updated_at=None)],
                ["SENTINEL_DATABASE_URL is unset"])
    conn = None
    try:
        from sentinel.feed import readiness
        from sentinel.feed import store as feed_store
        conn = feed_store.connect(_bounded_dsn(database_url))

        # EACH READ SEPARATELY, and this granularity is the whole point.
        # Grouping them meant one slow query cost the page every other row: the
        # frontier is `MAX(session)` over `sentinel_bars`, which times out while
        # that table is being bulk-loaded, and it took the INGEST row down with
        # it — the one row that matters during an ingest, and the only one that
        # can say whether the seed is alive.
        #
        # The order below is deliberately cheapest-first, so the most useful row
        # is already secured before anything expensive is attempted.
        runs, run_err = _read(conn, lambda c: feed_store.run_status(c, limit=1),
                              STATEMENT_TIMEOUT_MS, default=[])
        # THE VISIBLE frontier, deliberately — the newest session a DECISION may
        # read, not the newest row physically present. The panel exists to
        # answer "is the data current?", and reporting a date the engine refuses
        # to load would make an ingest that committed rows and then failed to
        # publish them look like a healthy fetch. Showing the published frontier
        # makes the same failure read as "we are a day behind", which is true.
        frontier, front_err = _read(conn, feed_store.latest_visible_session,
                                    STATEMENT_TIMEOUT_MS, default=None)

        # The contract check is the expensive read and the least urgent, so it
        # gets the TIGHTEST budget and is the first thing given up. During a
        # seed it legitimately takes minutes.
        r, _ = _read(conn, readiness.check_readiness, READINESS_TIMEOUT_MS,
                     default=None)
        if r is None:
            ready, passed, total = None, 0, 0
        else:
            ready, passed, total = (r.ready, sum(1 for c in r.checks if c.ok),
                                    len(r.checks))

        # SESSIONS, which is what the field has always been called.
        #
        # It was computed as `(utcnow().date() - frontier).days`, and both halves
        # were wrong. Calendar days are not sessions: on a Monday evening with
        # Friday's data — the healthy state — it read 3, while a Friday with a
        # Tuesday frontier and two missing sessions also read 3. And the clock
        # was UTC for an exchange question, so after 20:00 ET it added another
        # day, during exactly the hours the daily ingest runs.
        #
        # No DB, no timeout budget: the calendar is a pinned local library.
        behind = None
        if frontier:
            from sentinel.feed import calendar as _cal
            try:
                behind = _cal.freshness(str(frontier)).sessions_behind
            except Exception:                            # noqa: BLE001
                # No calendar ⇒ UNKNOWN, rendered as blank. Never 0: the panel
                # must not report a corpus current on the strength of a check
                # that could not run.
                behind = None

        run = runs[0] if runs else {}
        rows = [
            # A frontier that TIMED OUT is not an unreadable database — the
            # connection is open and the ingest row right below was just read
            # over it. Reporting it as unreadable would blame the whole feed for
            # one slow scan, which is what the grouped guard used to do.
            model.feed_row(frontier=str(frontier) if frontier else None,
                           sessions_behind=behind, ready=ready,
                           checks_passed=passed, checks_total=total,
                           as_of=_utc(run.get("updated_at")),
                           error=(f"frontier {front_err}" if front_err else None),
                           ingest_running=(run.get("status") == "running")),
            model.ingest_row(kind=run.get("kind"), status=run.get("status"),
                             chunks_done=int(run.get("chunks_done") or 0),
                             chunks_total=int(run.get("chunks_total") or 0),
                             rows_written=int(run.get("rows_written") or 0),
                             current_chunk=run.get("current_chunk"),
                             updated_at=_utc(run.get("updated_at")),
                             error_message=run.get("error_message")),
        ]
        # `source_errors` is the banner across the top of the page and it means
        # "the panel could not read the world". A single slow query does not
        # qualify — the rows below say so themselves, in the right place. Only a
        # read that failed for a reason OTHER than time gets escalated, and a
        # dead connection is caught by the outer handler.
        errs = [f"feed database: {e}" for e in (run_err,)
                if e and e != "timed out"]
        return rows, errs
    except Exception as exc:                         # noqa: BLE001
        msg = repr(exc)
        return ([model.feed_row(frontier=None, sessions_behind=None, ready=None,
                                checks_passed=0, checks_total=0, as_of=None,
                                error=msg),
                 model.ingest_row(kind=None, status=None, chunks_done=0,
                                  chunks_total=0, rows_written=0,
                                  current_chunk=None, updated_at=None)],
                [f"feed database: {msg}"])
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:                        # noqa: BLE001
                pass


def build_panel(*, state_dir: Path, database_url: str,
                now: Optional[datetime] = None) -> model.Panel:
    """Assemble the whole page.

    The BOOK, TERMINALS and BROKER rows are PENDING by construction today: no
    live Wealth Core state is persisted until the execution projection lands
    (deployment item E), and there is nothing to read. They are shown rather
    than omitted so the panel's shape is the finished shape — an operator who
    learns the layout tonight does not re-learn it when E ships, and a row that
    appears later is a row nobody was watching for.
    """
    now = now or datetime.now(timezone.utc)
    errors: list[str] = []

    own = _ownership(Path(state_dir), database_url)
    if own.status is model.UNKNOWN:
        errors.append("ownership log")
    feed_rows, feed_errs = _feed_rows(database_url)
    errors.extend(feed_errs)

    rows = [
        own,
        model.exposure_row(exposure=1.0, controller_active=False),
        *feed_rows,
        model.book_row(available=False),
        model.terminals_row(counters=None),
        model.broker_row(available=False),
    ]
    return model.Panel(rows=rows, now=now, source_errors=errors)


__all__ = ["DEFAULT_SLOTS", "build_panel"]
