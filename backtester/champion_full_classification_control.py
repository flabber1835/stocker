#!/usr/bin/env python3
"""Run the capacity-corrected formal Champion path with only the candidate
historical unknown-security-type classifier added.

This is a controlled attribution replay. It does not certify performance and it
keeps Champion parameters, $100M starting shadow cash, corpus, runtime,
dividend lag, terminal rules, costs, controller and dates unchanged.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
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


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def write(path: Path, value) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n")


def build_source(output: Path, candidate_root: Path) -> tuple[str, str, str]:
    from backtester import run_research_champion_strict_pit_20y_v2 as target
    import backtester

    baseline = target.champion._champion_strict20_transform("fullpit", output)
    capacity_off = baseline
    for guard in CAP_GUARDS:
        capacity_off = replace_one(capacity_off, guard, "")

    candidate_backtester = str(candidate_root.resolve() / "backtester")
    if candidate_backtester not in backtester.__path__:
        backtester.__path__.append(candidate_backtester)
    from backtester import research_champion_corrected_classification as classifier

    os.environ["BEST_EFFORT_SECURITY_TYPES"] = str(classifier.base.DEFAULT_LEDGER)
    os.environ["BEST_EFFORT_CLASSIFICATION_SCENARIO"] = "reviewed_18"

    controlled = replace_one(
        capacity_off,
        "from collections import defaultdict\n",
        "from collections import defaultdict\nfrom backtester import research_champion_corrected_classification as _bestclass\n",
    )
    anchor = "actions,split_dates=load_actions(); spy,bil=load_funds(); book=Book(); native=Native()"
    controlled = replace_one(
        controlled,
        anchor,
        anchor + "\n    _BEST_TYPES=_bestclass.SecurityTypeEstimate(Path(os.environ['BEST_EFFORT_SECURITY_TYPES']),os.environ['BEST_EFFORT_CLASSIFICATION_SCENARIO'])",
    )
    controlled = replace_one(
        controlled,
        "            elig=_sec_ok&_base_elig",
        """            for _j in np.flatnonzero(_base_elig):
                _tid=int(tids[int(_j)]); _mr=_metadata(_tid,ds)
                if _mr is None or str(_mr.get('security_type','')).strip().lower()=='unknown':
                    _estimated=_BEST_TYPES.classify(str(sid[_tid]),ds)
                    _sec_ok[int(_j)]=_estimated=='common'
            elig=_sec_ok&_base_elig""",
    )
    compile(controlled, "<champion-full-classification-control>", "exec")
    return baseline, capacity_off, controlled


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--candidate-root", required=True, type=Path)
    args = parser.parse_args()

    output = args.output.resolve()
    engine = output / "engine"
    output.mkdir(parents=True, exist_ok=True)
    engine.mkdir(parents=True, exist_ok=True)

    actual = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    expected = SOURCE["certified"]
    if actual != expected:
        raise RuntimeError(f"wrong certified checkout: {actual} != {expected}")
    candidate_sha = subprocess.check_output(
        ["git", "-C", str(args.candidate_root), "rev-parse", "HEAD"], text=True
    ).strip()
    if candidate_sha != SOURCE["candidate"]:
        raise RuntimeError(f"wrong candidate classifier checkout: {candidate_sha}")

    manifest = json.loads((Path(os.environ["CANONICAL_PIT_DATASET"]) / "manifest.json").read_text())
    if manifest.get("dataset_hash") != EXPECTED_CORPUS:
        raise RuntimeError("wrong canonical PIT dataset")

    baseline, capacity_off, controlled = build_source(engine, args.candidate_root)
    for name, text in [
        ("baseline-generated.py", baseline),
        ("capacity-off-generated.py", capacity_off),
        ("capacity-off-plus-classification-generated.py", controlled),
    ]:
        (output / name).write_text(text)

    identity = {
        "schema": "champion.economic-full-classification-control/1",
        "status": "RUNNING_DIAGNOSTIC_NOT_CERTIFIED",
        "certification_status": "NOT_CERTIFIED_CONTROLLED_ATTRIBUTION",
        "baseline_source_sha": expected,
        "candidate_classifier_source_sha": candidate_sha,
        "audit_source_sha": os.environ.get("AUDIT_SOURCE_SHA", ""),
        "runtime_sha": RUNTIME,
        "profile": PROFILE,
        "profile_sha256": PROFILE_HASH,
        "corpus_hash": EXPECTED_CORPUS,
        "initial_shadow_cash": 100000000,
        "warmup_start": "2006-01-03",
        "measurement_start": "2006-07-31",
        "end_session": "2026-07-31",
        "base_case": "FORMAL_CERTIFICATE_WITH_UNINTENDED_CAPACITY_GUARDS_REMOVED",
        "changed_dimension": "UNKNOWN_SECURITY_TYPE_CLASSIFICATION_ONLY",
        "classification_scenario": "reviewed_18_plus_historical_corrections",
        "known_limitation": "candidate classifier includes evidence-availability defect; diagnostic attribution only",
        "baseline_generated_sha256": sha(baseline.encode()),
        "capacity_off_generated_sha256": sha(capacity_off.encode()),
        "controlled_generated_sha256": sha(controlled.encode()),
        "baseline_normalized_ast_sha256": sha(normalized_ast(baseline).encode()),
        "capacity_off_normalized_ast_sha256": sha(normalized_ast(capacity_off).encode()),
        "controlled_normalized_ast_sha256": sha(normalized_ast(controlled).encode()),
        "capacity_guards_removed": 2,
    }
    write(output / "identity.json", identity)

    module = types.ModuleType("champion_full_classification_control")
    sys.modules[module.__name__] = module
    exec(compile(controlled, str(output / "capacity-off-plus-classification-generated.py"), "exec"), module.__dict__)
    try:
        module.run()
    except Exception as exc:
        identity["status"] = "FAIL"
        identity["failure"] = f"{type(exc).__name__}: {exc}"
        write(output / "identity.json", identity)
        raise

    identity["status"] = "PASS_FULL_HORIZON_DIAGNOSTIC_NOT_CERTIFIED"
    write(output / "identity.json", identity)
    write(output / "SHA256.json", {
        str(p.relative_to(output)): sha(p.read_bytes())
        for p in sorted(output.rglob("*")) if p.is_file() and p.name != "SHA256.json"
    })
    print(json.dumps(identity, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
