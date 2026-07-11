"""Experiment queue — auto-feed the evaluator's recommendations to the isolated
backtest stack as wind-tunnel EXPERIMENTS (docs/backtester-v2-plan.md Phase 6b).

Boundary: proposals are backtests, not config changes — running one is harmless,
so no human gate here; human approval still guards live config deployment. The
LLM gets NO write tool for this: after each successful review, deterministic
Python harvests the already-schema-validated recommendations into
artifacts/bt/proposals.json. bt-scheduler picks pending ones up as extra
single-field configs in the next weekly sweep (file bridge only — no network
path between the stacks).

Everything here is pure except write_proposals_file's atomic replace.
"""
from __future__ import annotations

import hashlib
import json
import os
from typing import Any

from app.tools import apply_config_changes

PENDING_CAP = int(os.getenv("EVALUATOR_PROPOSALS_PENDING_CAP", "8"))
RETAIN = int(os.getenv("EVALUATOR_PROPOSALS_RETAIN", "40"))

_NULL_TOKENS = {"none", "null", "off", "disabled", "disable"}


def parse_suggested_value(raw: Any) -> tuple[Any, bool]:
    """LLM suggested_value (a string per the report schema) → JSON value.
    Returns (value, ok). Not every recommendation is a testable literal —
    prose like 'reduce by half' fails parsing and is skipped, not guessed at."""
    if isinstance(raw, (int, float, bool)) or raw is None:
        return raw, True
    s = str(raw).strip()
    if not s:
        return None, False
    try:
        return json.loads(s), True
    except ValueError:
        pass
    low = s.lower()
    if low in _NULL_TOKENS:
        return None, True
    if low == "true":
        return True, True
    if low == "false":
        return False, True
    # bare numbers with stray chars ("0.15 (15%)") or prose → not testable
    return None, False


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


def proposals_path() -> str:
    return os.path.join(os.getenv("ARTIFACTS_PATH", "/artifacts"),
                        "bt", "proposals.json")


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
