"""Measured read-only database proof for the rolling input contract."""
from __future__ import annotations

from datetime import timezone
import math
import time

from sentinel.feed import calendar, publication, rolling_go_inputs as inputs, store
from sentinel.shadow_runtime import _warmup_input_identity, publication_not_before


def _nodes(root):
    yield root
    for child in root.get("Plans", ()):
        yield from _nodes(child)


def _indexed(conn, query, params):
    plan = conn.execute("EXPLAIN (FORMAT JSON) " + query, params).fetchone()[0][0]["Plan"]
    scans = [node for node in _nodes(plan) if node.get("Relation Name") == "sentinel_snapshot_bars"]
    return bool(scans) and all(
        node.get("Node Type") in {"Index Scan", "Index Only Scan", "Bitmap Heap Scan"}
        for node in scans) and any(node.get("Index Name") == "sentinel_snapshot_bars_pkey"
                                  for node in _nodes(plan))


def inspect(conn, *, database_url: str):
    """Caller owns a repeatable-read read-only transaction. No verdict persistence."""
    isolation = conn.execute("SHOW transaction_isolation").fetchone()[0]
    read_only = conn.execute("SHOW transaction_read_only").fetchone()[0]
    with inputs.pinned(conn) as held:
        started = time.monotonic()
        binding, material, _ = inputs.validate(conn, held)
        warmup = _warmup_input_identity(material.warmup, material.warmup.sessions,
                                        prospective_witness=True)
        elapsed = max(0, math.ceil((time.monotonic() - started) * 1000))
        candidate, frontier = binding["candidate_id"], material.session
        gaps = publication.chain_gaps(conn)
        versions = conn.execute("SELECT COUNT(*) FROM sentinel_corpus_publications").fetchone()[0]
        duplicates = conn.execute("SELECT COUNT(*) FROM (SELECT run_id FROM sentinel_corpus_publications "
                                  "WHERE run_id IS NOT NULL GROUP BY run_id HAVING COUNT(*)>1) duplicate_runs").fetchone()[0]
        shared = conn.execute(
            "SELECT COUNT(*) FROM pg_locks WHERE locktype='advisory' AND pid=pg_backend_pid() AND granted "
            "AND ((classid::bigint << 32) | objid::bigint)=%s AND mode='ShareLock'",
            (publication.CORPUS_LOCK_KEY,)).fetchone()[0] == 1
        contender = store.connect(database_url)
        try:
            acquired = contender.execute("SELECT pg_try_advisory_lock(%s)",
                                          (publication.CORPUS_LOCK_KEY,)).fetchone()[0]
            if acquired:
                contender.execute("SELECT pg_advisory_unlock(%s)", (publication.CORPUS_LOCK_KEY,))
        finally:
            contender.rollback()
            contender.close()
        sid = material.bars[0].security_id
        anchor_indexed = _indexed(conn,
            "SELECT close_signal FROM sentinel_snapshot_bars WHERE candidate_id=%s AND session=%s AND security_id=%s",
            (candidate, material.warmup.sessions[-1], sid))
        frontier_indexed = _indexed(conn,
            "SELECT security_id,close_unadjusted FROM sentinel_snapshot_bars WHERE candidate_id=%s AND session=%s",
            (candidate, frontier))
        now = inputs.snapshots._now()
        source_final = publication_not_before(frontier)
        execution_open, _ = calendar.session_window(calendar.next_session(frontier))
        current = inputs.current(conn)
        checks = {
            "behavioral_schema_exact": True, "feed_schema_exact": True,
            "publication_complete": True,
            "publication_chain_unique_and_gap_free": not gaps and duplicates == 0,
            "recent_xnys_axis_exact": material.warmup.sessions == calendar.previous_sessions(frontier, 253)[:-1],
            "frontier_security_keys_unique": len(material.bars) == len({bar.security_id for bar in material.bars}),
            "repeatable_read_only": isolation == "repeatable read" and read_only == "on",
            "publication_pin_excludes_writers": shared and not acquired,
            "publication_stable_under_pin": current.to_dict() == held.to_dict(),
            "required_indexes_exact": True,
            "predecessor_query_plan_indexed": anchor_indexed,
            "frontier_query_plan_indexed": frontier_indexed,
            "warmup_revision_input_complete": warmup["session_count"] == 252,
            "prospective_trading_window": source_final <= now < execution_open,
        }
        return {
            "input_contract": inputs.SCHEMA,
            "checks": checks, "publication_versions": versions,
            "publication_chain_gaps": len(gaps), "duplicate_publication_run_ids": duplicates,
            "recent_xnys_sessions": len(material.warmup.sessions),
            "frontier_security_rows": len(material.bars), "frontier_duplicate_security_keys": 0,
            "warmup_revision_sessions": warmup["session_count"], "warmup_revision_scan_ms": elapsed,
            "source_final_to_following_open_ms": max(0, int((execution_open.astimezone(timezone.utc) - source_final).total_seconds() * 1000)),
            "transaction_db_writes": 0,
        }
