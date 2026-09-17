"""Incremental maintenance. Owns an idle connection; failures only retain data."""
import logging

from sentinel.feed import rolling_jobs, rolling_store, store
from sentinel.feed.rolling_contract import canonical_json

log = logging.getLogger(__name__)
BATCH_ROWS = rolling_store.BATCH_SIZE


def _pass(conn, *, batch_rows):
    from sentinel import rolling_checkpoint, rolling_daily_checkpoint
    # Authenticate the current restart dependency before releasing any payload.
    if conn.execute("SELECT to_regclass('sentinel_processed_sessions')").fetchone()[0]:
        rolling_checkpoint.read(conn)
        rolling_daily_checkpoint.read(conn)
    for (job,) in conn.execute("SELECT job_id FROM sentinel_snapshot_jobs WHERE deadline<=clock_timestamp() "
        "AND state NOT IN ('REFUSED','ABORTED','PUBLISHED') AND reason<>'COMPARISON_ONLY' "
        "ORDER BY deadline LIMIT 32 FOR UPDATE SKIP LOCKED").fetchall():
        rolling_jobs.expire(conn, str(job))
    # Lock ordering is job -> candidate, as in workers. Shared generation reads
    # hold the corpus transaction pin and make this pass retry safely.
    previous = conn.execute("SELECT diagnostic->>'scan_cursor' FROM sentinel_snapshot_maintenance WHERE id").fetchone()
    cursor = previous[0] if previous else None
    rows = conn.execute("SELECT c.candidate_id,sentinel_snapshot_pins(c.candidate_id) "
        "FROM sentinel_price_candidates c WHERE NOT EXISTS "
        "(SELECT 1 FROM sentinel_snapshot_retirements r WHERE r.candidate_id=c.candidate_id) "
        "AND (%s::uuid IS NULL OR c.candidate_id>%s::uuid) "
        "ORDER BY c.candidate_id LIMIT 32", (cursor, cursor)).fetchall()
    if len(rows) < 32 and cursor:
        rows += conn.execute("SELECT c.candidate_id,sentinel_snapshot_pins(c.candidate_id) "
            "FROM sentinel_price_candidates c WHERE NOT EXISTS "
            "(SELECT 1 FROM sentinel_snapshot_retirements r WHERE r.candidate_id=c.candidate_id) "
            "AND c.candidate_id<=%s::uuid ORDER BY c.candidate_id LIMIT %s", (cursor, 32 - len(rows))).fetchall()
    retained = {str(cid): pins for cid, pins in rows if pins}
    scanned = None
    retired_candidate = None
    for cid, pins in rows:
        scanned = str(cid)
        if not pins:
            conn.execute("INSERT INTO sentinel_snapshot_retirements(candidate_id) VALUES(%s) ON CONFLICT DO NOTHING", (cid,))
            retired_candidate = str(cid)
            break
    row = conn.execute("SELECT r.candidate_id FROM sentinel_snapshot_retirements r WHERE "
        "EXISTS(SELECT 1 FROM sentinel_snapshot_bars b WHERE b.candidate_id=r.candidate_id) "
        "OR EXISTS(SELECT 1 FROM sentinel_snapshot_benchmarks b WHERE b.candidate_id=r.candidate_id) "
        "ORDER BY retired_at,candidate_id LIMIT 1").fetchone()
    deleted = 0
    candidate = str(row[0]) if row else None
    if candidate:
        for table in ("sentinel_snapshot_bars", "sentinel_snapshot_benchmarks"):
            result = conn.execute(f"DELETE FROM {table} WHERE ctid IN "
                f"(SELECT ctid FROM {table} WHERE candidate_id=%s LIMIT %s)", (candidate, batch_rows - deleted))
            deleted += result.rowcount
    # The table lock closes reference creation vs payload release. It is short,
    # bounded by lock_timeout, and never surrounds acquisition or normalization.
    conn.execute("LOCK TABLE sentinel_price_candidates IN SHARE ROW EXCLUSIVE MODE")
    evidence = conn.execute("SELECT DISTINCT e.evidence_sha256 FROM sentinel_snapshot_evidence e "
        "JOIN sentinel_price_candidates c ON e.evidence_sha256 IN (c.reference_sha256,c.source_evidence_sha256) "
        "JOIN sentinel_snapshot_retirements r USING(candidate_id) WHERE e.payload IS NOT NULL "
        "AND NOT EXISTS(SELECT 1 FROM sentinel_price_candidates live WHERE "
        "e.evidence_sha256 IN (live.reference_sha256,live.source_evidence_sha256) AND NOT EXISTS "
        "(SELECT 1 FROM sentinel_snapshot_retirements gone WHERE gone.candidate_id=live.candidate_id)) "
        "AND NOT EXISTS(SELECT 1 FROM sentinel_snapshot_validations WHERE validation_sha256=e.evidence_sha256) "
        "AND NOT EXISTS(SELECT 1 FROM sentinel_operational_snapshot_validations WHERE validation_sha256=e.evidence_sha256) "
        "AND NOT EXISTS(SELECT 1 FROM sentinel_snapshot_comparisons WHERE producer_sha256=e.evidence_sha256) "
        "LIMIT 32").fetchall()
    for (sha,) in evidence:
        conn.execute("UPDATE sentinel_snapshot_evidence SET payload=NULL WHERE evidence_sha256=%s", (sha,))
    # Scratch ownership is recorded at claim, so a reclaimed worker's remnants
    # can be retired without guessing which UUID belongs to a live operation.
    scratch = conn.execute("DELETE FROM sentinel_sep_staging WHERE ctid IN "
        "(SELECT s.ctid FROM sentinel_sep_staging s JOIN sentinel_snapshot_workers w ON w.owner=s.run_id "
        "JOIN sentinel_snapshot_jobs j USING(job_id) WHERE j.owner IS DISTINCT FROM w.owner "
        "AND j.state IN ('REFUSED','ABORTED','PUBLISHED') LIMIT %s)", (batch_rows,)).rowcount
    return dict(status="COMPLETE", candidate_id=candidate, deleted_rows=deleted,
                released_evidence=len(evidence), deleted_scratch_rows=scratch,
                retired_candidate_id=retired_candidate, retired_count=int(retired_candidate is not None),
                retained=retained, retained_count=len(retained), scan_cursor=scanned,
                more_work=bool(deleted or retired_candidate or len(rows) == 32 or evidence or scratch))


