"""Persistence for intent reconciliation (defect 4), with retry semantics.

WHY THIS IS A MODULE AND NOT INLINE SQL IN `main.py`. The shadow write is
wrapped in a `try` that logs and continues — it must be, because it shares a
transaction with the `delta_intents` rows the trade-executor actually reads and
must not be able to fail the delta run. But that same tolerance means a typo in a
column name would surface only as `[delta] intent reconciliation skipped (…)` in
a log nobody reads, and the shadow would quietly write nothing for weeks while
appearing to be deployed. Putting the statements here lets the integration tier
run THESE EXACT statements against a real migrated schema.

RETRY SEMANTICS, and why a bare unique violation was not good enough. Production
calls both writers inside ONE savepoint. On a retry of the same run the proposals
inserted fine and the net-intent unique index then raised, rolling the savepoint
back and taking the new proposal rows with it — so the append-only table was
append-only until something went wrong, which is when it matters. Worse, once the
shadow's tolerant `except` becomes fatal at executor cutover, an ordinary retry of
an unchanged run would fail the whole delta step. Uniqueness prevented duplicate
trades without defining what a safe retry means. It now means:

    identical net intent already present   idempotent SUCCESS. Counted, not
                                           silently ignored — a retry is a fact
                                           about the run and the caller is told.
    DIFFERENT net intent for the same key  NetIntentDivergence, fatal. Two
                                           reconciliations of one run disagreeing
                                           is a defect in the inputs or the rule,
                                           and the second answer must never
                                           quietly replace the first.
    proposals                              always appended, under a fresh
                                           `attempt_id` per invocation, so
                                           repeated attempts stay distinguishable
                                           instead of merging into one history.

Divergence is raised AFTER every net intent has been examined, so the error names
every disagreeing ticker rather than the first one. The savepoint then rolls back
the whole attempt including its proposals — the divergence detail travels in the
exception (and thence the log), not in the table, which is the cost of the
savepoint and is recorded here rather than discovered later.

The rule itself is pure and lives in
`shared/stock_strategy_shared/intent_reconciliation.py`. This module only writes.
"""
from __future__ import annotations

import json
import uuid
from typing import Optional, Sequence

from sqlalchemy import text

from stock_strategy_shared.intent_reconciliation import (NetIntent, Proposal,
                                                         provenance_json)


class NetIntentDivergence(Exception):
    """A retry produced a DIFFERENT executable instruction than the one stored.

    Fatal by design. The stored intent may already have been acted on; replacing
    it would rewrite an instruction the rest of the system believes it has, and
    keeping both is what the unique index exists to prevent.
    """

    def __init__(self, divergences: list[dict]) -> None:
        self.divergences = divergences
        detail = "; ".join(
            f"{d['ticker']}: stored {d['stored']} != recomputed {d['recomputed']}"
            for d in divergences
        )
        super().__init__(
            f"net intent divergence on retry for {len(divergences)} ticker(s): {detail}"
        )


_INSERT_PROPOSAL = text(
    "INSERT INTO intent_proposals "
    "(run_id, attempt_id, account_id, ticker, source, action, seq, rank, "
    " composite_score, confirmation_days_met, target_weight, actual_weight, "
    " weight_drift, reason) "
    "VALUES (:rid, :aid, :acct, :ticker, :source, :action, :seq, :rank, :score, "
    "        :conf_days, :weight, :actual_weight, :weight_drift, :reason)"
)

# ON CONFLICT DO NOTHING rather than letting the unique index raise. A raised
# constraint violation poisons the whole transaction, so the comparison that
# decides idempotent-vs-divergent could not run afterwards — the write would have
# to fail before knowing whether failing was correct.
_INSERT_NET = text(
    "INSERT INTO net_intents "
    "(run_id, account_id, ticker, action, source, resolved_by, conflicted, "
    " contributing, rank, composite_score, confirmation_days_met, target_weight, "
    " actual_weight, weight_drift, reason) "
    "VALUES (:rid, :acct, :ticker, :action, :source, :rule, :conflicted, "
    "        CAST(:prov AS JSONB), :rank, :score, :conf_days, :weight, "
    "        :actual_weight, :weight_drift, :reason) "
    "ON CONFLICT (run_id, account_id, ticker) DO NOTHING "
    "RETURNING id"
)

