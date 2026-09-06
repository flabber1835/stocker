#!/usr/bin/env python3
"""Run the exact formal Champion economic program with only the synthetic
10%-of-prior-volume execution guards removed.

This is a controlled attribution replay. It never issues certification and does
not alter Champion parameters, initial capital, corpus, dividend lag, terminal
rules, classifier, controller, costs, or dates.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import types

from backtester.champion_economic_prefix_audit import (
    CAP_GUARDS,
    EXPECTED_CORPUS,
    PROFILE,
    PROFILE_HASH,
    RUNTIME,
    SOURCE,
    normalized_ast,
    replace_one,
)


def sha_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def write_json(path: Path, value) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n")


def build_capacity_off_source(output: Path) -> tuple[str, str]:
    from backtester import run_research_champion_strict_pit_20y_v2 as target

    baseline = target.champion._champion_strict20_transform("fullpit", output)
    controlled = baseline
    for guard in CAP_GUARDS:
        controlled = replace_one(controlled, guard, "")
    compile(controlled, "<champion-full-capacity-off>", "exec")
    return baseline, controlled


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    output = args.output.resolve()
    engine_output = output / "engine"
    output.mkdir(parents=True, exist_ok=True)
    engine_output.mkdir(parents=True, exist_ok=True)

    expected_source = SOURCE["certified"]
    actual_source = __import__("subprocess").check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    if actual_source != expected_source:
        raise RuntimeError(f"wrong certificate checkout: {actual_source} != {expected_source}")

    dataset = Path(os.environ["CANONICAL_PIT_DATASET"])
    manifest = json.loads((dataset / "manifest.json").read_text())
    if manifest.get("dataset_hash") != EXPECTED_CORPUS:
        raise RuntimeError("wrong canonical PIT dataset")

    baseline, controlled = build_capacity_off_source(engine_output)
    (output / "baseline-generated.py").write_text(baseline)
    (output / "capacity-off-generated.py").write_text(controlled)

    identity = {
        "schema": "champion.economic-full-capacity-control/1",
        "status": "RUNNING_DIAGNOSTIC_NOT_CERTIFIED",
        "certification_status": "NOT_CERTIFIED_CONTROLLED_ATTRIBUTION",
        "baseline_source_sha": expected_source,
        "audit_source_sha": os.environ.get("AUDIT_SOURCE_SHA", ""),
        "runtime_sha": RUNTIME,
        "profile": PROFILE,
        "profile_sha256": PROFILE_HASH,
        "corpus_hash": EXPECTED_CORPUS,
        "initial_shadow_cash": 100000000,
        "warmup_start": "2006-01-03",
        "measurement_start": "2006-07-31",
        "end_session": "2026-07-31",
        "changed_dimension": "EXECUTION_PARTICIPATION_CAP_ONLY",
        "change": "remove exactly the two 10%-of-prior-20-volume whole-order deferral guards",
        "baseline_generated_sha256": sha_bytes(baseline.encode()),
        "controlled_generated_sha256": sha_bytes(controlled.encode()),
        "baseline_normalized_ast_sha256": sha_bytes(normalized_ast(baseline).encode()),
        "controlled_normalized_ast_sha256": sha_bytes(normalized_ast(controlled).encode()),
        "guard_occurrences_removed": 2,
    }
    write_json(output / "identity.json", identity)

    module = types.ModuleType("champion_full_capacity_off")
    sys.modules[module.__name__] = module
    exec(compile(controlled, str(output / "capacity-off-generated.py"), "exec"), module.__dict__)
    try:
        module.run()
    except Exception as exc:
        identity["status"] = "FAIL"
        identity["failure"] = f"{type(exc).__name__}: {exc}"
        write_json(output / "identity.json", identity)
        raise

    identity["status"] = "PASS_FULL_HORIZON_DIAGNOSTIC_NOT_CERTIFIED"
    write_json(output / "identity.json", identity)
    write_json(output / "SHA256.json", {
        str(path.relative_to(output)): sha_bytes(path.read_bytes())
        for path in sorted(output.rglob("*")) if path.is_file() and path.name != "SHA256.json"
    })
    print(json.dumps(identity, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
