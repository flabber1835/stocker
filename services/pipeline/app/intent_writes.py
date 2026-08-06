"""Persistence for intent reconciliation (defect 4).

WHY THIS IS A MODULE AND NOT INLINE SQL IN `main.py`. The shadow write is
wrapped in a `try` that logs and continues — it must be, because it shares a
transaction with the `delta_intents` rows the trade-executor actually reads and
must not be able to fail the delta run. But that same tolerance means a typo in a
column name would surface only as `[delta] intent reconciliation skipped (…)` in
a log nobody reads, and the shadow would quietly write nothing for weeks while
appearing to be deployed. Putting the statements here lets the integration tier
run THESE EXACT statements against a real migrated schema, so a column that does
not exist fails in CI instead of disappearing into an exception handler.

The rule itself is pure and lives in
`shared/stock_strategy_shared/intent_reconciliation.py`. This module only writes.
"""
from __future__ import annotations

import json
from typing import Sequence

from sqlalchemy import text

from stock_strategy_shared.intent_reconciliation import (NetIntent, Proposal,
                                                         provenance_json)

_INSERT_PROPOSAL = text(
    "INSERT INTO intent_proposals "
    "(run_id, account_id, ticker, source, action, seq, rank, composite_score, "
    " confirmation_days_met, target_weight, actual_weight, weight_drift, reason) "
    "VALUES (:rid, :acct, :ticker, :source, :action, :seq, :rank, :score, "
    "        :conf_days, :weight, :actual_weight, :weight_drift, :reason)"
)

_INSERT_NET = text(
    "INSERT INTO net_intents "
    "(run_id, account_id, ticker, action, source, resolved_by, conflicted, "
    " contributing, rank, composite_score, confirmation_days_met, target_weight, "
    " actual_weight, weight_drift, reason) "
    "VALUES (:rid, :acct, :ticker, :action, :source, :rule, :conflicted, "
    "        CAST(:prov AS JSONB), :rank, :score, :conf_days, :weight, "
    "        :actual_weight, :weight_drift, :reason)"
)


def _r6(v) -> float | None:
    return round(v, 6) if v is not None else None


async def write_proposals(conn, run_id, proposals: Sequence[Proposal]) -> int:
    """Append every proposal, winners and losers alike."""
    for p in proposals:
        await conn.execute(_INSERT_PROPOSAL, {
            "rid": run_id, "acct": p.account_id, "ticker": p.ticker,
            "source": p.source, "action": p.action, "seq": p.seq,
            "rank": p.rank, "score": _r6(p.composite_score),
            "conf_days": p.confirmation_days_met,
            "weight": p.target_weight,
            "actual_weight": _r6(p.actual_weight),
            "weight_drift": _r6(p.weight_drift),
            "reason": p.reason,
        })
    return len(proposals)


async def write_net_intents(conn, run_id, nets: Sequence[NetIntent]) -> int:
    """Write the reconciled instructions. The unique index on
    (run_id, account_id, ticker) means a second row for one key raises here —
    which is the invariant doing its job, not a bug to catch."""
    for n in nets:
        w = n.winner
        await conn.execute(_INSERT_NET, {
            "rid": run_id, "acct": n.account_id, "ticker": n.ticker,
            "action": n.action, "source": w.source, "rule": n.resolved_by,
            "conflicted": n.conflicted, "prov": json.dumps(provenance_json(n)),
            "rank": w.rank, "score": _r6(w.composite_score),
            "conf_days": w.confirmation_days_met,
            "weight": w.target_weight,
            "actual_weight": _r6(w.actual_weight),
            "weight_drift": _r6(w.weight_drift),
            "reason": w.reason,
        })
    return len(nets)
