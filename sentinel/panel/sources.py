"""Where the panel's numbers come from. The ONLY module here that does IO.

EVERY READ IS INDIVIDUALLY GUARDED. A panel whose job is to reveal that
something is broken must not go blank when something is broken — if the feed
database is unreachable, the ownership row is still the fact the operator most
needs, and a 500 page would hide it. So each source is wrapped, a failure
becomes an UNKNOWN row plus a `source_errors` entry, and the page still renders.

READ-ONLY, and structurally so: this module opens connections and runs SELECTs
against canonical durable records. It imports nothing that can submit an
order, and the broker adapter is deliberately not touched here — a page load
must never produce broker traffic, because a phone left on a desk refreshing
every 30 seconds
would be an unattended API client.
"""
from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
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

# The panel probes these exact columns before issuing a runtime SELECT. This is
# not a migration mechanism: old/partial schemas remain old/partial and render
# UNKNOWN. The probe prevents a missing relation in one row from cascading into
# every other row on the shared connection.
_RUNTIME_COLUMNS = {
    "sentinel_processed_sessions": {
        "cursor_name", "session", "state", "updated_at"},
    "sentinel_execution_plans": {
        "plan_id", "decision_session", "effective_session",
        "target_exposure", "unpriced_securities", "superseded_by",
        "rollout_mode", "rollout_version", "rollout_certificate_sha256",
        "created_at"},
    "sentinel_rollout_state": {
        "id", "mode", "version", "certificate_sha256", "updated_at"},
    "sentinel_observations": {
        "seq", "observed_at", "completeness", "positions", "orders",
        "runtime_state"},
    "sentinel_commands": {
        "state", "updated_at"},
}
_ACTIVE_COMMAND_STATES = (
    "PLANNED", "SEND_PENDING", "ACKNOWLEDGED", "UNKNOWN",
    "PARTIALLY_FILLED", "CANCEL_PENDING",
)
_UNCERTAIN_COMMAND_STATES = frozenset({
    "SEND_PENDING", "UNKNOWN", "CANCEL_PENDING"})
_WORKING_ORDER_STATES = frozenset({
    "SEND_PENDING", "ACKNOWLEDGED", "UNKNOWN", "PARTIALLY_FILLED",
    "CANCEL_PENDING"})


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


def _json_mapping(value, *, label: str) -> dict:
    if isinstance(value, str):
        value = json.loads(value)
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} is not a JSON object")
    return dict(value)


def _json_list(value, *, label: str) -> list:
    if isinstance(value, str):
        value = json.loads(value)
    if not isinstance(value, list):
        raise ValueError(f"{label} is not a JSON array")
    return list(value)


def _finite_float(value, *, label: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{label} is not numeric")
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"{label} is not numeric") from exc
    if not number.is_finite():
        raise ValueError(f"{label} is not finite")
    return float(number)


def _runtime_schema(conn) -> dict[str, set[str]]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT table_name, column_name FROM information_schema.columns"
            " WHERE table_schema = ANY(current_schemas(false))"
            " AND table_name = ANY(%s)",
            (list(_RUNTIME_COLUMNS),))
        rows = cur.fetchall()
    found = {table: set() for table in _RUNTIME_COLUMNS}
    for table, column in rows:
        if str(table) in found:
            found[str(table)].add(str(column))
    return found


def _schema_error(found: Mapping[str, set[str]], table: str) -> str | None:
    missing = _RUNTIME_COLUMNS[table] - set(found.get(table) or ())
    if not missing:
        return None
    return f"missing schema {table}({', '.join(sorted(missing))})"


def _canonical_state(conn):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT session, state, updated_at"
            " FROM sentinel_processed_sessions"
            " WHERE cursor_name = %s",
            ("catchup",))
        rows = cur.fetchall()
    if len(rows) > 1:
        raise ValueError("canonical cursor is not unique")
    if not rows:
        return None
    session, raw, updated_at = rows[0]
    return {
        "session": str(session),
        "state": _json_mapping(raw, label="canonical SessionState"),
        "updated_at": _utc(updated_at),
    }