def maintain(conn, *, batch_rows=BATCH_ROWS):
    """One bounded pass, best effort. Never commit someone else's transaction."""
    from sentinel.execution.journal import writer_lock
    if conn.info.transaction_status.value != 0:
        raise RuntimeError("retention requires an idle connection")
    if not 1 <= batch_rows <= 50000:
        raise ValueError("retention batch must be in 1..50000")
    try:
        with writer_lock(conn), store.corpus_write_lock(conn):
            conn.execute("SET LOCAL lock_timeout='250ms'")
            conn.execute("SET LOCAL statement_timeout='5s'")
            result = _pass(conn, batch_rows=batch_rows)
            conn.commit()
    except Exception as exc:
        conn.rollback()
        result = dict(status="RETRY", reason=type(exc).__name__)
        log.warning("rolling maintenance deferred: %s", type(exc).__name__)
    try:
        conn.execute("INSERT INTO sentinel_snapshot_maintenance(id,diagnostic) VALUES(TRUE,%s::jsonb) "
            "ON CONFLICT(id) DO UPDATE SET updated_at=clock_timestamp(),diagnostic=EXCLUDED.diagnostic",
            (canonical_json(result),))
        conn.commit()
    except Exception:
        conn.rollback()
        log.warning("rolling maintenance diagnostics unavailable; retry next wake")
    return result


def idle_pass(database_url):
    """Drain one batch during the broker-free service's existing idle wake."""
    conn = None
    try:
        conn = store.connect(database_url)
        available = conn.execute("SELECT to_regclass('sentinel_operational_snapshots')").fetchone()[0]
        if not available or not conn.execute('SELECT 1 FROM sentinel_operational_snapshots LIMIT 1').fetchone():
            return False
        conn.rollback()
        result = maintain(conn)
        return result['status'] == 'COMPLETE' and result['more_work']
    except Exception as exc:
        log.warning('rolling idle maintenance deferred: %s', type(exc).__name__)
        return False
    finally:
        if conn is not None:
            conn.close()
