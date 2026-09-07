"""Bounded self-heal for stable Sharadar SEP local-only rows.

A current Sharadar traversal can legitimately retract a historical SEP row that
was previously published.  ``lastupdated`` cannot express absence, so ordinary
upsert maintenance leaves the old local row in place and complete reconciliation
fails on a local-only key.

This module repairs only that narrow negative-space case.  It independently
re-observes the exact source partition through the same normalization path,
requires every current source key/value to match the published corpus, bounds the
local-only set, proves removal cannot change the effective split chain, durably
records the exact keys, and retires them in the same transaction that publishes a
dedicated repair generation.  Missing local source rows, value drift, identity
drift, source instability, split-chain drift, or large key-set changes remain
fail-closed.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import uuid

from sentinel.feed import (
    authority,
    domains,
    publication,
    sep_reconciliation_impl as recon,
    sharadar,
    staging,
    store,
    universe,
)
from sentinel.feed.source_authority import CanonicalSourceFetch, SepUpdateEnvelope

SCHEMA = "sentinel.sep-negative-space-retirement/1"
KIND = "sep_source_retirement"
MAX_RETIREMENTS = 256
_TEMP_SOURCE_KEYS = "sentinel_sep_negative_space_source_keys"
_TEMP_RETIRE_KEYS = "sentinel_sep_negative_space_retire_keys"


class SepNegativeSpaceRefused(recon.SepKeysetDrift):
    """A key mismatch is not provably bounded current-source negative space."""


def _keys_digest(keys: list[dict]) -> str:
    payload = json.dumps(
        keys, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _assert_lossless_source_normalisation(report: domains.NormalisationReport) -> None:
    """A source row rejected by normalization can never become retirement proof."""
    if (report.dropped_no_identity or report.dropped_no_raw_close
            or report.rejections or report.rejections_truncated):
        raise SepNegativeSpaceRefused(
            "SEP retirement re-observation was not lossless: source rows were "
            "rejected during normalization, so source absence is unproved")


def _publication_committed_for_run(conn, run_id: str) -> bool:
    """Resolve durable publication state after a publish-path exception."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM sentinel_corpus_publications WHERE run_id=%s LIMIT 1",
            (str(run_id),))
        return cur.fetchone() is not None


def _create_source_table(conn) -> None:
    with conn.cursor() as cur:
        cur.execute(
            f"CREATE TEMP TABLE IF NOT EXISTS {_TEMP_SOURCE_KEYS} ("
            " security_id TEXT NOT NULL, session DATE NOT NULL, ticker TEXT NOT NULL,"
            " PRIMARY KEY(security_id,session,ticker)) ON COMMIT PRESERVE ROWS")
        cur.execute(f"TRUNCATE {_TEMP_SOURCE_KEYS}")


def _load_retire_table(conn, keys: list[dict]) -> None:
    with conn.cursor() as cur:
        cur.execute(
            f"CREATE TEMP TABLE IF NOT EXISTS {_TEMP_RETIRE_KEYS} ("
            " security_id TEXT NOT NULL, session DATE NOT NULL, ticker TEXT NOT NULL,"
            " PRIMARY KEY(security_id,session,ticker)) ON COMMIT PRESERVE ROWS")
        cur.execute(f"TRUNCATE {_TEMP_RETIRE_KEYS}")
        cur.executemany(
            f"INSERT INTO {_TEMP_RETIRE_KEYS}(security_id,session,ticker)"
            " VALUES (%s,%s,%s)",
            [(k["security_id"], k["session"], k["ticker"]) for k in keys])


def _drop_temp(conn, table: str) -> None:
    try:
        with conn.cursor() as cur:
            cur.execute(f"DROP TABLE IF EXISTS {table}")
    except Exception:  # pragma: no cover - cleanup cannot replace authority error
        pass