def _current_plan(conn):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT plan_id, decision_session, effective_session,"
            " target_exposure, unpriced_securities, rollout_mode,"
            " rollout_version, rollout_certificate_sha256, created_at"
            " FROM sentinel_execution_plans"
            " WHERE superseded_by IS NULL"
            " ORDER BY created_at DESC, plan_id DESC LIMIT 2")
        rows = cur.fetchall()
    if len(rows) > 1:
        raise ValueError("more than one execution plan is current")
    if not rows:
        return None
    row = rows[0]
    return {
        "plan_id": str(row[0]),
        "decision_session": str(row[1]),
        "effective_session": str(row[2]),
        "target_exposure": row[3],
        "unpriced_securities": _json_list(
            row[4], label="current plan unpriced_securities"),
        "rollout_mode": str(row[5] or ""),
        "rollout_version": int(row[6]),
        "rollout_certificate_sha256": (
            str(row[7]) if row[7] is not None else None),
        "created_at": _utc(row[8]),
    }


def _rollout_state(conn):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT mode, version, certificate_sha256, updated_at"
            " FROM sentinel_rollout_state WHERE id = 1")
        rows = cur.fetchall()
    if len(rows) > 1:
        raise ValueError("rollout authority is not unique")
    if not rows:
        raise ValueError("rollout authority is absent")
    mode = str(rows[0][0] or "")
    version = int(rows[0][1])
    certificate = str(rows[0][2]) if rows[0][2] is not None else None
    if mode not in {"PINNED_1_00", "CONTROLLER"}:
        raise ValueError(f"unknown rollout mode {mode!r}")
    if version < 1:
        raise ValueError("rollout version is not positive")
    if ((mode == "PINNED_1_00" and certificate is not None)
            or (mode == "CONTROLLER" and not certificate)):
        raise ValueError("rollout certificate does not match its mode")
    return {
        "mode": mode, "version": version, "certificate_sha256": certificate,
        "updated_at": _utc(rows[0][3]),
    }


def _latest_observation(conn):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT observed_at, completeness, positions, orders, runtime_state"
            " FROM sentinel_observations ORDER BY seq DESC LIMIT 1")
        rows = cur.fetchall()
    if not rows:
        return None
    row = rows[0]
    return {
        "observed_at": _utc(row[0]),
        "completeness": str(row[1] or ""),
        "positions": _json_mapping(row[2], label="broker observation positions"),
        "orders": _json_list(row[3], label="broker observation orders"),
        "runtime_state": str(row[4] or ""),
    }


def _active_commands(conn):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT state, COUNT(*), MAX(updated_at)"
            " FROM sentinel_commands WHERE state = ANY(%s) GROUP BY state",
            (list(_ACTIVE_COMMAND_STATES),))
        rows = cur.fetchall()
    counts: dict[str, int] = {}
    updated_at = None
    for state, count, updated in rows:
        counts[str(state)] = int(count)
        stamp = _utc(updated)
        if stamp is not None and (updated_at is None or stamp > updated_at):
            updated_at = stamp
    return {"counts": counts, "updated_at": updated_at}


def _state_view(snapshot) -> dict:
    state = snapshot["state"]
    session = snapshot["session"]
    if int(state.get("version", 0)) != 3:
        raise ValueError("persisted production state is not canonical version 3")
    if str(state.get("last_processed_session") or "") != session:
        raise ValueError("canonical state and processed-session cursor disagree")
    wealth = _json_mapping(state.get("wealth_core"), label="Wealth Core state")
    slots = _json_mapping(wealth.get("slots"), label="Wealth Core slots")
    episodes = _json_mapping(
        wealth.get("episodes"), label="Wealth Core episodes")
    unresolved = _json_mapping(
        wealth.get("unresolved_terminals") or {},
        label="unresolved terminal state")
    carried = _json_mapping(
        wealth.get("terminal_pending_terms") or {},
        label="carried terminal state")
    pending = _json_list(state.get("pending"), label="pending operations")
    evidence = _json_mapping(
        state.get("last_evidence"), label="last session evidence")
    wealth_evidence = _json_mapping(
        evidence.get("wealth_core"), label="Wealth Core session evidence")
    blocked = wealth_evidence.get("blocked")
    if not isinstance(blocked, bool):
        raise ValueError("Wealth Core blocked evidence is not boolean")
    nav = _finite_float(
        wealth_evidence.get("estimated_equity"), label="shadow estimated NAV")
    cash = _finite_float(wealth.get("cash"), label="shadow cash")
    if nav < 0 or cash < 0:
        raise ValueError("shadow NAV/cash cannot be negative")
    if len(episodes) > len(slots):
        raise ValueError("Wealth Core episodes exceed its slot count")
    decision = state.get("last_decision")
    if decision is not None:
        decision = _json_mapping(decision, label="controller decision")
    return {
        "session": session,
        "updated_at": snapshot["updated_at"],
        "slots_used": len(episodes),
        "slots_total": len(slots),
        "nav": nav,
        "cash": cash,
        "blocked": blocked,
        "unresolved": len(unresolved),
        "carried": len(carried),
        "pending": len(pending),
        "decision": decision,
    }


