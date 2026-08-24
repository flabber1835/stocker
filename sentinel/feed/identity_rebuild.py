"""Attended full-history recovery for historical TICKERS identity corrections.

Ordinary seed and daily ingestion must never reinterpret already-published bars
merely because Sharadar's current TICKERS snapshot changed a listing interval.
The guard in :mod:`sentinel.feed.universe` is therefore intentionally retained.
This module is the only stronger recovery boundary: a complete source-stable
seed replays every retained SEP session against the corrected TICKERS snapshot,
claims every replayed bar, and retires negative space in the same transaction as
the replacement universe projection and corpus publication.
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
from dataclasses import dataclass
from typing import Iterable, Mapping, Sequence

from sentinel.feed import coherence, publication, recovery, universe
from sentinel.feed import store as feed_store
from sentinel.feed import universe_projection

SCHEMA = "sentinel.identity-rebuild/1"


@dataclass(frozen=True)
class IdentityRebuildPlan:
    """Exact published boundary a full identity rebuild is allowed to replace."""

    market_start: str
    market_end: str
    base_version: int
    base_visible_start: str
    base_visible_end: str
    snapshot_date: str


def _date(value: str) -> _dt.date:
    try:
        return _dt.date.fromisoformat(str(value))
    except ValueError as exc:
        raise recovery.PublicationRecoveryRefused(
            f"identity rebuild boundary is not an ISO date: {value!r}") from exc


def _bar_bounds(conn, *, visible: bool) -> tuple[str | None, str | None]:
    predicate = ""
    if visible:
        predicate = " WHERE " + publication.visible_predicate("b")
    with conn.cursor() as cur:
        cur.execute(
            "SELECT MIN(b.session),MAX(b.session) FROM sentinel_bars b" + predicate)
        lo, hi = cur.fetchone()
    return (None if lo is None else str(lo), None if hi is None else str(hi))


def _unused_snapshot_date(conn, *, market_end: str,
                          observed_on: str | None = None) -> str:
    today = _date(observed_on or _dt.date.today().isoformat())
    lower = _date(market_end)
    if lower > today:
        raise recovery.PublicationRecoveryRefused(
            f"identity rebuild ends at future date {lower}; refusing to invent "
            "a TICKERS observation date")
    with conn.cursor() as cur:
        cur.execute(
            "SELECT snapshot_date FROM sentinel_universe"
            " WHERE snapshot_date BETWEEN %s AND %s",
            (lower.isoformat(), today.isoformat()))
        occupied = {str(row[0]) for row in cur.fetchall()}
    cursor = today
    while cursor >= lower:
        candidate = cursor.isoformat()
        if candidate not in occupied:
            return candidate
        cursor -= _dt.timedelta(days=1)
    raise recovery.PublicationRecoveryRefused(
        f"no unused TICKERS snapshot date exists in {lower}..{today}. "
        "Historical evidence is immutable; retry after a new observation date "
        "becomes available rather than overwriting a published snapshot")


def prepare(conn, *, date_from: str, date_to: str,
            observed_on: str | None = None) -> IdentityRebuildPlan:
    """Authorize only a complete replacement of the current physical history."""
    feed_store._assert_corpus_locked(conn)
    requested_lo, requested_hi = _date(date_from), _date(date_to)
    if requested_lo > requested_hi:
        raise recovery.PublicationRecoveryRefused(
            f"reversed identity rebuild range: {requested_lo} > {requested_hi}")

    report = publication.assert_coherent(conn)
    current = publication.require_current(conn)
    visible_lo, visible_hi = _bar_bounds(conn, visible=True)
    physical_lo, physical_hi = _bar_bounds(conn, visible=False)
    if visible_lo is None or visible_hi is None:
        raise recovery.PublicationRecoveryRefused(
            "historical identity mutation was reported but the published SEP "
            "corpus has no visible bar boundary")
    required_lo = min(value for value in (visible_lo, physical_lo) if value)
    required_hi = max(value for value in (visible_hi, physical_hi) if value)
    if requested_lo > _date(required_lo) or requested_hi < _date(required_hi):
        raise recovery.PublicationRecoveryRefused(
            f"identity rebuild {requested_lo}..{requested_hi} does not cover the "
            f"entire physical/published SEP history {required_lo}..{required_hi}. "
            "A partial replay cannot prove which old identity keys are obsolete")
    if report.version != current.version:
        raise recovery.PublicationRecoveryRefused(
            "corpus coherence and current publication disagree while preparing "
            "identity rebuild")

    return IdentityRebuildPlan(
        market_start=requested_lo.isoformat(),
        market_end=requested_hi.isoformat(),
        base_version=current.version,
        base_visible_start=visible_lo,
        base_visible_end=visible_hi,
        snapshot_date=_unused_snapshot_date(
            conn, market_end=requested_hi.isoformat(), observed_on=observed_on),
    )


def _plan_payload(plan: IdentityRebuildPlan) -> dict:
    return {
        "schema": SCHEMA,
        "market_start": plan.market_start,
        "market_end": plan.market_end,
        "base_version": int(plan.base_version),
        "base_visible_start": plan.base_visible_start,
        "base_visible_end": plan.base_visible_end,
        "snapshot_date": plan.snapshot_date,
    }


def record_plan(conn, *, run_id: str, plan: IdentityRebuildPlan) -> None:
    """Persist the replacement boundary before the long replay writes anything."""
    feed_store._assert_corpus_locked(conn)
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE feed_ingest_runs SET publication_recovery=%s::jsonb,"
            " updated_at=NOW()"
            " WHERE run_id=%s AND kind='seed' AND status='running'",
            (json.dumps(_plan_payload(plan), sort_keys=True), str(run_id)))
        changed = int(cur.rowcount)
    if changed != 1:
        raise recovery.PublicationRecoveryRefused(
            f"cannot bind identity rebuild plan to running seed {run_id}")
    conn.commit()


def _load_payload(conn, *, run_id: str) -> tuple[str, dict]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT status,publication_recovery FROM feed_ingest_runs"
            " WHERE run_id=%s AND kind='seed'", (str(run_id),))
        row = cur.fetchone()
    if row is None:
        raise recovery.PublicationRecoveryRefused(
            f"identity rebuild seed {run_id} has no lifecycle row")
    status, raw = str(row[0]), row[1]
    payload = raw if isinstance(raw, dict) else json.loads(raw or "{}")
    if not isinstance(payload, dict) or payload.get("schema") != SCHEMA:
        raise recovery.PublicationRecoveryRefused(
            f"seed {run_id} lacks a valid durable identity rebuild plan")
    return status, payload


def load_plan(conn, *, run_id: str) -> IdentityRebuildPlan:
    _status, payload = _load_payload(conn, run_id=run_id)
    required = {
        "schema", "market_start", "market_end", "base_version",
        "base_visible_start", "base_visible_end", "snapshot_date",
    }
    if not required.issubset(payload):
        raise recovery.PublicationRecoveryRefused(
            f"seed {run_id} has incomplete identity rebuild evidence")
    return IdentityRebuildPlan(
        market_start=_date(payload["market_start"]).isoformat(),
        market_end=_date(payload["market_end"]).isoformat(),
        base_version=int(payload["base_version"]),
        base_visible_start=_date(payload["base_visible_start"]).isoformat(),
        base_visible_end=_date(payload["base_visible_end"]).isoformat(),
        snapshot_date=_date(payload["snapshot_date"]).isoformat(),
    )


def _source_rows(rows: Iterable[Mapping]) -> list[Mapping]:
    material = [dict(row) for row in rows]
    if not material or any(
            str(row.get("table") or "").strip().upper() != "SEP"
            for row in material):
        raise recovery.PublicationRecoveryRefused(
            "identity rebuild requires one non-empty, explicitly table=SEP "
            "TICKERS snapshot")
    return material


def _universe_payload(rows: Sequence[Mapping], *, snapshot_date: str,
                      run_id: str) -> list[tuple]:
    payload: list[tuple] = []
    for row in rows:
        permaticker, ticker = row.get("permaticker"), row.get("ticker")
        if not permaticker or not ticker:
            continue
        payload.append((
            str(permaticker).strip(), str(ticker).strip().upper(),
            row.get("category"), row.get("sector"),
            universe._related_observation(row),
            universe._d(row.get("firstpricedate") or row.get("first_price_date")),
            universe._d(row.get("lastpricedate") or row.get("last_price_date")),
            universe._delisted_observation(row), snapshot_date, str(run_id),
        ))
    if not payload:
        raise recovery.PublicationRecoveryRefused(
            "identity rebuild TICKERS snapshot contains no permanent SEP pairs")
    return payload


def verify_candidate(conn, *, run_id: str, plan: IdentityRebuildPlan,
                     rows: Iterable[Mapping]) -> list[Mapping]:
    """Re-prove the mutation and bind the exact stable TICKERS generation."""
    feed_store._assert_corpus_locked(conn)
    if load_plan(conn, run_id=run_id) != plan:
        raise recovery.PublicationRecoveryRefused(
            "in-memory identity rebuild plan differs from durable run evidence")
    material = _source_rows(rows)
    payload = _universe_payload(
        material, snapshot_date=plan.snapshot_date, run_id=run_id)
    try:
        universe.assert_candidate_listing_history_safe(conn, payload=payload)
    except universe.HistoricalIdentityMutation as exc:
        mutation_detail = str(exc)
    else:
        raise recovery.PublicationRecoveryRefused(
            "identity rebuild trigger disappeared on the replacement TICKERS "
            "observation; refusing a destructive rebuild without a reproducible "
            "historical identity mutation")

    observation = coherence.observe_tickers(material)
    addition = {
        "candidate_rows": int(observation.rows),
        "candidate_digest": observation.digest,
        "mutation_sha256": hashlib.sha256(
            mutation_detail.encode("utf-8")).hexdigest(),
        "mutation_detail": mutation_detail[:4000],
    }
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE feed_ingest_runs"
            " SET publication_recovery=publication_recovery || %s::jsonb,"
            " updated_at=NOW()"
            " WHERE run_id=%s AND status='running'"
            "   AND publication_recovery->>'schema'=%s",
            (json.dumps(addition, sort_keys=True), str(run_id), SCHEMA))
        changed = int(cur.rowcount)
    if changed != 1:
        raise recovery.PublicationRecoveryRefused(
            f"identity rebuild seed {run_id} lost its durable authorization")
    conn.commit()
    return material


def write_bars_claiming(conn, bars: Iterable, *, run_id: str,
                        batch_size: int = 0) -> int:
    """Replay bars while claiming unchanged published keys for this generation."""
    feed_store._assert_corpus_locked(conn)
    writer = str(run_id)
    size = int(batch_size or feed_store.WRITE_BATCH)
    rows: list[tuple] = []
    written = 0

    def flush() -> None:
        nonlocal written
        if not rows:
            return
        with conn.cursor() as cur:
            cur.executemany(feed_store._BAR_UPSERT, [row[:10] for row in rows])
            cur.executemany(
                "UPDATE sentinel_bars SET last_written_run_id=%s"
                " WHERE security_id=%s AND session=%s",
                [(writer, row[0], row[1]) for row in rows])
        conn.commit()
        written += len(rows)
        rows.clear()

    for item in bars:
        bar = getattr(item, "vendor", item)
        rows.append((
            bar.security_id, bar.session, bar.ticker,
            getattr(item, "close_signal", None),
            bar.raw_close, bar.raw_open, bar.volume, bar.split_ratio,
            bar.dividend_per_share, writer,
            getattr(item, "close_total_return", None),
        ))
        if len(rows) >= size:
            flush()
    flush()
    return written


def _candidate_evidence(conn, *, run_id: str,
                        rows: Sequence[Mapping]) -> tuple[IdentityRebuildPlan, dict]:
    status, payload = _load_payload(conn, run_id=run_id)
    if status != "running":
        raise recovery.PublicationRecoveryRefused(
            f"identity rebuild seed {run_id} is {status!r}, expected 'running'")
    plan = load_plan(conn, run_id=run_id)
    observation = coherence.observe_tickers(rows)
    if (int(payload.get("candidate_rows", -1)) != observation.rows
            or str(payload.get("candidate_digest") or "") != observation.digest):
        raise recovery.PublicationRecoveryRefused(
            "final TICKERS generation differs from the candidate bound before "
            "the SEP replay")
    return plan, payload


def _validate_bar_replacement(conn, *, run_id: str,
                              plan: IdentityRebuildPlan) -> int:
    writer = str(run_id)
    with conn.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*),MIN(session),MAX(session) FROM sentinel_bars"
            " WHERE last_written_run_id=%s", (writer,))
        count, lo, hi = cur.fetchone()
        cur.execute(
            "SELECT COUNT(*) FROM sentinel_bars"
            " WHERE last_written_run_id=%s"
            "   AND (session<%s OR session>%s)",
            (writer, plan.market_start, plan.market_end))
        outside = int(cur.fetchone()[0])
    if not int(count or 0):
        raise recovery.PublicationRecoveryRefused(
            "identity rebuild replay produced no candidate SEP bars")
    if outside:
        raise recovery.PublicationRecoveryRefused(
            f"identity rebuild run owns {outside} bar(s) outside its declared "
            f"range {plan.market_start}..{plan.market_end}")
    if str(lo) > plan.base_visible_start or str(hi) < plan.base_visible_end:
        raise recovery.PublicationRecoveryRefused(
            f"identity rebuild candidate coverage {lo}..{hi} does not span the "
            f"published boundary {plan.base_visible_start}..{plan.base_visible_end}")
    return int(count)


def _stage_candidate_universe(conn, *, run_id: str,
                              plan: IdentityRebuildPlan,
                              rows: Sequence[Mapping]) -> int:
    payload = _universe_payload(
        rows, snapshot_date=plan.snapshot_date, run_id=run_id)
    with conn.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) FROM sentinel_universe WHERE snapshot_date=%s",
            (plan.snapshot_date,))
        occupied = int(cur.fetchone()[0])
        if occupied:
            raise recovery.PublicationRecoveryRefused(
                f"identity rebuild snapshot date {plan.snapshot_date} acquired "
                f"{occupied} row(s) after authorization; refusing to overwrite "
                "immutable TICKERS evidence")
        cur.executemany(universe._UNIVERSE_UPSERT, payload)
    return len(payload)


def publish_completed_run(conn, *, run, rows: Sequence[Mapping],
                          plan: IdentityRebuildPlan):
    """Commit success, negative-space retirement and publication atomically."""
    feed_store._assert_corpus_locked(conn)
    writer = str(run.progress.run_id)
    durable_plan, payload = _candidate_evidence(conn, run_id=writer, rows=rows)
    if durable_plan != plan:
        raise recovery.PublicationRecoveryRefused(
            "identity rebuild finalizer received a plan different from its "
            "durable authorization")
    current = publication.require_current(conn)
    if current.version != plan.base_version:
        raise recovery.PublicationRecoveryRefused(
            f"identity rebuild was authorized against corpus v{plan.base_version} "
            f"but current authority is v{current.version}")

    candidate_bar_count = _validate_bar_replacement(
        conn, run_id=writer, plan=plan)
    try:
        candidate_universe_rows = _stage_candidate_universe(
            conn, run_id=writer, plan=plan, rows=rows)
        run.progress.rows_written += candidate_universe_rows
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE feed_ingest_runs SET status='success',completed_at=NOW(),"
                " updated_at=NOW(),chunks_done=%s,rows_written=%s,rows_dropped=%s,"
                " current_chunk=%s,error_message=NULL"
                " WHERE run_id=%s AND status='running'",
                (run.progress.chunks_done, run.progress.rows_written,
                 run.progress.rows_dropped, run.progress.current_chunk, writer))
            if int(cur.rowcount) != 1:
                raise recovery.PublicationRecoveryRefused(
                    f"identity rebuild seed {writer} is no longer RUNNING")

        retired_projection = universe_projection.retire_absent_from_run(
            conn, run_id=writer)
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM sentinel_bars"
                " WHERE session BETWEEN %s AND %s"
                "   AND last_written_run_id IS DISTINCT FROM %s::uuid",
                (plan.market_start, plan.market_end, writer))
            retired_bars = int(cur.rowcount)

        evidence = {
            "kind": run.progress.kind,
            "rows_written": run.progress.rows_written,
            "rows_dropped": run.progress.rows_dropped,
            "chunks": run.progress.chunks_done,
            "identity_rebuild": {
                **_plan_payload(plan),
                "candidate_rows": int(payload["candidate_rows"]),
                "candidate_digest": str(payload["candidate_digest"]),
                "mutation_sha256": str(payload["mutation_sha256"]),
                "candidate_universe_rows": candidate_universe_rows,
                "candidate_bars": candidate_bar_count,
                "retired_obsolete_bars": retired_bars,
                "retired_projection_pairs": retired_projection,
            },
        }
        return publication.publish(
            conn, run_id=writer, window_start=plan.market_start,
            window_end=plan.market_end, evidence=evidence)
    except BaseException as exc:                              # noqa: BLE001
        conn.rollback()
        run.finish("failed", f"identity rebuild publication failed: {exc}")
        raise


__all__ = [
    "IdentityRebuildPlan", "SCHEMA", "prepare", "publish_completed_run",
    "record_plan", "verify_candidate", "write_bars_claiming",
]
