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

ACTIONS has no documented mutation timestamp, so it is periodically observed in
full twice.  Changed split/dividend source rows trigger the same bounded SEP
re-normalization against the *candidate* ACTIONS generation before one atomic
corpus publication activates both.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
import os
from dataclasses import dataclass
from typing import Iterable, Mapping, Optional

from sentinel.core.terminal import DIVIDEND_ACTIONS, SPLIT_ACTIONS
from sentinel.feed import (
    action_source, authority, publication, renormalize, sharadar, store, universe)

SEP_CURSOR_NAME = "sharadar-sep-lastupdated:v1"
ACTIONS_CURSOR_NAME = "sharadar-actions-reconcile:v1"
ACTIONS_RECONCILE_DAYS = int(os.getenv("SHARADAR_ACTIONS_RECONCILE_DAYS", "7"))
ACTIONS_FULL_WINDOW_START = "1900-01-01"


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

    def __init__(self, fetch):
        self._fetch = fetch
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
                    if (self.max_sep_lastupdated is None
                            or observed > self.max_sep_lastupdated):
                        self.max_sep_lastupdated = observed
                yield row
        return replay()


def _read_cursor(conn, name: str, kind: str) -> Optional[SourceCursor]:
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
    return _read_cursor(conn, ACTIONS_CURSOR_NAME,
                        "sharadar-actions-reconcile/v1")


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
                                lo: dt.date, hi: dt.date) -> list[str]:
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
    dates = _validate_sep_mutation_rows(conn, rows, lo=lo, hi=hi)

    if not dates:
        current = publication.require_current(conn)
        return _write_cursor(
            conn, name=SEP_CURSOR_NAME, kind="sharadar-sep-lastupdated/v1",
            through=hi, publication_version=current.version)

    windows = renormalize.correction_windows(dates)
    run = store.IngestRun(
        conn, "sep_mutations", date_from=windows[0][0], date_to=windows[-1][1],
        chunks_total=len(windows))
    try:
        replayed = renormalize.renormalize(
            conn, fetch=fetch, run=run, dates=dates,
            chunk_prefix="lastupdated")
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


def _bar_affecting_action(row: Mapping) -> bool:
    action = str(row.get("action") or "").lower()
    return action in SPLIT_ACTIONS or action in DIVIDEND_ACTIONS


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


def reconcile_actions_if_due(conn, *, fetch=sharadar.fetch_table,
                             through: str, force: bool = False
                             ) -> Optional[SourceCursor]:
    """Reconcile complete ACTIONS and replay affected split/dividend bar windows."""
    store._assert_corpus_locked(conn)
    if ACTIONS_RECONCILE_DAYS < 1:
        raise ValueError("SHARADAR_ACTIONS_RECONCILE_DAYS must be >= 1")
    hi = dt.date.fromisoformat(str(through))
    prior_cursor = load_actions_cursor(conn)
    if (not force and prior_cursor is not None
            and (hi - prior_cursor.processed_through).days < ACTIONS_RECONCILE_DAYS):
        return prior_cursor

    rows = _stable_rows(fetch, sharadar.ACTIONS, {})
    if not rows:
        raise SharadarMutationRefused(
            "complete Sharadar ACTIONS reconciliation returned zero rows; "
            "refusing to turn a suspicious empty source into mass removals")
    prior_active = _active_action_rows(conn)
    if prior_active and len(action_source.distinct_rows(rows)) < int(len(prior_active) * 0.90):
        raise SharadarMutationRefused(
            f"complete ACTIONS source shrank from {len(prior_active):,} active "
            f"rows to {len(action_source.distinct_rows(rows)):,}; refusing "
            "mass-removal authority without inspection")
    dates = _action_change_dates(conn, rows)

    current_ids = {
        identity for identity, _payload, _row in action_source.distinct_rows(rows)}
    if current_ids == set(prior_active):
        current = publication.require_current(conn)
        return _write_cursor(
            conn, name=ACTIONS_CURSOR_NAME,
            kind="sharadar-actions-reconcile/v1", through=hi,
            publication_version=current.version)

    windows = renormalize.correction_windows(dates)
    run = store.IngestRun(
        conn, "actions_reconcile",
        date_from=ACTIONS_FULL_WINDOW_START, date_to=hi.isoformat(),
        chunks_total=1 + len(windows))
    with run.chunk("actions_full"):
        run.progress.rows_written += store.write_actions(
            conn, rows, run_id=run.progress.run_id,
            window_start=ACTIONS_FULL_WINDOW_START, window_end=hi.isoformat())
    if dates:
        renormalize.renormalize(
            conn, fetch=fetch, run=run, dates=dates,
            include_action_run_id=run.progress.run_id,
            chunk_prefix="actions")
    run.finish("success")
    published = publication.publish(
        conn, run_id=run.progress.run_id,
        window_start=ACTIONS_FULL_WINDOW_START, window_end=hi.isoformat(),
        evidence={
            "kind": "actions_reconcile",
            "source_rows": len(rows),
            "changed_source_rows": len(set(prior_active).symmetric_difference(current_ids)),
            "affected_bar_dates": len(set(dates)),
            "replay_windows": [list(w) for w in windows],
        })
    return _write_cursor(
        conn, name=ACTIONS_CURSOR_NAME, kind="sharadar-actions-reconcile/v1",
        through=hi, publication_version=published.version)


__all__ = [
    "ACTIONS_RECONCILE_DAYS", "LastUpdatedTrackingFetch",
    "MutationCursorUnavailable", "SEP_CURSOR_NAME", "SharadarMutationRefused",
    "SourceCursor", "establish_sep_cursor_after_complete_reconciliation",
    "establish_sep_cursor_after_seed", "load_actions_cursor", "load_sep_cursor",
    "reconcile_actions_if_due", "reconcile_sep_mutations",
]
