"""Public post-seed coherence membrane.

Only production Sharadar snapshot seeds opt into this authority by durably
recording ``seed_coherence`` at run start. Injected/replay fetch seams do not
manufacture vendor-generation evidence and therefore remain non-certifying.
"""
from __future__ import annotations

import json

from sentinel.feed import _seed_coherence_impl as _base

for _name, _value in tuple(vars(_base).items()):
    if not _name.startswith("__") and _name != "reopen_successful_run":
        globals()[_name] = _value


def _durable_json(value):
    """Model PostgreSQL jsonb's value semantics, including alias separation."""
    return json.loads(json.dumps(value, sort_keys=True, default=str))


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
        raise SeedCoherenceRefused(
            f"run-backed publication {run_id} has no lifecycle row")
    if str(row[0]) != "seed":
        return None

    raw = row[4]
    recovery = raw if isinstance(raw, dict) else json.loads(raw or "{}")
    recovery = _durable_json(recovery)
    if not isinstance(recovery, dict) or "seed_coherence" not in recovery:
        # Explicit injected/replay seed seam: it never claimed production
        # generation authority and therefore contributes no #259 evidence.
        return None

    if str(row[1]) != "success":
        raise SeedCoherenceRefused(
            f"seed {run_id} is {row[1]!r}; only SUCCESS can publish")
    date_from, date_to = str(row[2]), str(row[3])
    if (str(window_start), str(window_end)) != (date_from, date_to):
        raise SeedCoherenceRefused(
            f"seed publication window {window_start}..{window_end} differs from "
            f"durable run window {date_from}..{date_to}")

    payload = recovery.get("seed_coherence")
    if not isinstance(payload, dict) or payload.get("schema") != SCHEMA:
        raise SeedCoherenceRefused(
            f"seed {run_id} lacks durable post-seed source/local coherence proof")
    required = {
        "schema", "phase", "run_id", "market_interval",
        "seed_start_update_boundary", "mutation_interval",
        "mutation_source_first", "mutation_source_second", "overlap",
        "normalized_source", "normalized_local", "final_mutation_cursor",
    }
    if not required.issubset(payload) or payload.get("phase") != "complete":
        raise SeedCoherenceRefused(
            f"seed {run_id} post-seed proof is incomplete")
    if (str(payload.get("run_id")) != str(run_id)
            or payload.get("market_interval") != [date_from, date_to]):
        raise SeedCoherenceRefused(
            f"seed {run_id} proof is bound to a different run/window")
    if payload.get("mutation_source_first") != payload.get("mutation_source_second"):
        raise SeedCoherenceRefused(
            f"seed {run_id} mutation source observations are not stable")
    overlap = payload.get("overlap")
    if (not isinstance(overlap, dict)
            or overlap.get("source_first") != overlap.get("source_second")):
        raise SeedCoherenceRefused(
            f"seed {run_id} trailing source observations are not stable")
    if payload.get("normalized_source") != payload.get("normalized_local"):
        raise SeedCoherenceRefused(
            f"seed {run_id} normalized source/local proof does not match")
    _base._strict_date(payload.get("final_mutation_cursor"),
                       label="final mutation cursor")
    return dict(payload)


# Intentionally omit ``reopen_successful_run``. #259 finalization must execute
# while the candidate is still RUNNING; reopening SUCCESS is not supported.
__all__ = [name for name in getattr(_base, "__all__", ())
           if name != "reopen_successful_run"]
