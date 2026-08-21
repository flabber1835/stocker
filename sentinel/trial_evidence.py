"""Append-only per-session strategy evidence for the forward paper trial.

This is observability, never strategy authority.  It records the canonical
SessionState that has already been computed; no value from this table is read
back into Wealth Core, Sentinel, Concordance, projection or execution.
"""
from __future__ import annotations

import hashlib
import json
from typing import Mapping


class TrialEvidenceConflict(RuntimeError):
    """A session already has different retained strategy evidence."""


def _canonical_bytes(value) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def _hash(value) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _canonical_production_state(state):
    if not isinstance(state, Mapping):
        return None
    try:
        # Lazy import avoids making the generic catch-up coordinator depend on
        # production at module load time.  A generic test/research seam that is
        # merely JSON-serialisable is intentionally not trial evidence.
        from sentinel.core.production import SessionState
        return SessionState.from_dict(state)
    except (KeyError, TypeError, ValueError):
        return None


def record_strategy_session(conn, *, session: str, state) -> bool:
    """Retain one canonical production strategy close without committing.

    Identical replay is idempotent. A different payload for an already-retained
    session is corruption and refuses the surrounding transaction. PostgreSQL
    additionally rejects UPDATE/DELETE so application bugs cannot rewrite the
    historical explanation later.
    """
    canonical = _canonical_production_state(state)
    if canonical is None:
        return False
    if canonical.last_processed_session != session:
        raise TrialEvidenceConflict(
            "canonical strategy state session differs from evidence session")
    if canonical.data_version is None:
        raise TrialEvidenceConflict(
            "canonical strategy state has no publication data_version")
    if not isinstance(canonical.last_decision, Mapping):
        raise TrialEvidenceConflict(
            "canonical strategy state has no decision evidence")
    if not isinstance(canonical.last_evidence, Mapping):
        raise TrialEvidenceConflict(
            "canonical strategy state has no observation evidence")

    payload = {
        "session": session,
        "data_version": int(canonical.data_version),
        "state_sha256": canonical.state_hash,
        "strategy_identity": canonical.strategy_identity,
        "decision": canonical.last_decision,
        "evidence": canonical.last_evidence,
        "recent_leadership": canonical.recent_leadership,
        "ldrc": canonical.ldrc,
    }
    payload_sha256 = _hash(payload)
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO sentinel_trial_strategy_evidence "
            "(session,data_version,state_sha256,strategy_identity,decision,"
            " evidence,recent_leadership,ldrc,payload_sha256) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) "
            "ON CONFLICT (session) DO NOTHING",
            (session, payload["data_version"], payload["state_sha256"],
             json.dumps(payload["strategy_identity"], sort_keys=True),
             json.dumps(payload["decision"], sort_keys=True),
             json.dumps(payload["evidence"], sort_keys=True),
             (json.dumps(payload["recent_leadership"], sort_keys=True)
              if payload["recent_leadership"] is not None else None),
             (json.dumps(payload["ldrc"], sort_keys=True)
              if payload["ldrc"] is not None else None),
             payload_sha256),
        )
        inserted = cur.rowcount == 1
        if not inserted:
            cur.execute(
                "SELECT data_version,state_sha256,strategy_identity,decision,"
                " evidence,recent_leadership,ldrc,payload_sha256 "
                "FROM sentinel_trial_strategy_evidence WHERE session=%s",
                (session,),
            )
            row = cur.fetchone()
            if row is None:
                raise TrialEvidenceConflict(
                    "trial evidence conflict disappeared during verification")
            retained = {
                "session": session,
                "data_version": int(row[0]),
                "state_sha256": str(row[1]),
                "strategy_identity": row[2],
                "decision": row[3],
                "evidence": row[4],
                "recent_leadership": row[5],
                "ldrc": row[6],
            }
            if str(row[7]) != payload_sha256 or _hash(retained) != payload_sha256:
                raise TrialEvidenceConflict(
                    f"session {session} already has different strategy evidence")
    return True


def load_strategy_session(conn, session: str) -> dict | None:
    """Read retained evidence for inspection/reporting; never strategy logic."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT data_version,state_sha256,strategy_identity,decision,evidence,"
            " recent_leadership,ldrc,payload_sha256,recorded_at "
            "FROM sentinel_trial_strategy_evidence WHERE session=%s",
            (session,),
        )
        row = cur.fetchone()
    if row is None:
        return None
    result = {
        "session": session, "data_version": int(row[0]),
        "state_sha256": str(row[1]), "strategy_identity": row[2],
        "decision": row[3], "evidence": row[4],
        "recent_leadership": row[5], "ldrc": row[6],
        "payload_sha256": str(row[7]), "recorded_at": row[8],
    }
    check = {key: result[key] for key in (
        "session", "data_version", "state_sha256", "strategy_identity",
        "decision", "evidence", "recent_leadership", "ldrc")}
    if _hash(check) != result["payload_sha256"]:
        raise TrialEvidenceConflict(
            f"retained strategy evidence hash mismatch for {session}")
    return result


__all__ = [
    "TrialEvidenceConflict", "load_strategy_session",
    "record_strategy_session",
]