def _exposure_row(state_view, plan, rollout, *, state_error: str | None,
                  plan_error: str | None,
                  rollout_error: str | None) -> model.Row:
    if state_error or plan_error or rollout_error:
        detail = "; ".join(
            v for v in (state_error, plan_error, rollout_error) if v)
        return model.exposure_row(
            exposure=None, controller_active=None, error=detail)
    if state_view is None:
        return model.exposure_row(
            exposure=None, controller_active=None,
            error="no canonical SessionState has been persisted")
    decision = state_view.get("decision")
    if not decision:
        raise ValueError("canonical state has no controller decision")
    decision_session = str(decision.get("session") or "")
    if decision_session != state_view["session"]:
        raise ValueError("controller decision and canonical cursor disagree")
    exposure = _finite_float(
        decision.get("target_core_exposure"), label="controller exposure")
    if not 0 <= exposure <= 1:
        raise ValueError("controller exposure is outside [0, 1]")
    if rollout is None:
        raise ValueError("durable rollout authority is absent")
    if plan is None:
        return model.exposure_row(
            exposure=(1.0 if rollout["mode"] == "PINNED_1_00" else exposure),
            controller_active=(rollout["mode"] == "CONTROLLER"), adopted=False,
            session=decision_session, as_of=state_view["updated_at"])
    plan_exposure = _finite_float(
        plan["target_exposure"], label="current plan exposure")
    if plan["decision_session"] != decision_session:
        raise ValueError(
            "current plan and canonical controller decision disagree")
    plan_rollout = (
        plan["rollout_mode"], plan["rollout_version"],
        plan["rollout_certificate_sha256"])
    current_rollout = (
        rollout["mode"], rollout["version"], rollout["certificate_sha256"])
    if plan_rollout != current_rollout:
        raise ValueError("current plan and rollout authority disagree")
    if rollout["mode"] == "PINNED_1_00":
        if Decimal(str(plan_exposure)) != Decimal(1):
            raise ValueError("pinned rollout plan exposure is not exactly 1")
        return model.exposure_row(
            exposure=plan_exposure, controller_active=False, adopted=True,
            session=decision_session, as_of=plan["created_at"])
    if Decimal(str(plan_exposure)) != Decimal(str(exposure)):
        raise ValueError(
            "controller rollout plan and canonical decision disagree")
    return model.exposure_row(
        exposure=plan_exposure, controller_active=True, adopted=True,
        session=decision_session, as_of=plan["created_at"])


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

        # A VERDICT SOMEBODY ELSE COMPUTED, read by primary key.
        #
        # This used to call `check_readiness` here, inside the page load, under
        # the tightest of the three budgets — with a comment explaining that it
        # is the expensive read and during a seed it legitimately takes minutes.
        # Both true, and together they blanked the page on exactly the question
        # it exists to answer: an operator watching a six-hour seed could not
        # tell a corpus still building from one that had failed a clause.
        #
        # No budget fixes that. The check reads the corpus, the corpus is what
        # is under load, and anything short enough to protect a page load is
        # short enough to lose under contention. `check-data` already computes
        # a full verdict; this reads the last one and reports its age.
        snap, _ = _read(conn, readiness.latest_snapshot, STATEMENT_TIMEOUT_MS,
                        default=None)
        if snap is None:
            # NEVER False. Nothing has computed a verdict — "we have not asked"
            # is not "the corpus failed a clause", and `model.feed_row` already
            # renders None as its own third state.
            ready, passed, total, checked_at = None, 0, 0, None
        else:
            # `ready` is what was MEASURED; `trustworthy` folds in the age. The
            # panel shows the measurement and labels the staleness, rather than
            # silently downgrading a verdict the operator can date themselves.
            ready = snap.ready
            passed, total = snap.checks_passed, snap.checks_total
            checked_at = snap.computed_at

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
                           # WHEN THE VERDICT WAS COMPUTED, which is not when
                           # the ingest last ran. A day-old PASS shown beside a
                           # fresh ingest timestamp reads as current, and that
                           # is the one way a stale verdict does harm.
                           checked_at=_utc(checked_at),
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


