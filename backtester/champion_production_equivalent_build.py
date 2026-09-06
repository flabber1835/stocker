#!/usr/bin/env python3
"""Build and probe the final Production-equivalent Champion program.

This command deliberately does **not** execute the 20-year replay.  It produces
an exact generated source artifact and a machine-readable source-probe report.
The performance runner remains gated until this build is independently green.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess

from backtester import champion_full_classification_control as control
from backtester.production_equivalent_economic_overlay import install, assert_contract
from backtester.champion_economic_prefix_audit import (
    EXPECTED_CORPUS, PROFILE, PROFILE_HASH, RUNTIME, SOURCE,
)


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--candidate-root", required=True, type=Path)
    p.add_argument("--output", required=True, type=Path)
    args = p.parse_args()

    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    engine = out / "engine-build"
    engine.mkdir()

    # The source builder is an audit branch layered on the frozen formal and
    # candidate source identities.  We verify the candidate checkout exactly;
    # the current audit head is separately recorded rather than pretending to
    # equal the old formal source commit.
    candidate = subprocess.check_output(
        ["git", "-C", str(args.candidate_root), "rev-parse", "HEAD"], text=True
    ).strip()
    if candidate != SOURCE["candidate"]:
        raise RuntimeError(f"candidate source pin mismatch: {candidate}")

    manifest = json.loads((Path(os.environ["CANONICAL_PIT_DATASET"]) / "manifest.json").read_text())
    if manifest.get("dataset_hash") != EXPECTED_CORPUS:
        raise RuntimeError("canonical corpus identity mismatch")

    baseline, capacity_off, prior = control.build_source(engine, args.candidate_root)
    if "_research_capacity_guard(" in capacity_off:
        raise RuntimeError("capacity-off source still contains executable capacity guard")
    final = install(prior)
    assert_contract(final)

    (out / "baseline-generated.py").write_text(baseline)
    (out / "capacity-off-generated.py").write_text(capacity_off)
    (out / "prior-classification-generated.py").write_text(prior)
    (out / "production-equivalent-generated.py").write_text(final)

    audit_head = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    report = {
        "schema": "champion.production-equivalent-source-build/1",
        "status": "PASS_SOURCE_BUILD_NO_REPLAY",
        "audit_head": audit_head,
        "formal_source_sha": SOURCE["certified"],
        "candidate_source_sha": candidate,
        "runtime_sha": RUNTIME,
        "profile": PROFILE,
        "profile_sha256": PROFILE_HASH,
        "corpus_hash": EXPECTED_CORPUS,
        "capacity_participation_cap": None,
        "dividend_accrual_precedes_open_equity": final.index("receivables.append") < final.index("open_eq,_=book.equity(opraw)"),
        "dividend_lag_sessions": 1,
        "cumulative_terminal_retirement_present": "_retired_tids" in final,
        "hard_abort_missing_mark_present": "financial-grade NAV unresolved" in final,
        "final_truth_classifier_present": "champion_final_security_truth as _bestclass" in final,
        "performance_replay_executed": False,
        "generated_sha256": {
            "baseline": digest(baseline.encode()),
            "capacity_off": digest(capacity_off.encode()),
            "prior_classification": digest(prior.encode()),
            "production_equivalent": digest(final.encode()),
        },
    }
    if not report["dividend_accrual_precedes_open_equity"] or report["cumulative_terminal_retirement_present"] or report["hard_abort_missing_mark_present"] or not report["final_truth_classifier_present"]:
        raise RuntimeError(f"source probe mismatch: {report}")
    (out / "SOURCE_PROBES.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    (out / "SHA256.json").write_text(json.dumps({
        p.name: digest(p.read_bytes()) for p in sorted(out.iterdir()) if p.is_file() and p.name != "SHA256.json"
    }, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
