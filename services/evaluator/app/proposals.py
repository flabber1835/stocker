"""Experiment queue — feed the isolated backtest stack wind-tunnel EXPERIMENTS
(docs/backtester-v2-plan.md Phase 6b).

Boundary: proposals are backtests, not config changes — running one is harmless,
so no human gate here; human approval still guards live config deployment.
Two producers, identical validation and caps:

1. HARVEST (deterministic Python, no LLM write): after each successful review,
   the already-schema-validated recommendations are harvested into
   artifacts/bt/proposals.json.
2. queue_experiment TOOL (LLM-invoked, enqueue-only): lets the evaluator test a
   thesis in the wind tunnel WITHOUT putting a recommendation in front of the
   human — entries are tagged origin="exploratory" and carry the stated
   hypothesis. The tool can only append pending entries to this one file
   (same single-field diff, same StrategyConfig validation, same PENDING_CAP);
   it cannot run anything, touch config, or alter existing entries.

bt-scheduler picks pending entries up as extra single-diff configs in the next
weekly sweep (file bridge only — no network path between the stacks).

Everything here is pure except write_proposals_file's atomic replace.
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


def proposal_id(field: str, value: Any) -> str:
    return hashlib.sha1(
        f"{field}={json.dumps(value, sort_keys=True, default=str)}".encode()
    ).hexdigest()[:16]


def harvest_proposals(recommendations: list[dict], active_config: dict,
                      existing: dict | None, *, run_id: str, iso_week: str,
                      now_iso: str) -> tuple[dict, list[dict]]:
    """Merge this review's actionable recommendations into the proposals file
    content. Returns (new_file_dict, newly_added). A proposal is queued only if:
    config_field stamped valid by validate_recommendations, not 'none',
    suggested_value parses to a literal, the single-field diff validates through
    StrategyConfig against the ACTIVE config, and it isn't already in the file
    (any status — tested entries suppress re-queuing until they age out of the
    RETAIN window, forcing the review to argue from results, not repetition)."""
    entries: list[dict] = list((existing or {}).get("proposals") or [])
    seen = {e.get("id") for e in entries}
    n_pending = sum(1 for e in entries if e.get("status") == "pending")
    added: list[dict] = []

    for rec in recommendations or []:
        if not isinstance(rec, dict) or not rec.get("config_field_valid"):
            continue
        field = str(rec.get("config_field") or "").strip()
        if not field or field.lower() == "none":
            continue
        value, ok = parse_suggested_value(rec.get("suggested_value"))
        if not ok:
            continue
        validated, err = apply_config_changes(active_config, {field: value})
        if err is not None:
            continue
        pid = proposal_id(field, value)
        if pid in seen or n_pending + len(added) >= PENDING_CAP:
            continue
        added.append({
            "id": pid,
            "config_field": field,
            "value": value,
            "status": "pending",
            "source_run_id": run_id,
            "iso_week": iso_week,
            "confidence": rec.get("confidence"),
            "observation": str(rec.get("observation") or "")[:300],
            "created_at": now_iso,
            "sweep_id": None,
        })
        seen.add(pid)

    entries = (entries + added)[-RETAIN:]
    return {"proposals": entries}, added


def queue_exploratory(field: str, value: Any, hypothesis: str,
                      existing: dict | None, *, run_id: str | None,
                      iso_week: str, now_iso: str) -> tuple[dict, dict]:
    """Append ONE exploratory (tool-queued, not recommended) experiment.
    Returns (new_file_dict, result) where result reports queued/duplicate/cap.
    Same dedupe rule as harvest: an id already in the file — ANY status —
    is never re-queued, so a tested thesis must be argued from its results.
    Pure; caller validates the diff and holds proposals_lock()."""
    entries: list[dict] = list((existing or {}).get("proposals") or [])
    pid = proposal_id(field, value)
    for e in entries:
        if e.get("id") == pid:
            return {"proposals": entries}, {
                "queued": False, "reason": "already in queue", "id": pid,
                "status": e.get("status"), "origin": e.get("origin", "recommendation"),
            }
    n_pending = sum(1 for e in entries if e.get("status") == "pending")
    if n_pending >= PENDING_CAP:
        return {"proposals": entries}, {
            "queued": False, "reason": f"pending cap reached ({PENDING_CAP})",
            "pending": n_pending,
        }
    entry = {
        "id": pid,
        "config_field": field,
        "value": value,
        "status": "pending",
        "origin": "exploratory",
        "hypothesis": str(hypothesis or "").strip()[:300],
        "source_run_id": run_id,
        "iso_week": iso_week,
        "created_at": now_iso,
        "sweep_id": None,
    }
    entries = (entries + [entry])[-RETAIN:]
    return {"proposals": entries}, {"queued": True, "id": pid, "pending": n_pending + 1}


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