def _source_proof_and_keys(
        conn, *, fetch, start: str, end: str,
        observation_ceiling: dt.date) -> recon._PartitionProof:
    guarded = CanonicalSourceFetch(
        fetch, sep_update_envelope=SepUpdateEnvelope.through(
            observation_ceiling,
            context="SEP negative-space retirement re-observation"))
    stable = authority.StableSharadarFetch(guarded, after_session=end)
    rows = stable(sharadar.SEP, sharadar.date_params(start, end))

    max_updated: dt.date | None = None

    def tracking_rows():
        nonlocal max_updated
        for row in rows:
            raw = row.get("lastupdated")
            if raw not in (None, ""):
                try:
                    observed = dt.date.fromisoformat(str(raw))
                except ValueError as exc:
                    raise SepNegativeSpaceRefused(
                        f"SEP {row.get('ticker')}/{row.get('date')} has invalid "
                        f"lastupdated {raw!r}") from exc
                if observed > observation_ceiling:
                    raise SepNegativeSpaceRefused(
                        f"SEP {row.get('ticker')}/{row.get('date')} lastupdated "
                        f"{observed} exceeds retirement observation ceiling "
                        f"{observation_ceiling}")
                if max_updated is None or observed > max_updated:
                    max_updated = observed
            yield row

    scratch = str(uuid.uuid4())
    chunk = f"sep-negative-space-{start}-{end}"
    staging.stage(conn, tracking_rows(), run_id=scratch, chunk=chunk)
    try:
        report = domains.NormalisationReport()
        normalised = domains.normalise_sep_rows(
            staging.staged(conn, run_id=scratch, chunk=chunk),
            resolve_identity=universe.load_resolver(conn).resolve,
            prior_observations=store.previous_observations(conn, start),
            report=report)
        key_fp = recon._Fingerprint()
        value_fp = recon._ValueFingerprint()
        batch: list[tuple[str, str, str]] = []
        for item in normalised:
            bar = item.vendor
            sid, session, ticker = (
                str(bar.security_id), str(bar.session), str(bar.ticker))
            key_fp.add(sid, session, ticker)
            value_fp.add(
                sid, session, ticker, item.close_signal,
                bar.raw_close, bar.raw_open, bar.volume)
            batch.append((sid, session, ticker))
            if len(batch) >= 5000:
                with conn.cursor() as cur:
                    cur.executemany(
                        f"INSERT INTO {_TEMP_SOURCE_KEYS}"
                        " (security_id,session,ticker) VALUES (%s,%s,%s)"
                        " ON CONFLICT DO NOTHING", batch)
                batch.clear()
        if batch:
            with conn.cursor() as cur:
                cur.executemany(
                    f"INSERT INTO {_TEMP_SOURCE_KEYS}"
                    " (security_id,session,ticker) VALUES (%s,%s,%s)"
                    " ON CONFLICT DO NOTHING", batch)
        _assert_lossless_source_normalisation(report)
        if key_fp.rows != value_fp.rows:
            raise AssertionError("SEP negative-space source key/value counts diverged")
        return recon._PartitionProof(
            rows=key_fp.rows, key_digest=key_fp.digest(),
            value_digest=value_fp.digest(), max_lastupdated=max_updated)
    finally:
        staging.clear(conn, run_id=scratch, chunk=chunk)


def _source_only_local_proof(conn, *, start: str, end: str) -> recon._PartitionProof:
    key_fp = recon._Fingerprint()
    value_fp = recon._ValueFingerprint()
    sql = (
        "SELECT b.security_id,b.session,b.ticker,b.close_signal,"
        " b.close_unadjusted,b.open_unadjusted,b.volume"
        " FROM sentinel_bars b"
        " WHERE b.session BETWEEN %s AND %s"
        "   AND " + publication.visible_predicate("b") +
        f"   AND EXISTS (SELECT 1 FROM {_TEMP_SOURCE_KEYS} s"
        "       WHERE s.security_id=b.security_id AND s.session=b.session"
        "         AND s.ticker=b.ticker)"
        " ORDER BY b.session,b.security_id")
    with store.streaming_cursor(conn, sql, (start, end)) as cur:
        for sid, session, ticker, close_signal, raw_close, raw_open, volume in cur:
            key_fp.add(sid, session, ticker)
            value_fp.add(
                sid, session, ticker, close_signal, raw_close, raw_open, volume)
    return recon._PartitionProof(
        rows=key_fp.rows, key_digest=key_fp.digest(),
        value_digest=value_fp.digest(), max_lastupdated=None)


