#!/usr/bin/env python3
"""Queue a HUMAN-authored full-config candidate into the wind tunnel's experiment lane.

Until now the only way into `artifacts/bt/proposals.json` was the evaluator's
`queue_strategy_experiment` tool. That is fine for the autonomous loop, but it
leaves no path for the owner to test something the evaluator cannot even propose —
most obviously anything under `PROTECTED_PATHS`, which the LLM is forbidden from
touching. `trailing_stop.enabled` is exactly that case: protected on the live-tuner
path, but sweeps deliberately do not enforce the partition, so the tunnel is allowed
to SCORE it. This script is that path.

It writes the same entry shape the evaluator writes, so the lane, the leaderboard
and the evaluator packet all read it without special-casing. `origin` is set to
'human' rather than 'exploratory' so a later review can tell who asked.

Run it in a container that has BOTH ./strategies (to read the active config) and
./artifacts read-write (to write the queue). `pipeline` has both; bt-scheduler has
neither, and the evaluator mounts /repo without ./scripts. No container mounts the
scripts dir, so copy it in:

    docker compose cp scripts/queue-experiment.py pipeline:/tmp/qe.py
    docker compose exec pipeline python /tmp/qe.py \
        --set trailing_stop.enabled=true \
        --set trailing_stop.stop_pct=0.10 \
        --mechanism exit_hysteresis \
        --hypothesis "A 10% trailing stop exits broken trends earlier than the
                      orphan timer, raising terminal wealth at equal or lower
                      drawdown." \
        --first

--first puts the entry at the head of the queue. The lane fires ONE full-config
candidate per slot and takes pend_full[0], so without it a candidate queues behind
whatever the evaluator already proposed.

Nothing here can reach the live book: the queue feeds the wind tunnel only, and
promotion remains the deterministic gate's decision.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import uuid
from datetime import datetime, timezone

# Add the repo's shared/ when running from a checkout. Inside a service container
# stock_strategy_shared is already installed (editable, from the base image), and
# __file__ may not point anywhere useful — the script is typically `docker compose
# cp`'d to /tmp — so this is best-effort, not required.
try:
    _REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if os.path.isdir(os.path.join(_REPO, "shared")):
        sys.path.insert(0, os.path.join(_REPO, "shared"))
except NameError:  # executed from stdin
    pass

from stock_strategy_shared.filelock import file_lock          # noqa: E402
from stock_strategy_shared.loader import load_strategy        # noqa: E402
from stock_strategy_shared.schemas.strategy import StrategyConfig  # noqa: E402

# Mirrors services/evaluator/app/tools.py MECHANISMS. A candidate must name the
# CLASS of intervention it tests, so a later review can aggregate failures by
# mechanism instead of re-deriving them from diffs.
MECHANISMS = {
    "factor_weighting", "factor_construction", "entry_selection",
    "exit_hysteresis", "portfolio_construction", "concentration_control",
    "risk_control", "turnover_control", "universe",
}


def _coerce(raw: str):
    """YAML-ish scalar coercion so --set takes true/0.10/30/none naturally."""
    low = raw.strip().lower()
    if low in ("true", "yes"):
        return True
    if low in ("false", "no"):
        return False
    if low in ("null", "none"):
        return None
    try:
        return int(raw)
    except ValueError:
        pass
    try:
        return float(raw)
    except ValueError:
        return raw


def apply_diff(cfg: dict, diff: dict) -> dict:
    import copy
    out = copy.deepcopy(cfg)
    for path, value in diff.items():
        parts = [p for p in path.split(".") if p]
        node = out
        for p in parts[:-1]:
            node = node.setdefault(p, {})
            if not isinstance(node, dict):
                raise SystemExit(f"path {path!r} traverses a non-object at {p!r}")
        node[parts[-1]] = value
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--set", action="append", default=[], metavar="dotted.path=value",
                    help="field to change vs the ACTIVE config; repeatable")
    ap.add_argument("--mechanism", required=True,
                    help=f"class of intervention: {', '.join(sorted(MECHANISMS))}")
    ap.add_argument("--hypothesis", required=True,
                    help="what this candidate tests, read cold by a future review")
    ap.add_argument("--config-path", default=os.getenv(
        "STRATEGY_CONFIG_PATH", "/strategies/momentum_rotation_v2.yaml"))
    ap.add_argument("--artifacts", default=os.getenv("ARTIFACTS_PATH", "/artifacts"))
    ap.add_argument("--first", action="store_true",
                    help="put at the HEAD of the queue — the lane fires pend_full[0]")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if args.mechanism not in MECHANISMS:
        raise SystemExit(f"unknown mechanism {args.mechanism!r}; "
                         f"choose one of {', '.join(sorted(MECHANISMS))}")
    if not args.set:
        raise SystemExit("nothing to change — pass at least one --set")

    diff = {}
    for item in args.set:
        if "=" not in item:
            raise SystemExit(f"--set expects dotted.path=value, got {item!r}")
        path, raw = item.split("=", 1)
        diff[path.strip()] = _coerce(raw)

    base_cfg, active_hash = load_strategy(args.config_path)
    candidate = apply_diff(base_cfg.model_dump(mode="json"), diff)
    # Validate BEFORE queueing. A candidate that cannot be constructed would be
    # dropped by the lane as an error row, wasting a slot and telling nobody why.
    try:
        validated = StrategyConfig(**candidate).model_dump(mode="json")
    except Exception as exc:  # noqa: BLE001
        raise SystemExit(f"candidate is not a valid StrategyConfig: {exc}")

    cfg_hash = hashlib.sha256(
        json.dumps(validated, sort_keys=True, default=str).encode()).hexdigest()[:16]

    entry = {
        "id": str(uuid.uuid4()), "kind": "full_config", "status": "pending",
        "origin": "human",
        "hypothesis": " ".join(args.hypothesis.split()),
        "config": validated, "config_hash": cfg_hash, "diff": diff,
        "regime": None, "mechanism": args.mechanism,
        "changed_fields": sorted(diff),
        "predicted_tune_cagr_edge": None,
        "queued_against_config_hash": active_hash,
        "queued_at": datetime.now(timezone.utc).isoformat(),
    }

    if args.dry_run:
        print(json.dumps({k: v for k, v in entry.items() if k != "config"}, indent=2))
        print(f"\n(dry run — nothing written. candidate hash {cfg_hash}, "
              f"active {active_hash})")
        return 0

    bt_dir = os.path.join(args.artifacts, "bt")
    os.makedirs(bt_dir, exist_ok=True)
    path = os.path.join(bt_dir, "proposals.json")
    # Same lock the evaluator and the lane take — this is a read-modify-write on a
    # file three processes touch.
    with file_lock(os.path.join(bt_dir, "proposals.json.lock")):
        content = {"proposals": []}
        if os.path.exists(path):
            with open(path) as f:
                content = json.load(f) or {"proposals": []}
        entries = content.setdefault("proposals", [])
        dupe = [e for e in entries
                if e.get("config_hash") == cfg_hash
                and e.get("status") in ("pending", "testing", "tested")]
        if dupe:
            raise SystemExit(
                f"an identical candidate (hash {cfg_hash}) is already "
                f"{dupe[0].get('status')} — read its results instead of re-running it")
        entries.insert(0, entry) if args.first else entries.append(entry)
        tmp = path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(content, f, indent=1, default=str)
        os.replace(tmp, path)

    pending = [e for e in content["proposals"]
               if e.get("status") == "pending" and e.get("kind") == "full_config"]
    print(f"queued {entry['id']} (hash {cfg_hash}) against active {active_hash}")
    print(f"  diff: {diff}")
    print(f"  position: {1 if args.first else len(pending)} of {len(pending)} pending")
    if not args.first and len(pending) > 1:
        print("  NOTE: the lane fires pend_full[0] — this will not run tonight. "
              "Re-run with --first to jump the queue.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
