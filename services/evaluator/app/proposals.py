"""Wind-tunnel experiment queue — file I/O and the cross-stack lock.

The single-field producers (harvest_proposals / queue_exploratory /
proposal_id) were REMOVED with the human one-click apply: a COMPLETE candidate
config is now the only currency, written by the evaluator's
queue_strategy_experiment tool and consumed by bt-scheduler's experiment lane.
What remains here is the shared read/write/lock the two stacks meet on
(tests/cross_service/test_evaluator_windtunnel_contract.py owns that seam).

Boundary: queued candidates are BACKTESTS, not config changes. A change reaches
the live strategy only by winning the deterministic promotion gate.
"""
from __future__ import annotations

import json
import os

# How many finished (tested/failed/invalid) entries to keep. Every entry embeds
# a COMPLETE StrategyConfig (kilobytes), and both stacks read+rewrite the whole
# file under a lock on every queue write and every lifecycle mark — so without
# trimming the file grows forever and every write gets slower. Pending/testing
# entries are NEVER trimmed (they are live work).
RETAIN = int(os.getenv("EVALUATOR_PROPOSALS_RETAIN", "40"))
_LIVE_STATUSES = ("pending", "testing")



def proposals_path() -> str:
    return os.path.join(os.getenv("ARTIFACTS_PATH", "/artifacts"),
                        "bt", "proposals.json")


def proposals_lock():
    """Serializes the read→harvest→write against bt-scheduler's lifecycle
    marking (same lock file, same host inode — works across containers)."""
    from stock_strategy_shared.filelock import file_lock
    return file_lock(proposals_path() + ".lock")


def read_proposals_file() -> dict | None:
    try:
        with open(proposals_path()) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def trim_proposals(entries: list[dict], retain: int = RETAIN) -> list[dict]:
    """Drop the oldest FINISHED entries beyond `retain`, keeping every live one
    and preserving order. Pure."""
    finished = [i for i, e in enumerate(entries)
                if e.get("status") not in _LIVE_STATUSES]
    drop = set(finished[:max(0, len(finished) - retain)])
    return [e for i, e in enumerate(entries) if i not in drop]


def write_proposals_file(content: dict) -> None:
    path = proposals_path()
    if isinstance(content.get("proposals"), list):
        content = {**content, "proposals": trim_proposals(content["proposals"])}
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(content, f, indent=1, default=str)
    os.replace(tmp, path)
