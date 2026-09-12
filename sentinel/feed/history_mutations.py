"""Bind durable historical corrections to the atomic publication receipt."""
from __future__ import annotations

from sentinel.core.history import SCHEMA, validate_proof
from sentinel.core.terminal import (
    DIVIDEND_ACTIONS, SHARE_SPLIT_ACTIONS, SPINOFF_ACTIONS, TERMINAL_ACTIONS,
)

EVIDENCE_KEY = "strategy_history"
STATE_ACTIONS = DIVIDEND_ACTIONS | SHARE_SPLIT_ACTIONS | SPINOFF_ACTIONS | TERMINAL_ACTIONS


def publication_proof(conn, *, previous, version: int, run_id, evidence) -> dict:
    if EVIDENCE_KEY in evidence:
        raise ValueError("caller may not supply historical mutation authority")
    if previous is None:
        baseline, changes = 0, []
    else:
        prior = previous.evidence.get(EVIDENCE_KEY)
        if prior is None:
            # The old corpus is an explicit baseline. An older state cannot
            # cross this unobserved prefix and acquire new historical authority.
            baseline, changes = previous.version, []
        else:
            checked = validate_proof(prior, version=previous.version)
            baseline, changes = checked["baseline_version"], checked["changes"]

    affected = []
    if previous is not None:
        # Include failed attempts at this publication. Their in-place writes
        # may be reclaimed unchanged by a succeeding run, so examining only
        # the successful writer would lose the original revision boundary.
        with conn.cursor() as cur:
            cur.execute(
                "SELECT MIN(affected_session) FROM sentinel_history_mutations"
                " WHERE base_version=%s", (previous.version,))
            row = cur.fetchone()
        if row and row[0] is not None:
            affected.append(str(row[0]))
        if run_id is not None:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT MIN(o.session) FROM sentinel_action_observations o"
                    " WHERE o.last_written_run_id=%s AND LOWER(o.action)=ANY(%s)"
                    " AND ((o.disposition='PRESENT' AND NOT EXISTS ("
                    " SELECT 1 FROM sentinel_active_actions a"
                    " WHERE a.source_row_id=o.source_row_id))"
                    " OR (o.disposition='REMOVED' AND EXISTS ("
                    " SELECT 1 FROM sentinel_active_actions a"
                    " WHERE a.source_row_id=o.source_row_id)))",
                    (str(run_id), sorted(STATE_ACTIONS)))
                row = cur.fetchone()
            if row and row[0] is not None:
                affected.append(str(row[0]))
        retirement = evidence.get("source_retirement")
        if retirement is not None:
            affected.append(str(retirement["interval"][0]))
    if affected:
        changes = [*changes, [version, min(affected)]]
    return validate_proof({
        "schema": SCHEMA, "baseline_version": baseline,
        "publication_version": version, "changes": changes,
    }, version=version)
