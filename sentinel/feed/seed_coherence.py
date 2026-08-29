"""Public post-seed coherence membrane.

Only production Sharadar snapshot seeds opt into this authority by durably
recording ``seed_coherence`` at run start. Injected/replay fetch seams do not
manufacture vendor-generation evidence and therefore remain non-certifying.
"""
from __future__ import annotations

import json

from sentinel.feed import _seed_coherence_impl as _core
from sentinel.feed._seed_coherence_impl import (
    SCHEMA,
    START_SCHEMA,
    SeedCoherenceProof,
    SeedCoherenceRefused,
    capture_update_boundary,
    capture_update_ceiling,
    load,
    prove,
    record_start_boundary,
)

# Explicit static seam retained for deterministic mutation-boundary tests.
_observe_mutations = _core._observe_mutations


def _durable_json(value):
    """Model PostgreSQL jsonb's value semantics, including alias separation."""
    return json.loads(json.dumps(value, sort_keys=True, default=str))


def record_seed_coverage(conn, *, run_id: str, evidence: dict) -> None:
    """Persist successful exact SEP membership/category accounting evidence."""
    payload = _durable_json(evidence)
    if (not isinstance(payload, dict)
            or payload.get("schema") != "sentinel.seed-source-coverage/1"
            or payload.get("missing_eligible_total") != 0
            or payload.get("unexpected_eligible_total") != 0
            or payload.get("unresolved_eligible_risk_total") != 0):
        raise _core.SeedCoherenceRefused(
            f"seed {run_id} coverage evidence is absent or not an exact pass")
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE feed_ingest_runs"
            " SET publication_recovery=jsonb_set("
            "   publication_recovery,'{seed_coverage}',%s::jsonb,true),"
            " updated_at=NOW()"
            " WHERE run_id=%s AND kind='seed' AND status='running'"
            "   AND NOT EXISTS (SELECT 1 FROM sentinel_corpus_publications p"
            "                   WHERE p.run_id=feed_ingest_runs.run_id)",
            (json.dumps(payload, sort_keys=True), str(run_id)))
        changed = int(cur.rowcount)
    if changed != 1:
        conn.rollback()
        raise _core.SeedCoherenceRefused(
            f"seed {run_id} lost unpublished RUNNING authority before coverage save")
    conn.commit()


def require_for_publication(conn, *, run_id: str, window_start=None,
                            window_end=None):
    """Validate a production seed proof; injected non-authority seeds return None.

    Once a ``seed_coherence`` marker exists, the value is treated exactly as a
    durable JSON document and must be a complete proof. This deliberately avoids
    Python object-identity/aliasing semantics that cannot exist after jsonb
    persistence and could otherwise mask mismatched observations in tests.
    """
    with conn.cursor() as cur:
        cur.execute(
            "SELECT kind,status,date_from,date_to,publication_recovery"
            " FROM feed_ingest_runs WHERE run_id=%s",
            (str(run_id),))
        row = cur.fetchone()
    if row is None:
        raise _core.SeedCoherenceRefused(
            f"run-backed publication {run_id} has no lifecycle row")
    if str(row[0]) != "seed":
        return None

    raw = row[4]
    recovery = raw if isinstance(raw, dict) else json.loads(raw or "{}")
    recovery = _durable_json(recovery)
    if not isinstance(recovery, dict) or "seed_coherence" not in recovery:
        return None

    if str(row[1]) != "success":
        raise _core.SeedCoherenceRefused(
            f"seed {run_id} is {row[1]!r}; only SUCCESS can publish")
    date_from, date_to = str(row[2]), str(row[3])
    if (str(window_start), str(window_end)) != (date_from, date_to):
        raise _core.SeedCoherenceRefused(
            f"seed publication window {window_start}..{window_end} differs from "
            f"durable run window {date_from}..{date_to}")

    coverage = recovery.get("seed_coverage")
    if coverage is not None:
        if (not isinstance(coverage, dict)
                or coverage.get("schema") != "sentinel.seed-source-coverage/1"
                or coverage.get("interval") != [date_from, date_to]
                or coverage.get("missing_eligible_total") != 0
                or coverage.get("unexpected_eligible_total") != 0
                or coverage.get("unresolved_eligible_risk_total") != 0):
            raise _core.SeedCoherenceRefused(
                f"seed {run_id} retained source coverage evidence is invalid")

    payload = recovery.get("seed_coherence")
    if not isinstance(payload, dict) or payload.get("schema") != _core.SCHEMA:
        raise _core.SeedCoherenceRefused(
            f"seed {run_id} lacks durable post-seed source/local coherence proof")
    required = {
        "schema", "phase", "run_id", "market_interval",
        "seed_start_update_boundary", "mutation_interval",
        "mutation_source_first", "mutation_source_second", "overlap",
        "normalized_source", "normalized_local", "final_mutation_cursor",
    }
    if not required.issubset(payload) or payload.get("phase") != "complete":
        raise _core.SeedCoherenceRefused(
            f"seed {run_id} post-seed proof is incomplete")
    if (str(payload.get("run_id")) != str(run_id)
            or payload.get("market_interval") != [date_from, date_to]):
        raise _core.SeedCoherenceRefused(
            f"seed {run_id} proof is bound to a different run/window")
    if payload.get("mutation_source_first") != payload.get("mutation_source_second"):
        raise _core.SeedCoherenceRefused(
            f"seed {run_id} mutation source observations are not stable")
    overlap = payload.get("overlap")
    if (not isinstance(overlap, dict)
            or overlap.get("source_first") != overlap.get("source_second")):
        raise _core.SeedCoherenceRefused(
            f"seed {run_id} trailing source observations are not stable")
    if payload.get("normalized_source") != payload.get("normalized_local"):
        raise _core.SeedCoherenceRefused(
            f"seed {run_id} normalized source/local proof does not match")
    _core._strict_date(payload.get("final_mutation_cursor"),
                       label="final mutation cursor")
    return dict(payload)


__all__ = [
    "SCHEMA", "START_SCHEMA", "SeedCoherenceProof", "SeedCoherenceRefused",
    "capture_update_boundary", "capture_update_ceiling", "load", "prove",
    "record_seed_coverage", "record_start_boundary", "require_for_publication",
]