def _runtime_rows(database_url: str) -> tuple[list[model.Row], list[str]]:
    """Canonical state, current plan and durable broker evidence.

    This is a PostgreSQL projection only. In particular, the newest
    `sentinel_observations` row is shown as what the broker said when an explicit
    command last observed it; rendering this page never asks the broker again.
    """
    if not database_url:
        detail = "SENTINEL_DATABASE_URL is unset"
        return ([
            model.exposure_row(
                exposure=None, controller_active=None, error=detail),
            model.book_row(available=None, error=detail),
            model.terminals_row(error=detail),
            model.broker_row(available=None, error=detail),
        ], [detail])

    from sentinel.feed import store as feed_store

    conn = None
    try:
        conn = feed_store.connect(_bounded_dsn(database_url))
        found, schema_read_error = _read(
            conn, _runtime_schema, STATEMENT_TIMEOUT_MS, default={})
        if schema_read_error:
            detail = f"runtime schema: {schema_read_error}"
            return ([
                model.exposure_row(
                    exposure=None, controller_active=None, error=detail),
                model.book_row(available=None, error=detail),
                model.terminals_row(error=detail),
                model.broker_row(available=None, error=detail),
            ], [detail])

        state_error = _schema_error(found, "sentinel_processed_sessions")
        plan_error = _schema_error(found, "sentinel_execution_plans")
        rollout_error = _schema_error(found, "sentinel_rollout_state")
        observation_error = _schema_error(found, "sentinel_observations")
        command_error = _schema_error(found, "sentinel_commands")

        state_snapshot = None
        if state_error is None:
            state_snapshot, state_error = _read(
                conn, _canonical_state, STATEMENT_TIMEOUT_MS, default=None)
        plan = None
        if plan_error is None:
            plan, plan_error = _read(
                conn, _current_plan, STATEMENT_TIMEOUT_MS, default=None)
        rollout = None
        if rollout_error is None:
            rollout, rollout_error = _read(
                conn, _rollout_state, STATEMENT_TIMEOUT_MS, default=None)
        observation = None
        if observation_error is None:
            observation, observation_error = _read(
                conn, _latest_observation, STATEMENT_TIMEOUT_MS, default=None)
        commands = None
        if command_error is None:
            commands, command_error = _read(
                conn, _active_commands, STATEMENT_TIMEOUT_MS, default=None)

        state_view = None
        if state_error is None and state_snapshot is not None:
            try:
                state_view = _state_view(state_snapshot)
            except Exception as exc:                         # noqa: BLE001
                state_error = _short(exc)

        try:
            exposure = _exposure_row(
                state_view, plan, rollout, state_error=state_error,
                plan_error=plan_error, rollout_error=rollout_error)
        except Exception as exc:                             # noqa: BLE001
            plan_error = _short(exc)
            exposure = model.exposure_row(
                exposure=None, controller_active=None, error=plan_error,
                as_of=(plan or {}).get("created_at"))

        if state_error:
            book = model.book_row(available=None, error=state_error)
            terminals = model.terminals_row(error=state_error)
        elif state_view is None:
            book = model.book_row(available=False)
            terminals = model.terminals_row(counters=None)
        else:
            if plan_error or rollout_error:
                book = model.book_row(
                    available=None, error=plan_error or rollout_error)
            else:
                book = model.book_row(
                    available=True,
                    slots_used=state_view["slots_used"],
                    slots_total=state_view["slots_total"],
                    nav=state_view["nav"], cash=state_view["cash"],
                    blocked=state_view["blocked"],
                    unresolved_terminals=state_view["unresolved"],
                    unpriced_securities=(len(plan["unpriced_securities"])
                                         if plan is not None else None),
                    pending_actions=state_view["pending"],
                    as_of=state_view["updated_at"])
            terminals = model.terminals_row(
                current_unresolved=state_view["unresolved"],
                current_pending=state_view["carried"],
                as_of=state_view["updated_at"])

        if observation_error or command_error:
            detail = "; ".join(
                value for value in (observation_error, command_error) if value)
            broker = model.broker_row(available=None, error=detail)
        elif observation is None:
            broker = model.broker_row(available=False)
        else:
            try:
                position_count = 0
                for security_id, quantity in observation["positions"].items():
                    if not str(security_id).strip():
                        raise ValueError(
                            "broker observation has a blank security id")
                    number = Decimal(str(quantity))
                    if not number.is_finite():
                        raise ValueError(
                            "broker observation has a non-finite quantity")
                    if number != 0:
                        position_count += 1
                working_orders = 0
                for raw in observation["orders"]:
                    order = _json_mapping(
                        raw, label="broker observation order")
                    state = str(order.get("state") or "").upper()
                    if not state:
                        raise ValueError(
                            "broker observation order has no state")
                    if state in _WORKING_ORDER_STATES:
                        working_orders += 1
                counts = commands["counts"]
                active = sum(counts.values())
                uncertain = sum(
                    count for state, count in counts.items()
                    if state in _UNCERTAIN_COMMAND_STATES)
                broker = model.broker_row(
                    available=True, positions=position_count,
                    completeness=observation["completeness"],
                    runtime_state=observation["runtime_state"],
                    working_orders=working_orders, active_commands=active,
                    uncertain_commands=uncertain,
                    command_as_of=commands["updated_at"],
                    as_of=observation["observed_at"])
            except Exception as exc:                         # noqa: BLE001
                observation_error = _short(exc)
                broker = model.broker_row(
                    available=None, error=observation_error,
                    as_of=observation.get("observed_at"))

        errors = [
            f"runtime {name}: {error}"
            for name, error in (
                ("state", state_error), ("plan", plan_error),
                ("rollout", rollout_error),
                ("observation", observation_error),
                ("commands", command_error))
            if error
        ]
        return [exposure, book, terminals, broker], errors
    except Exception as exc:                                 # noqa: BLE001
        detail = _short(exc)
        return ([
            model.exposure_row(
                exposure=None, controller_active=None, error=detail),
            model.book_row(available=None, error=detail),
            model.terminals_row(error=detail),
            model.broker_row(available=None, error=detail),
        ], [f"runtime database: {detail}"])
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:                                # noqa: BLE001
                pass


def build_panel(*, state_dir: Path, database_url: str,
                now: Optional[datetime] = None) -> model.Panel:
    """Assemble the whole page.

    Runtime rows project only durable PostgreSQL facts. Their absence is named;
    a malformed or unreadable fact becomes UNKNOWN rather than falling back to
    the deployment-stage placeholders this panel used before item E landed.
    """
    now = now or datetime.now(timezone.utc)
    errors: list[str] = []

    own = _ownership(Path(state_dir), database_url)
    if own.status is model.UNKNOWN:
        errors.append("ownership binding")
    feed_rows, feed_errs = _feed_rows(database_url)
    errors.extend(feed_errs)
    runtime_rows, runtime_errs = _runtime_rows(database_url)
    errors.extend(runtime_errs)

    rows = [
        own,
        model.execution_authority_row(),
        runtime_rows[0],
        *feed_rows,
        *runtime_rows[1:],
        model.automation_row(),
    ]
    return model.Panel(rows=rows, now=now, source_errors=errors)


__all__ = ["DEFAULT_SLOTS", "build_panel"]
