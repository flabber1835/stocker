#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RUNNER_DIR = ROOT / "research" / "wealth-core-v5-canonical-reconvergence-v1"
sys.path.insert(0, str(RUNNER_DIR))
import run_reconvergence as rr

FROZEN_HEAD = "f5c765e62d173839fd6b36c32d6422cec269d1c7"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--old-baseline-input", required=True, type=Path)
    ap.add_argument("--control-source", required=True, type=Path)
    ap.add_argument("--median-overlay", required=True, type=Path)
    ap.add_argument("--output", required=True, type=Path)
    args = ap.parse_args()

    old_root = args.old_baseline_input.resolve()
    prior = json.loads((old_root / "RESULT.json").read_text())
    if prior.get("status") != "PASS" or prior.get("suite") != "baseline":
        raise RuntimeError("prior adversarial baseline is not PASS")
    if prior.get("experiment_head") != FROZEN_HEAD:
        raise RuntimeError(f"prior baseline head mismatch: {prior.get('experiment_head')}")
    old = prior["baseline"]
    rr.adv.assert_baseline(old)

    root = args.output.resolve()
    shutil.rmtree(root, ignore_errors=True)
    (root / "old").mkdir(parents=True)
    src_daily = old_root / "baseline-run" / "daily.csv"
    if not src_daily.exists():
        raise RuntimeError("prior baseline daily tape missing")
    shutil.copy2(src_daily, root / "old" / "daily.csv")
    for name in ("summary.json", "transactions.csv", "close-decisions.csv", "open-sizing-telemetry.json"):
        p = old_root / "baseline-run" / name
        if p.exists(): shutil.copy2(p, root / "old" / name)

    selected = rr.adv.build_selected(args.control_source, args.median_overlay)
    reconv_src = rr.apply_reconvergence(selected)
    reconv = rr.adv.execute(reconv_src, root / "reconv", "reconv_baseline", keep_raw=True)

    oldf = rr.load_daily(root / "old" / "daily.csv")
    recf = rr.load_daily(root / "reconv" / "daily.csv")
    holdouts = rr.frozen_holdouts(oldf, recf)
    result = {
        "schema": rr.SCHEMA,
        "suite": "baseline",
        "status": "PASS",
        "system": rr.SYSTEM,
        "old": old,
        "reconvergence": reconv,
        "architecture_change_only": True,
        "old_baseline_authority": {
            "source_run": 34367819219,
            "artifact": "v5-ex3-v5-adversarial-baseline",
            "experiment_head": FROZEN_HEAD,
            "exact_parity_revalidated": True,
        },
        "holdout_policy": {
            "count": rr.HOLDOUT_COUNT,
            "original_96_shard_minimum": rr.PREVIOUSLY_UNTOUCHED_MIN_SHARD,
            "selection": "sha256(canonical-reconvergence-holdout-v1:<security_id>) among IDs held by both unperturbed paths",
            "performance_used_for_selection": False,
        },
        "holdout_security_ids": holdouts,
    }
    rr.write_json(root / "RESULT.json", result)
    rr.write_json(root / "holdout-security-ids.json", holdouts)
    print(json.dumps({"status":"PASS","holdouts":holdouts}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