_SELECT_EXISTING_NET = text(
    "SELECT action, resolved_by, target_weight FROM net_intents "
    "WHERE run_id=:rid AND account_id=:acct AND ticker=:ticker"
)


def _r6(v) -> Optional[float]:
    return round(v, 6) if v is not None else None


def new_attempt_id() -> uuid.UUID:
    """One id per writer invocation. Callers pass the SAME value to both writers
    of one attempt."""
    return uuid.uuid4()


async def write_proposals(
    conn,
    run_id,
    proposals: Sequence[Proposal],
    attempt_id,
) -> int:
    """Append every proposal of ONE attempt, winners and losers alike."""
    for p in proposals:
        await conn.execute(_INSERT_PROPOSAL, {
            "rid": run_id, "aid": attempt_id, "acct": p.account_id,
            "ticker": p.ticker, "source": p.source, "action": p.action,
            "seq": p.seq, "rank": p.rank, "score": _r6(p.composite_score),
            "conf_days": p.confirmation_days_met,
            "weight": p.target_weight,
            "actual_weight": _r6(p.actual_weight),
            "weight_drift": _r6(p.weight_drift),
            "reason": p.reason,
        })
    return len(proposals)


async def write_net_intents(conn, run_id, nets: Sequence[NetIntent]) -> dict:
    """Write the reconciled instructions, idempotently.

    Returns {"inserted", "idempotent", "total"}. Raises NetIntentDivergence if a
    stored intent disagrees with the recomputed one — after checking them ALL, so
    the error names every disagreement rather than the first.
    """
    inserted = idempotent = 0
    divergences: list[dict] = []

    for n in nets:
        w = n.winner
        weight = _r6(w.target_weight)
        row = (await conn.execute(_INSERT_NET, {
            "rid": run_id, "acct": n.account_id, "ticker": n.ticker,
            "action": n.action, "source": w.source, "rule": n.resolved_by,
            "conflicted": n.conflicted, "prov": json.dumps(provenance_json(n)),
            "rank": w.rank, "score": _r6(w.composite_score),
            "conf_days": w.confirmation_days_met,
            "weight": weight,
            "actual_weight": _r6(w.actual_weight),
            "weight_drift": _r6(w.weight_drift),
            "reason": w.reason,
        })).first()

        if row is not None:
            inserted += 1
            continue

        existing = (await conn.execute(_SELECT_EXISTING_NET, {
            "rid": run_id, "acct": n.account_id, "ticker": n.ticker,
        })).mappings().one()

        stored_weight = (round(float(existing["target_weight"]), 6)
                         if existing["target_weight"] is not None else None)
        # `resolved_by` is compared alongside the instruction on purpose. Two
        # reconciliations reaching the same action by DIFFERENT rules agree only
        # by coincidence — they are one input away from disagreeing, which is the
        # same argument the crash-brake transition record settled.
        same = (existing["action"] == n.action
                and existing["resolved_by"] == n.resolved_by
                and stored_weight == weight)
        if same:
            idempotent += 1
        else:
            divergences.append({
                "ticker": n.ticker,
                "account_id": n.account_id,
                "stored": {"action": existing["action"],
                           "resolved_by": existing["resolved_by"],
                           "target_weight": stored_weight},
                "recomputed": {"action": n.action,
                               "resolved_by": n.resolved_by,
                               "target_weight": weight},
            })

    if divergences:
        raise NetIntentDivergence(divergences)

    return {"inserted": inserted, "idempotent": idempotent, "total": len(nets)}
