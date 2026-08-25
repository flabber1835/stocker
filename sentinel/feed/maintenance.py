"""Current-source reconciliation beyond the moving market-session window.

Two clocks are independent:

``SESSION FRONTIER`` discovers new market dates.
``MUTATION WATERMARK`` discovers old SEP rows Sharadar changed later.

SEP exposes the latter as date-valued ``lastupdated``.  The durable cursor
re-reads the complete preceding update date and advances only after the
corresponding local corpus generation is published.  Historical changes are not
patched into one bar: they are replayed through the ordinary normalizer over a
bounded prior/effective/following-session window so split orientation,
dividends, rejections and anomaly evidence remain coherent.

ACTIONS has no documented mutation timestamp.  Ordinary daily pagination is
useful for additions but cannot prove negative space: two identical partial
traversals are stable, not necessarily complete.  Production complete
reconciliation therefore uses Nasdaq Data Link's whole-table Exporter snapshot,
whose ``fresh`` state carries a vendor ``data_snapshot_time`` and table
``last_refreshed_time``.  The reconciliation cursor is earned every decision day
only after that stronger source boundary succeeds.  Changed split/dividend rows
then trigger bounded SEP re-normalization against the candidate ACTIONS
generation before one atomic corpus publication activates both.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
import os
import uuid
from dataclasses import dataclass
from typing import Iterable, Mapping, Optional

from sentinel.core.terminal import DIVIDEND_ACTIONS, SHARE_SPLIT_ACTIONS
from sentinel.feed import (
    action_snapshot, action_source, anomalies, authority, calendar, publication, recovery,
    renormalize, sharadar, snapshot_export, source_validation, store, universe)

SEP_CURSOR_NAME = "sharadar-sep-lastupdated:v1"
# New name on purpose whenever split semantics change: a cursor earned under an
# older resolver must never suppress replay under newer economic semantics.
# v6 re-earns every retained split disposition after the sub-2% explicit split
# corroboration fix introduced for TRI 2026-05-04.  v5 remains historical
# evidence only and cannot authorize the corrected interpretation.
ACTIONS_CURSOR_NAME = "sharadar-actions-export-reconcile:v6"
ACTIONS_CURSOR_KIND = "sharadar-actions-export-reconcile/v6"
# Full ACTIONS authority must cover the decision frontier itself.  A 7-day
# cadence allowed a same-day omitted dividend/terminal action to coexist with a
# READY frontier.  One vendor export per decision day is intentionally stronger.
ACTIONS_RECONCILE_DAYS = int(os.getenv("SHARADAR_ACTIONS_RECONCILE_DAYS", "1"))
ACTIONS_FULL_WINDOW_START = "1900-01-01"
_SPLIT_SEMANTIC_ACTIONS = frozenset(SHARE_SPLIT_ACTIONS) | {"adrratiosplit"}


class MutationCursorUnavailable(RuntimeError):
    """No complete source proof has established where incremental CDC may begin."""


class SharadarMutationRefused(RuntimeError):
    """A historical vendor mutation cannot be applied without guessing."""


@dataclass(frozen=True)
class SourceCursor:
    kind: str
    processed_through: dt.date
    publication_version: int


class LastUpdatedTrackingFetch:
    """Transparent fetch wrapper used by a complete seed to earn CDC bootstrap."""

    def __init__(self, fetch, *, through: str | dt.date | None = None):
        self._fetch = fetch
        self._through = (None if through is None else
                         dt.date.fromisoformat(str(through)))
        self.max_sep_lastupdated: Optional[dt.date] = None

    def __call__(self, table, params=None, **kwargs):
        rows = self._fetch(table, params, **kwargs)
        if table != sharadar.SEP:
            return rows

        def replay():
            for row in rows:
                value = row.get("lastupdated")
                if value not in (None, ""):
                    try:
                        observed = dt.date.fromisoformat(str(value))
                    except ValueError as exc:
                        raise SharadarMutationRefused(
                            f"SEP lastupdated {value!r} is not an ISO date") from exc
                    if self._through is not None and observed > self._through:
                        raise SharadarMutationRefused(
                            f"SEP lastupdated {observed} is beyond seed "
                            f"observation boundary {self._through}")
                    if (self.max_sep_lastupdated is None
                            or observed > self.max_sep_lastupdated):
                        self.max_sep_lastupdated = observed
                yield row
        return replay()


def _ensure_cursor_table(conn) -> None:
    """Install the durable source-cursor table before the first cursor access.

    #185 introduced maintenance cursors after the original Sentinel schema was
    already widely deployed.  The first implementation referenced the table but
    never created it, so a clean database and every upgraded appliance failed on
    the first seed/daily/readiness cursor read with UndefinedTable.  Keep the
    migration colocated with the cursor authority so no caller can observe a
    half-installed contract.  CREATE IF NOT EXISTS is idempotent and remains in
    the caller's transaction; the surrounding operation decides when it commits.
    """
    with conn.cursor() as cur:
        cur.execute(
            "CREATE TABLE IF NOT EXISTS sentinel_processed_sessions ("
            " cursor_name TEXT PRIMARY KEY,"
            " session DATE NOT NULL,"
            " state JSONB NOT NULL,"
            " updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW())")


def _read_cursor(conn, name: str, kind: str) -> Optional[SourceCursor]:
    _ensure_cursor_table(conn)
    with conn.cursor() as cur:
        cur.execute(
            "SELECT session,state FROM sentinel_processed_sessions"
            " WHERE cursor_name=%s", (name,))
        row = cur.fetchone()
    if row is None:
        return None
    raw = row[1]
    if isinstance(raw, dict):
        state = raw
    else:
        try:
            state = json.loads(str(raw))
        except (TypeError, ValueError) as exc:
            raise SharadarMutationRefused(
                f"source cursor {name} is not valid JSON") from exc
    required = {"kind", "processed_through", "publication_version"}
    if not isinstance(state, dict) or set(state) != required or state.get("kind") != kind:
        raise SharadarMutationRefused(
            f"source cursor {name} has an unknown durable state shape")
    try:
        through = dt.date.fromisoformat(str(state["processed_through"]))
        version = int(state["publication_version"])
    except (TypeError, ValueError) as exc:
        raise SharadarMutationRefused(
            f"source cursor {name} has invalid date/version evidence") from exc
    row_date = (row[0] if isinstance(row[0], dt.date)
                else dt.date.fromisoformat(str(row[0])))
    if row_date != through:
        raise SharadarMutationRefused(
            f"source cursor {name} row date disagrees with its state")
    with conn.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM sentinel_corpus_publications WHERE version=%s",
            (version,))
        if cur.fetchone() is None:
            raise SharadarMutationRefused(
                f"source cursor {name} names missing publication v{version}")
    current = publication.require_current(conn)
    if version > current.version:
        raise SharadarMutationRefused(
            f"source cursor {name} is ahead of current publication v{current.version}")
    return SourceCursor(kind=kind, processed_through=through,
                        publication_version=version)


def load_sep_cursor(conn) -> Optional[SourceCursor]:
    return _read_cursor(conn, SEP_CURSOR_NAME, "sharadar-sep-lastupdated/v1")


def load_actions_cursor(conn) -> Optional[SourceCursor]:
    return _read_cursor(conn, ACTIONS_CURSOR_NAME, ACTIONS_CURSOR_KIND)


def _write_cursor(conn, *, name: str, kind: str, through: dt.date,
                  publication_version: int) -> SourceCursor:
    prior = _read_cursor(conn, name, kind)
    if prior is not None and through < prior.processed_through:
        raise SharadarMutationRefused(
            f"source cursor {name} cannot move backward from "
            f"{prior.processed_through} to {through}")
    with conn.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM sentinel_corpus_publications WHERE version=%s",
            (int(publication_version),))
        if cur.fetchone() is None:
            raise SharadarMutationRefused(
                f"cannot advance {name} to nonexistent publication "
                f"v{publication_version}")
        payload = json.dumps({
            "kind": kind,
            "processed_through": through.isoformat(),
            "publication_version": int(publication_version),
        }, sort_keys=True)
        cur.execute(
            "INSERT INTO sentinel_processed_sessions"
            " (cursor_name,session,state) VALUES (%s,%s,%s::jsonb)"
            " ON CONFLICT (cursor_name) DO UPDATE SET"
            " session=EXCLUDED.session,state=EXCLUDED.state,updated_at=NOW()",
            (name, through.isoformat(), payload))
    conn.commit()
    return SourceCursor(kind=kind, processed_through=through,
                        publication_version=int(publication_version))


def establish_sep_cursor_after_seed(conn, *, through: dt.date,
                                    publication_version: int) -> SourceCursor:
    return _write_cursor(
        conn, name=SEP_CURSOR_NAME, kind="sharadar-sep-lastupdated/v1",
        through=through, publication_version=publication_version)


def establish_sep_cursor_after_complete_reconciliation(
        conn, *, through: dt.date, publication_version: int) -> SourceCursor:
    """Bootstrap CDC only after a full current-source value/key proof."""
    return _write_cursor(
        conn, name=SEP_CURSOR_NAME, kind="sharadar-sep-lastupdated/v1",
        through=through, publication_version=publication_version)


def _canonical(value):
    if value is None:
        return None
    if isinstance(value, (dt.date, dt.datetime)):
        return value.isoformat()
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        if isinstance(value, float) and not math.isfinite(value):
            return str(value)
        return format(value, ".17g") if isinstance(value, float) else value
    return str(value)


def _mutation_digest(rows: Iterable[Mapping]) -> tuple[int, str]:
    """Order-independent, multiplicity-sensitive strategy-field fingerprint."""
    mask = (1 << 256) - 1
    count = a = b = 0
    fields = ("date", "ticker", "open", "close", "closeunadj", "volume",
              "lastupdated")
    for row in rows:
        payload = json.dumps(
            {k: _canonical(row.get(k)) for k in fields},
            sort_keys=True, separators=(",", ":")).encode("utf-8")
        count += 1
        a = (a + int.from_bytes(hashlib.sha256(b"\x00" + payload).digest(), "big")) & mask
        b = (b + int.from_bytes(hashlib.sha256(b"\x01" + payload).digest(), "big")) & mask
    witness = (count.to_bytes(16, "big") + a.to_bytes(32, "big")
               + b.to_bytes(32, "big"))
    return count, hashlib.sha256(witness).hexdigest()


def _stable_rows(fetch, table: str, params: Mapping[str, str]) -> list[dict]:
    if table == sharadar.SEP:
        first = [dict(row) for row in source_validation.validated_market_rows(
            table, fetch(table, params), params)]
        second = [dict(row) for row in source_validation.validated_market_rows(
            table, fetch(table, params), params)]
    else:
        first = [dict(row) for row in fetch(table, params)]
        second = [dict(row) for row in fetch(table, params)]
    if table == sharadar.ACTIONS:
        one = authority.observe_actions(first)
        two = authority.observe_actions(second)
        authority.require_stable(table, one, two)
    elif table == sharadar.SEP:
        c1, d1 = _mutation_digest(first)
        c2, d2 = _mutation_digest(second)
        if (c1, d1) != (c2, d2):
            raise authority.VendorPublicationUnstable(
                f"Sharadar SEP mutation set changed across two complete "
                f"observations: rows {c1:,}->{c2:,}, fingerprint "
                f"{d1[:16]}->{d2[:16]}")
    else:
        raise ValueError(f"no reconciliation fingerprint for {table}")
    return second


def _positive(value) -> bool:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return False
    return math.isfinite(number) and number > 0


def _validate_sep_mutation_rows(conn, rows: Iterable[Mapping], *,
                                lo: dt.date, hi: dt.date,
                                published_from: dt.date,
                                published_through: dt.date) -> list[str]:
    resolver = universe.load_resolver(conn).resolve
    dates: list[str] = []
    for row in rows:
        ticker = str(row.get("ticker") or "")
        session = str(row.get("date") or "")
        updated_raw = row.get("lastupdated")
        try:
            updated = dt.date.fromisoformat(str(updated_raw))
            session_date = dt.date.fromisoformat(session)
        except (TypeError, ValueError) as exc:
            raise SharadarMutationRefused(
                f"SEP mutation row {ticker!r}/{session!r} has invalid date "
                f"or lastupdated {updated_raw!r}") from exc
        if not lo <= updated <= hi:
            raise SharadarMutationRefused(
                f"SEP mutation row {ticker}/{session} lies outside requested "
                f"lastupdated interval {lo}..{hi}")
        if not ticker:
            raise SharadarMutationRefused(
                f"SEP mutation row on {session} has no ticker")
        # CDC owns historical rows already inside published market authority.
        # A row outside that retained horizon belongs to a future ordinary daily
        # load or a deliberately wider complete seed. Letting a current
        # lastupdated row widen either edge would recreate the ACTIONS defect one
        # source membrane over.
        if session_date < published_from or session_date > published_through:
            raise SharadarMutationRefused(
                f"SEP mutation row {ticker}/{session} lies outside the "
                f"published authority horizon {published_from}.."
                f"{published_through}; refusing to filter source evidence")
        if resolver(ticker, session) is None:
            raise SharadarMutationRefused(
                f"SEP mutation {ticker}/{session} has no permanent identity; "
                "refusing to advance the mutation watermark past it")
        # The canonical normalizer drops a row with no raw close. That is safe on
        # ordinary source ingest but NOT on a mutation cursor: dropping the new
        # observation and advancing the watermark would leave the old stored bar
        # silently authoritative forever.
        if not _positive(row.get("closeunadj")):
            raise SharadarMutationRefused(
                f"SEP mutation {ticker}/{session} has no positive raw close; "
                "refusing to preserve stale local economics while advancing CDC")
        dates.append(session_date.isoformat())
    return dates


def reconcile_sep_mutations(conn, *, fetch=sharadar.fetch_table,
                            through: str) -> Optional[SourceCursor]:
    """Apply every SEP mutation through the normal bounded ingest normalizer."""
    store._assert_corpus_locked(conn)
    cursor = load_sep_cursor(conn)
    if cursor is None:
        raise MutationCursorUnavailable(
            "SEP lastupdated cursor is absent. A complete source-stable seed or "
            "complete value/key reconciliation must establish the initial "
            "watermark; a moving price-date window cannot prove old rows current.")
    hi = dt.date.fromisoformat(str(through))
    if hi <= cursor.processed_through:
        return cursor
    lo = cursor.processed_through - dt.timedelta(days=1)
    params = {"lastupdated.gte": lo.isoformat(),
              "lastupdated.lte": hi.isoformat()}
    rows = _stable_rows(fetch, sharadar.SEP, params)
    market_start, market_end = _retained_market_bounds(conn)
    published_from = dt.date.fromisoformat(market_start)
    published_through = dt.date.fromisoformat(market_end)
    dates = _validate_sep_mutation_rows(
        conn, rows, lo=lo, hi=hi, published_from=published_from,
        published_through=published_through)

    if not dates:
        current = publication.require_current(conn)
        return _write_cursor(
            conn, name=SEP_CURSOR_NAME, kind="sharadar-sep-lastupdated/v1",
            through=hi, publication_version=current.version)

    windows = renormalize.correction_windows(
        dates, market_start=market_start, market_end=market_end)
    run = store.IngestRun(
        conn, "sep_mutations", date_from=windows[0][0], date_to=windows[-1][1],
        chunks_total=len(windows))
    try:
        replayed = renormalize.renormalize(
            conn, fetch=fetch, run=run, dates=dates,
            chunk_prefix="lastupdated", market_start=market_start,
            market_end=market_end)
    except BaseException:
        # ``run.chunk`` records failures that occur inside a chunk. A failure
        # constructing the first window before entering it still needs a durable
        # failed terminal state rather than an orphan RUNNING row.
        if run.progress.chunks_done == 0:
            run.finish("failed", "historical SEP mutation re-normalization failed")
        raise
    run.finish("success")
    published = publication.publish(
        conn, run_id=run.progress.run_id,
        window_start=windows[0][0], window_end=windows[-1][1],
        evidence={
            "kind": "sep_mutations",
            "lastupdated_window": [lo.isoformat(), hi.isoformat()],
            "source_rows": len(rows),
            "affected_source_dates": len(set(dates)),
            "replay_windows": [
                {"start": item.start, "end": item.end,
                 "source_rows": item.source_rows,
                 "bars_written": item.bars_written,
                 "rows_dropped": item.rows_dropped}
                for item in replayed],
        })
    return _write_cursor(
        conn, name=SEP_CURSOR_NAME, kind="sharadar-sep-lastupdated/v1",
        through=hi, publication_version=published.version)


def _active_action_rows(conn) -> dict[str, dict]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT source_row_id,ticker,session,action,name,value,contraticker,"
            " contraname FROM sentinel_active_actions")
        rows = cur.fetchall()
    out: dict[str, dict] = {}
    for identity, ticker, session, action, name, value, contra, contra_name in rows:
        out[str(identity)] = {
            "ticker": ticker, "date": str(session), "action": action,
            "name": name, "value": value, "contraticker": contra,
            "contraname": contra_name,
        }
    return out



def _iter_active_action_rows(conn) -> Iterable[dict]:
    """Stream the published ACTIONS generation without a client-side result set."""
    name = f"sentinel_actions_{uuid.uuid4().hex}"
    try:
        cursor = conn.cursor(name=name)
    except TypeError:  # deterministic lightweight test doubles
        cursor = conn.cursor()
    with cursor as cur:
        if hasattr(cur, "itersize"):
            cur.itersize = 5_000
        cur.execute(
            "SELECT source_row_id,source_payload,ticker,session,action,name,value,"
            " contraticker,contraname FROM sentinel_active_actions"
            " ORDER BY source_row_id")
        while True:
            batch = cur.fetchmany(2_000)
            if not batch:
                return
            for (identity, payload, ticker, session, action, name, value,
                 contraticker, contraname) in batch:
                yield {
                    "source_row_id": str(identity),
                    "source_payload": payload,
                    "ticker": str(ticker),
                    "date": str(session),
                    "action": str(action),
                    "name": name,
                    "value": value,
                    "contraticker": contraticker,
                    "contraname": contraname,
                }


def _bar_affecting_action(row: Mapping) -> bool:
    action = str(row.get("action") or "").lower()
    return action in SHARE_SPLIT_ACTIONS or action in DIVIDEND_ACTIONS


def _action_change_dates(conn, rows: Iterable[Mapping]) -> list[str]:
    prior = _active_action_rows(conn)
    current = {
        identity: dict(row)
        for identity, _payload, row in action_source.distinct_rows(rows)
    }
    changed = set(prior).symmetric_difference(current)
    dates: set[str] = set()
    for identity in changed:
        row = current.get(identity) or prior.get(identity)
        if row is not None and _bar_affecting_action(row):
            value = str(row.get("date") or "")
            try:
                dt.date.fromisoformat(value)
            except ValueError as exc:
                raise SharadarMutationRefused(
                    f"changed ACTIONS row has invalid date {value!r}") from exc
            dates.add(value)
    return sorted(dates)


def _validate_action_snapshot_window(rows: Iterable[Mapping], *, hi: dt.date) -> None:
    for row in rows:
        value = str(row.get("date") or "")
        try:
            observed = dt.date.fromisoformat(value)
        except ValueError as exc:
            raise SharadarMutationRefused(
                f"complete ACTIONS snapshot has invalid date {value!r}") from exc
        if observed < dt.date.fromisoformat(ACTIONS_FULL_WINDOW_START) or observed > hi:
            raise SharadarMutationRefused(
                f"complete ACTIONS snapshot row {row.get('ticker')}/{value} lies "
                f"outside claimed authority window "
                f"{ACTIONS_FULL_WINDOW_START}..{hi.isoformat()}")


def _retained_market_bounds(conn) -> tuple[str, str]:
    """Return the published SEP horizon, resilient to a failed in-place write.

    Visible rows normally provide the exact bounds.  A failed upsert can hide a
    formerly published edge row by taking ownership of its key, so the durable
    windows of published market-writing runs are included as a second witness.
    ACTIONS reconciliations are deliberately excluded: their 1900 authority
    window is metadata scope, not price scope.
    """
    candidates: list[str] = []
    with conn.cursor() as cur:
        cur.execute(
            "SELECT MIN(b.session),MAX(b.session) FROM sentinel_bars b WHERE "
            + publication.visible_predicate("b"))
        visible = cur.fetchone()
    if visible:
        candidates.extend(str(value) for value in visible if value is not None)

    with conn.cursor() as cur:
        cur.execute(
            "SELECT MIN(p.window_start),MAX(p.window_end)"
            " FROM sentinel_corpus_publications p"
            " JOIN feed_ingest_runs r ON r.run_id=p.run_id"
            " WHERE r.kind IN ('seed','daily','sep_mutations')")
        published = cur.fetchone()
    if published:
        candidates.extend(str(value) for value in published if value is not None)

    if not candidates:
        raise SharadarMutationRefused(
            "published corpus has no retained SEP market boundary for ACTIONS "
            "reconciliation")
    sessions = calendar.sessions_in_range(min(candidates), max(candidates))
    if not sessions:
        raise SharadarMutationRefused(
            "published SEP market boundary contains no XNYS session")
    return sessions[0], sessions[-1]


def _failed_action_reconcile_bar_footprint(
        conn, *, market_start: str, market_end: str) -> tuple[list[str], bool]:
    """Sessions a retry must reclaim, plus whether out-of-range residue exists."""
    common = (
        " FROM sentinel_bars b"
        " JOIN feed_ingest_runs r ON r.run_id=b.last_written_run_id"
        " WHERE r.kind='actions_reconcile' AND r.status='failed'"
        "   AND NOT EXISTS (SELECT 1 FROM sentinel_corpus_publications p"
        "                   WHERE p.run_id=b.last_written_run_id)")
    with conn.cursor() as cur:
        cur.execute(
            "SELECT DISTINCT b.session" + common
            + " AND b.session BETWEEN %s AND %s ORDER BY b.session",
            (str(market_start), str(market_end)))
        dates = [str(row[0]) for row in cur.fetchall()]
    with conn.cursor() as cur:
        cur.execute(
            "SELECT EXISTS(SELECT 1" + common
            + " AND (b.session<%s OR b.session>%s))",
            (str(market_start), str(market_end)))
        row = cur.fetchone()
    return dates, bool(row and row[0])


def _semantic_upgrade_replay_dates(
        conn, *, market_start: str, market_end: str,
        current_action_rows: Iterable[Mapping],
        prior_action_rows: Iterable[Mapping]) -> list[str]:
    """Every retained split date whose pre-v6 economics must be re-earned.

    Blocking evidence is not enough: older code could publish an accepted ADR
    resize, reciprocal stock-split orientation, or suppress a real sub-2% split
    before comparing it with explicit ACTIONS authority. Include every active
    split disposition, every current or previously active raw source row from
    either side of the split/ADR semantic boundary, and every published effective
    non-unit ratio. The corpus selector covers a legacy derived or repaired bar
    with no surviving disposition or source row.
    """
    rows = anomalies.active_rows(
        conn, start=str(market_start), end=str(market_end),
        kinds=anomalies.SPLIT_DISPOSITION_KINDS)
    dates = {str(row["session"]) for row in rows}
    dates.update(
        str(row["session"])
        for row in publication.effective_nonunit_split_rows(
            conn, start=str(market_start), end=str(market_end)))
    for action_rows in (current_action_rows, prior_action_rows):
        for row in action_rows:
            if str(row.get("action") or "").lower() not in (
                    _SPLIT_SEMANTIC_ACTIONS):
                continue
            day = str(row.get("date") or "")
            effective = calendar.session_on_or_after(day)
            if str(market_start) <= effective <= str(market_end):
                dates.add(day)
    return sorted(dates)



def reconcile_actions_if_due(conn, *, fetch=sharadar.fetch_table,
                             through: str, force: bool = False
                             ) -> Optional[SourceCursor]:
    """Reconcile complete ACTIONS with bounded memory and exact negative space."""
    store._assert_corpus_locked(conn)
    if ACTIONS_RECONCILE_DAYS < 1:
        raise ValueError("SHARADAR_ACTIONS_RECONCILE_DAYS must be >= 1")
    hi = dt.date.fromisoformat(str(through))
    prior_cursor = load_actions_cursor(conn)
    if (not force and prior_cursor is not None
            and (hi - prior_cursor.processed_through).days < ACTIONS_RECONCILE_DAYS):
        return prior_cursor

    params = sharadar.date_params(ACTIONS_FULL_WINDOW_START, hi.isoformat())
    if fetch is sharadar.fetch_table:
        snapshot, source_evidence = snapshot_export.fetch_complete_actions(
            through=hi.isoformat())
    else:
        stable = _stable_rows(fetch, sharadar.ACTIONS, params)
        snapshot = action_snapshot.ActionSnapshot.from_rows(stable)
        del stable
        source_evidence = {
            "authority": "injected-double-observation/v1",
            "source_rows": snapshot.source_rows,
            "distinct_source_rows": len(snapshot),
            "exact_repeat_rows": snapshot.exact_repeat_rows,
        }

    with snapshot:
        _validate_action_snapshot_window(snapshot, hi=hi)
        if not snapshot:
            raise SharadarMutationRefused(
                "complete Sharadar ACTIONS reconciliation returned zero rows; "
                "refusing to turn a suspicious empty source into mass removals")

        prior_count = snapshot.load_prior_rows(_iter_active_action_rows(conn))
        if prior_count and len(snapshot) < int(prior_count * 0.90):
            raise SharadarMutationRefused(
                f"complete ACTIONS source shrank from {prior_count:,} active "
                f"rows to {len(snapshot):,}; refusing mass-removal authority "
                "without inspection")
        bar_actions = set(SHARE_SPLIT_ACTIONS) | set(DIVIDEND_ACTIONS)
        changed_dates = snapshot.changed_dates(bar_actions)
        changed_source_rows = snapshot.identity_delta_count()
        market_start, market_end = _retained_market_bounds(conn)
        recovery_dates, has_outside_failed_bars = (
            _failed_action_reconcile_bar_footprint(
                conn, market_start=market_start, market_end=market_end))
        semantic_dates = (_semantic_upgrade_replay_dates(
            conn, market_start=market_start, market_end=market_end,
            current_action_rows=snapshot,
            prior_action_rows=snapshot.iter_prior())
            if prior_cursor is None else [])
        replay_dates = sorted(
            set(changed_dates) | set(recovery_dates) | set(semantic_dates))

        if (changed_source_rows == 0
                and not recovery_dates and not semantic_dates
                and not has_outside_failed_bars):
            current = publication.require_current(conn)
            return _write_cursor(
                conn, name=ACTIONS_CURSOR_NAME, kind=ACTIONS_CURSOR_KIND,
                through=hi, publication_version=current.version)

        windows = renormalize.correction_windows(
            replay_dates, market_start=market_start, market_end=market_end)
        run = store.IngestRun(
            conn, "actions_reconcile",
            date_from=ACTIONS_FULL_WINDOW_START, date_to=hi.isoformat(),
            chunks_total=2 + len(windows))
        with run.chunk("actions_full"):
            run.progress.rows_written += store.write_actions(
                conn, snapshot, run_id=run.progress.run_id,
                window_start=ACTIONS_FULL_WINDOW_START,
                window_end=hi.isoformat())
        if windows:
            renormalize.renormalize(
                conn, fetch=fetch, run=run, dates=replay_dates,
                include_action_run_id=run.progress.run_id,
                chunk_prefix="actions", market_start=market_start,
                market_end=market_end)
        with run.chunk("publication_recovery"):
            recovery.record_action_reconcile_retirement_plan(
                conn, run_id=run.progress.run_id,
                plan=recovery.ActionReconcileRetirementPlan(
                    market_start=market_start, market_end=market_end,
                    replay_windows=tuple(windows)))
        run.finish("success")
        published = publication.publish(
            conn, run_id=run.progress.run_id,
            window_start=ACTIONS_FULL_WINDOW_START,
            window_end=hi.isoformat(),
            evidence={
                "kind": "actions_reconcile",
                "source_authority": source_evidence,
                "source_rows": snapshot.source_rows,
                "distinct_source_rows": len(snapshot),
                "exact_repeat_rows": snapshot.exact_repeat_rows,
                "changed_source_rows": changed_source_rows,
                "changed_action_dates": len(set(changed_dates)),
                "recovery_bar_dates": len(set(recovery_dates)),
                "semantic_upgrade_dates": len(set(semantic_dates)),
                "affected_bar_dates": len(set(replay_dates)),
                "retained_market_window": [market_start, market_end],
                "replay_windows": [list(w) for w in windows],
            })
        return _write_cursor(
            conn, name=ACTIONS_CURSOR_NAME, kind=ACTIONS_CURSOR_KIND,
            through=hi, publication_version=published.version)

__all__ = [
    "ACTIONS_RECONCILE_DAYS", "LastUpdatedTrackingFetch",
    "MutationCursorUnavailable", "SEP_CURSOR_NAME", "SharadarMutationRefused",
    "SourceCursor", "establish_sep_cursor_after_complete_reconciliation",
    "establish_sep_cursor_after_seed", "load_actions_cursor", "load_sep_cursor",
    "reconcile_actions_if_due", "reconcile_sep_mutations",
]