def _local_only_keys(conn, *, start: str, end: str) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT b.security_id,b.session,b.ticker FROM sentinel_bars b"
            " WHERE b.session BETWEEN %s AND %s"
            "   AND " + publication.visible_predicate("b") +
            f"   AND NOT EXISTS (SELECT 1 FROM {_TEMP_SOURCE_KEYS} s"
            "       WHERE s.security_id=b.security_id AND s.session=b.session"
            "         AND s.ticker=b.ticker)"
            " ORDER BY b.session,b.security_id,b.ticker LIMIT %s",
            (start, end, MAX_RETIREMENTS + 1))
        rows = list(cur.fetchall())
    if not rows:
        raise SepNegativeSpaceRefused(
            "SEP key-set mismatch has no exact local-only negative-space rows")
    if len(rows) > MAX_RETIREMENTS:
        raise SepNegativeSpaceRefused(
            "SEP local-only negative-space drift exceeds bounded automatic "
            f"retirement cap {MAX_RETIREMENTS}")
    return [{
        "security_id": str(sid),
        "session": str(session),
        "ticker": str(ticker),
    } for sid, session, ticker in rows]


def _bridge_split_ratio(prev_row, next_row) -> float:
    """Split ratio the next surviving bar needs after retirement."""
    if prev_row is None:
        return 1.0
    return domains.split_ratio_from_domains(
        prev_row[0], prev_row[1], next_row[0], next_row[1])


def _assert_retirement_preserves_split_chain(conn, keys: list[dict]) -> None:
    """Refuse deletion when it would change any next surviving split edge.

    Split ratios are path-dependent: removing B from A->B->C can change the
    ratio that C must carry even when every persisted price/volume field on A/C
    still matches source.  Inspect the nearest surviving predecessor and
    successor across the complete published corpus, so a successor just beyond
    the reconciliation partition cannot escape this proof.
    """
    effective = publication.effective_split_ratio("b")
    visible = publication.visible_predicate("b")
    for key in keys:
        sid, session = key["security_id"], key["session"]
        with conn.cursor() as cur:
            cur.execute(
                "SELECT b.close_signal,b.close_unadjusted FROM sentinel_bars b"
                " WHERE b.security_id=%s AND b.session<%s AND " + visible +
                f" AND NOT EXISTS (SELECT 1 FROM {_TEMP_RETIRE_KEYS} r"
                "  WHERE r.security_id=b.security_id AND r.session=b.session"
                "    AND r.ticker=b.ticker)"
                " ORDER BY b.session DESC LIMIT 1",
                (sid, session))
            prev_row = cur.fetchone()
            cur.execute(
                "SELECT b.close_signal,b.close_unadjusted," + effective +
                " FROM sentinel_bars b"
                " WHERE b.security_id=%s AND b.session>%s AND " + visible +
                f" AND NOT EXISTS (SELECT 1 FROM {_TEMP_RETIRE_KEYS} r"
                "  WHERE r.security_id=b.security_id AND r.session=b.session"
                "    AND r.ticker=b.ticker)"
                " ORDER BY b.session ASC LIMIT 1",
                (sid, session))
            next_row = cur.fetchone()
        if next_row is None:
            continue
        required = _bridge_split_ratio(prev_row, next_row)
        effective_next = float(next_row[2] or 1.0)
        if abs(float(required) - effective_next) > 1e-12:
            raise SepNegativeSpaceRefused(
                "SEP retirement would change the effective split chain for "
                f"{sid} after {session}: surviving successor requires split "
                f"ratio {required:g}, published ratio is {effective_next:g}")


def _plan(*, start: str, end: str, source: recon._PartitionProof,
          expected_source: recon._PartitionProof, keys: list[dict]) -> dict:
    return {
        "schema": SCHEMA,
        "interval": [str(start), str(end)],
        "count": len(keys),
        "keys": keys,
        "keys_sha256": _keys_digest(keys),
        "source_rows": int(source.rows),
        "source_key_sha256": str(source.key_digest),
        "source_value_sha256": str(source.value_digest),
        "detected_source_key_sha256": str(expected_source.key_digest),
        "detected_source_value_sha256": str(expected_source.value_digest),
    }


def _persist_plan(conn, *, run_id: str, plan: dict) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE feed_ingest_runs SET publication_recovery=%s::jsonb,"
            " updated_at=NOW() WHERE run_id=%s AND kind=%s AND status='running'",
            (json.dumps(plan, sort_keys=True), str(run_id), KIND))
        changed = int(cur.rowcount)
    if changed != 1:
        conn.rollback()
        raise SepNegativeSpaceRefused(
            f"SEP retirement run {run_id} lost RUNNING authority before plan save")
    conn.commit()


