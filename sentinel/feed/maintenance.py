"""Current-source reconciliation beyond the moving market-session window.

Two vendor clocks are intentionally separate:

``SESSION FRONTIER``
    discovers newly closed trading dates.

``MUTATION WATERMARK``
    discovers rows from old sessions that Sharadar changed later. SEP exposes
    this as a date-valued ``lastupdated`` field.

A price-date overlap cannot substitute for the second clock. The watermark here
is durable, overlaps the complete previous vendor-update date, and advances only
after the corresponding candidate corpus generation has been published. A crash
may therefore replay work, but it cannot skip it.

ACTIONS has no equivalent documented mutation clock. It is periodically fetched
in full twice and reconciled through the existing PRESENT/REMOVED generation
model. Absence becomes authority only when the two complete source observations
agree.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
import os
from dataclasses import dataclass
from typing import Iterable, Mapping, Optional

from stock_strategy_shared.wealth_core.feed import VendorBar

from sentinel.feed import authority, publication, sharadar, store, universe
from sentinel.feed.domains import NormalisedBar

SEP_CURSOR_NAME = "sharadar-sep-lastupdated:v1"
ACTIONS_CURSOR_NAME = "sharadar-actions-reconcile:v1"
ACTIONS_RECONCILE_DAYS = int(os.getenv("SHARADAR_ACTIONS_RECONCILE_DAYS", "7"))
ACTIONS_FULL_WINDOW_START = "1900-01-01"


class MutationCursorUnavailable(RuntimeError):
    """No complete source scan has established where incremental CDC may begin."""


class SharadarMutationRefused(RuntimeError):
    """A historical vendor mutation cannot be applied without guessing."""


@dataclass(frozen=True)
class SourceCursor:
    kind: str
    processed_through: dt.date
    publication_version: int


class LastUpdatedTrackingFetch:
    """Transparent fetch wrapper used by a complete seed to earn the CDC cursor."""

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
    expected = {"kind", "processed_through", "publication_version"}
    if not isinstance(state, dict) or set(state) != expected or state.get("kind") != kind:
        raise SharadarMutationRefused(
            f"source cursor {name} has an unknown durable state shape")
    try:
        through = dt.date.fromisoformat(str(state["processed_through"]))
        version = int(state["publication_version"])
    except (TypeError, ValueError) as exc:
        raise SharadarMutationRefused(
            f"source cursor {name} has invalid date/version evidence") from exc
    row_date = row[0] if isinstance(row[0], dt.date) else dt.date.fromisoformat(str(row[0]))
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
            f"source cursor {name} is ahead of current publication "
            f"v{current.version}")
    return SourceCursor(kind=kind, processed_through=through,
                        publication_version=version)


def load_sep_cursor(conn) -> Optional[SourceCursor]:
    return _read_cursor(conn, SEP_CURSOR_NAME, "sharadar-sep-lastupdated/v1")


def load_actions_cursor(conn) -> Optional[SourceCursor]:
    return _read_cursor(conn, ACTIONS_CURSOR_NAME,
                        "sharadar-actions-reconcile/v1")


def _write_cursor(conn, *, name: str, kind: str, through: dt.date,
                  publication_version: int) -> SourceCursor:
    # The publication must already exist. A crash after publication but before
    # this tiny cursor commit is safe: the next run replays the overlap.
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
    """A complete, source-stable seed is the authority that earns CDC bootstrap."""
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
    """Order-independent, multiplicity-sensitive CDC-set fingerprint."""
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


def _positive(value) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and number > 0 else None


def _existing_bar_authority(conn, sid: str, session: str):
    """Physical row plus whether its current owner is already published.

    The physical read is deliberate. A failed candidate overwrites a bar in
    place and makes it invisible by changing ``last_written_run_id``. On retry,
    that row still carries useful split/dividend continuity and, crucially, must
    be RECLAIMED by the new run even when its economics already equal the vendor
    replay. Filtering to visible rows here would mistake a retry for a new key.
    """
    expr = publication.effective_split_ratio("b")
    with conn.cursor() as cur:
        cur.execute(
            "SELECT b.close_signal,b.close_unadjusted,b.open_unadjusted,b.volume,"
            f" {expr} AS split_ratio,b.dividend_per_share,b.last_written_run_id,"
            " (b.last_written_run_id IS NULL OR EXISTS ("
            "   SELECT 1 FROM sentinel_corpus_publications p"
            "   WHERE p.run_id=b.last_written_run_id)) AS owner_published"
            " FROM sentinel_bars b WHERE b.security_id=%s AND b.session=%s",
            (str(sid), str(session)))
        return cur.fetchone()


def _mutation_bar(conn, row: Mapping, resolver) -> Optional[NormalisedBar]:
    session = str(row.get("date") or "")
    ticker = str(row.get("ticker") or "")
    if not session or not ticker:
        raise SharadarMutationRefused("SEP mutation row has no ticker/session")
    sid = resolver(ticker, session)
    if sid is None:
        raise SharadarMutationRefused(
            f"SEP mutation {ticker}/{session} has no permanent identity; "
            "refusing to overwrite historical evidence by ticker guess")
    existing = _existing_bar_authority(conn, str(sid), session)
    if existing is None:
        raise SharadarMutationRefused(
            f"SEP mutation introduces previously unseen key {ticker}/{session}; "
            "lastupdated CDC cannot prove a deletion/insertion key-set change. "
            "Run the complete SEP reconciliation before publishing it.")

    signal = _positive(row.get("close"))
    raw = _positive(row.get("closeunadj"))
    if signal is None or raw is None:
        raise SharadarMutationRefused(
            f"SEP mutation {ticker}/{session} removes a required price domain; "
            "refusing to preserve the stale prior value or invent a replacement")
    reported_volume = _positive(row.get("volume"))
    adjusted_open = _positive(row.get("open"))
    raw_open = (round(adjusted_open * raw / signal, 6)
                if adjusted_open is not None else None)
    split_ratio = float(existing[4] or 1.0)
    dividend = float(existing[5] or 0.0)

    old = (existing[0], existing[1], existing[2], existing[3])
    new = (signal, raw, raw_open, reported_volume)
    same_economics = all(
        (a is None and b is None) or
        (a is not None and b is not None and float(a) == float(b))
        for a, b in zip(old, new))
    if same_economics and bool(existing[7]):
        # Vendor ``lastupdated`` can advance for fields Sentinel does not consume.
        # If the row's owner is already published, no corpus churn is required.
        return None
    # If owner_published is false, DO return the otherwise-identical bar. The
    # store upsert has an explicit ownership clause that claims an unchanged key
    # from an older unpublished run; skipping it here would permanently strand
    # that candidate and defeat crash convergence.

    return NormalisedBar(
        close_signal=signal,
        vendor=VendorBar(
            session=session, security_id=str(sid), ticker=ticker,
            raw_close=raw, raw_open=raw_open, volume=reported_volume,
            split_ratio=split_ratio, dividend_per_share=dividend,
            tradeable=bool(raw and reported_volume)))


def reconcile_sep_mutations(conn, *, fetch=sharadar.fetch_table,
                            through: str) -> Optional[SourceCursor]:
    """Apply all SEP rows updated since the durable vendor-update cursor.

    ``through`` is an ISO vendor-update date. The prior date is re-read in full;
    because Sharadar's ``lastupdated`` is date-valued, this captures every row
    sharing the boundary value without inventing an intra-day ordering.
    """
    store._assert_corpus_locked(conn)
    cursor = load_sep_cursor(conn)
    if cursor is None:
        raise MutationCursorUnavailable(
            "SEP lastupdated cursor is absent. A complete source-stable seed (or "
            "complete SEP reconciliation) must establish the initial watermark; "
            "advancing it from a 14-day price window would skip older corrections.")
    hi = dt.date.fromisoformat(str(through))
    if hi <= cursor.processed_through:
        return cursor
    lo = cursor.processed_through - dt.timedelta(days=1)
    params = {"lastupdated.gte": lo.isoformat(),
              "lastupdated.lte": hi.isoformat()}
    rows = _stable_rows(fetch, sharadar.SEP, params)
    for row in rows:
        value = row.get("lastupdated")
        try:
            updated = dt.date.fromisoformat(str(value))
        except (TypeError, ValueError) as exc:
            raise SharadarMutationRefused(
                f"SEP mutation row has invalid lastupdated {value!r}") from exc
        if not lo <= updated <= hi:
            raise SharadarMutationRefused(
                f"SEP mutation row {row.get('ticker')}/{row.get('date')} lies "
                f"outside requested lastupdated interval {lo}..{hi}")

    resolver = universe.load_resolver(conn).resolve
    changed: list[NormalisedBar] = []
    for row in sorted(rows, key=lambda r: (str(r.get("date") or ""),
                                           str(r.get("ticker") or ""))):
        bar = _mutation_bar(conn, row, resolver)
        if bar is not None:
            changed.append(bar)

    sessions = [b.vendor.session for b in changed]
    run = store.IngestRun(
        conn, "sep_mutations",
        date_from=min(sessions) if sessions else lo.isoformat(),
        date_to=max(sessions) if sessions else hi.isoformat(), chunks_total=1)
    with run.chunk("lastupdated"):
        run.progress.rows_written += store.write_bars(
            conn, changed, run_id=run.progress.run_id, require_lock=True)
    run.finish("success")
    published = publication.publish(
        conn, run_id=run.progress.run_id,
        window_start=min(sessions) if sessions else lo.isoformat(),
        window_end=max(sessions) if sessions else hi.isoformat(),
        evidence={
            "kind": "sep_mutations",
            "lastupdated_window": [lo.isoformat(), hi.isoformat()],
            "source_rows": len(rows), "changed_rows": len(changed),
        })
    return _write_cursor(
        conn, name=SEP_CURSOR_NAME, kind="sharadar-sep-lastupdated/v1",
        through=hi, publication_version=published.version)


def reconcile_actions_if_due(conn, *, fetch=sharadar.fetch_table,
                             through: str, force: bool = False
                             ) -> Optional[SourceCursor]:
    """Periodically reconcile the complete ACTIONS key/content set."""
    store._assert_corpus_locked(conn)
    if ACTIONS_RECONCILE_DAYS < 1:
        raise ValueError("SHARADAR_ACTIONS_RECONCILE_DAYS must be >= 1")
    hi = dt.date.fromisoformat(str(through))
    prior = load_actions_cursor(conn)
    if (not force and prior is not None
            and (hi - prior.processed_through).days < ACTIONS_RECONCILE_DAYS):
        return prior
    rows = _stable_rows(fetch, sharadar.ACTIONS, {})
    if not rows:
        raise SharadarMutationRefused(
            "complete Sharadar ACTIONS reconciliation returned zero rows; "
            "refusing to turn a suspicious empty source into mass removals")

    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM sentinel_active_actions")
        active_rows = int(cur.fetchone()[0])
    if active_rows and len(rows) < int(active_rows * 0.90):
        raise SharadarMutationRefused(
            f"complete ACTIONS source shrank from {active_rows:,} active rows to "
            f"{len(rows):,}; refusing mass-removal authority without inspection")

    run = store.IngestRun(
        conn, "actions_reconcile",
        date_from=ACTIONS_FULL_WINDOW_START, date_to=hi.isoformat(), chunks_total=1)
    with run.chunk("actions_full"):
        run.progress.rows_written += store.write_actions(
            conn, rows, run_id=run.progress.run_id,
            window_start=ACTIONS_FULL_WINDOW_START, window_end=hi.isoformat())
    run.finish("success")
    published = publication.publish(
        conn, run_id=run.progress.run_id,
        window_start=ACTIONS_FULL_WINDOW_START, window_end=hi.isoformat(),
        evidence={"kind": "actions_reconcile", "source_rows": len(rows)})
    return _write_cursor(
        conn, name=ACTIONS_CURSOR_NAME, kind="sharadar-actions-reconcile/v1",
        through=hi, publication_version=published.version)


__all__ = [
    "ACTIONS_RECONCILE_DAYS", "LastUpdatedTrackingFetch",
    "MutationCursorUnavailable", "SEP_CURSOR_NAME", "SharadarMutationRefused",
    "SourceCursor", "establish_sep_cursor_after_seed", "load_actions_cursor",
    "load_sep_cursor", "reconcile_actions_if_due", "reconcile_sep_mutations",
]
