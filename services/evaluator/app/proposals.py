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

import hashlib
import json
import os
from typing import Any

# SHARED parser (also used by the api service's one-click apply) — "what value
# does this recommendation mean" cannot diverge between testing and applying.
from stock_strategy_shared.config_values import parse_suggested_value  # noqa: F401

from app.tools import apply_config_changes

PENDING_CAP = int(os.getenv("EVALUATOR_PROPOSALS_PENDING_CAP", "8"))
RETAIN = int(os.getenv("EVALUATOR_PROPOSALS_RETAIN", "40"))



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


def write_proposals_file(content: dict) -> None:
    path = proposals_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(content, f, indent=1, default=str)
    os.replace(tmp, path)