def _retire_and_publish(conn, *, run, plan: dict):
    keys = list(plan["keys"])
    _load_retire_table(conn, keys)
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT COUNT(*) FROM sentinel_bars b JOIN {_TEMP_RETIRE_KEYS} r"
            " ON r.security_id=b.security_id AND r.session=b.session"
            " AND r.ticker=b.ticker WHERE " + publication.visible_predicate("b"))
        matched = int(cur.fetchone()[0])
        if matched != len(keys):
            raise SepNegativeSpaceRefused(
                "SEP retirement target changed after durable source proof; "
                f"expected {len(keys)} rows, found {matched}")
        cur.execute(
            f"DELETE FROM sentinel_bars b USING {_TEMP_RETIRE_KEYS} r"
            " WHERE b.security_id=r.security_id AND b.session=r.session"
            "   AND b.ticker=r.ticker")
        if int(cur.rowcount) != len(keys):
            raise SepNegativeSpaceRefused(
                "SEP retirement delete was not exact; refusing publication")
        cur.execute(
            "UPDATE feed_ingest_runs SET status='success',chunks_done=1,"
            " rows_dropped=%s,current_chunk='retire-local-only',"
            " completed_at=NOW(),updated_at=NOW() WHERE run_id=%s"
            " AND kind=%s AND status='running'",
            (len(keys), str(run.progress.run_id), KIND))
        if int(cur.rowcount) != 1:
            raise SepNegativeSpaceRefused(
                "SEP retirement run lost RUNNING state before publication")
    return publication.publish(
        conn, run_id=str(run.progress.run_id),
        window_start=plan["interval"][0], window_end=plan["interval"][1],
        evidence={"kind": KIND, "source_retirement": plan})


def repair_local_only(
        conn, *, fetch, start: str, end: str, observation_ceiling,
        expected_source: recon._PartitionProof):
    """Retire a bounded exact local-only set and publish it atomically."""
    store._assert_corpus_locked(conn)
    ceiling = (
        observation_ceiling if isinstance(observation_ceiling, dt.date)
        else dt.date.fromisoformat(str(observation_ceiling)))
    _create_source_table(conn)
    try:
        source = _source_proof_and_keys(
            conn, fetch=fetch, start=start, end=end,
            observation_ceiling=ceiling)
        if (source.rows != expected_source.rows
                or source.key_digest != expected_source.key_digest
                or source.value_digest != expected_source.value_digest):
            raise SepNegativeSpaceRefused(
                "SEP source changed between mismatch detection and bounded "
                "retirement re-observation")
        local_source = _source_only_local_proof(conn, start=start, end=end)
        if (local_source.rows != source.rows
                or local_source.key_digest != source.key_digest):
            raise SepNegativeSpaceRefused(
                "current SEP source contains keys absent from published local state; "
                "automatic negative-space retirement cannot repair insertion or "
                "identity drift")
        if local_source.value_digest != source.value_digest:
            raise SepNegativeSpaceRefused(
                "current SEP source values disagree with published local values; "
                "automatic negative-space retirement cannot repair value drift")
        keys = _local_only_keys(conn, start=start, end=end)
        if len(keys) != int(recon._local_fingerprint(
                conn, start=start, end=end).rows - source.rows):
            raise SepNegativeSpaceRefused(
                "SEP local-only row count changed during retirement planning")
        _load_retire_table(conn, keys)
        _assert_retirement_preserves_split_chain(conn, keys)
        plan = _plan(
            start=start, end=end, source=source,
            expected_source=expected_source, keys=keys)
        run = store.IngestRun(
            conn, KIND, date_from=start, date_to=end, chunks_total=1)
        run_id = str(run.progress.run_id)
        _persist_plan(conn, run_id=run_id, plan=plan)
        try:
            published = _retire_and_publish(conn, run=run, plan=plan)
        except BaseException as exc:  # noqa: BLE001
            conn.rollback()
            if not _publication_committed_for_run(conn, run_id):
                run.finish("failed", f"{type(exc).__name__}: {exc}")
            raise
        return {"publication": published, "plan": plan}
    finally:
        _drop_temp(conn, _TEMP_SOURCE_KEYS)
        _drop_temp(conn, _TEMP_RETIRE_KEYS)


__all__ = [
    "KIND", "MAX_RETIREMENTS", "SCHEMA", "SepNegativeSpaceRefused",
    "repair_local_only",
]
