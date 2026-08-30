#!/usr/bin/env python3
"""Diagnose the first 20-year prefix-invariance divergence without changing certification semantics."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backtester.run_research_causal_certification import compare_prefix, read_trace


def _run(command: list[str]) -> None:
    subprocess.run(command, cwd=ROOT, check=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--canonical-dataset", type=Path, required=True)
    ap.add_argument("--baseline-trace", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--cutoff", default="2006-08-07")
    args = ap.parse_args()
    out = args.output.resolve()
    normal = out / "normal-prefix"
    control = out / "full-timeline-control"
    out.mkdir(parents=True, exist_ok=True)

    base_cmd = [
        sys.executable,
        "backtester/run_research_causal_single_20y.py",
        "--canonical-dataset", str(args.canonical_dataset.resolve()),
        "--view", "prefix",
        "--cutoff", args.cutoff,
    ]
    _run([*base_cmd, "--output", str(normal)])

    code = r'''
import sys
from pathlib import Path
import backtester.run_research_causal_single_20y as single
original = single.instrument_research_source

def diagnostic_instrument(text):
    source = original(text)
    seam = "    _CANONICAL=CausalPITDataset("
    if source.count(seam) != 1:
        raise RuntimeError("diagnostic expected exactly one canonical dataset seam")
    patch = "    CausalPITDataset._restrict_timeline=lambda self, cutoff: None\n"
    result = source.replace(seam, patch + seam, 1)
    compile(result, "<diagnostic-full-timeline-control>", "exec")
    return result

single.instrument_research_source = diagnostic_instrument
sys.argv = [
    sys.argv[0], "--canonical-dataset", sys.argv[1], "--output", sys.argv[2],
    "--view", "prefix", "--cutoff", sys.argv[3],
]
raise SystemExit(single.main())
'''
    _run([sys.executable, "-c", code, str(args.canonical_dataset.resolve()), str(control), args.cutoff])

    baseline = read_trace(args.baseline_trace.resolve())
    normal_trace = read_trace(normal / "causal-trace.jsonl.gz")
    control_trace = read_trace(control / "causal-trace.jsonl.gz")
    normal_cmp = compare_prefix(baseline, normal_trace, args.cutoff)
    control_cmp = compare_prefix(baseline, control_trace, args.cutoff)
    between_cmp = compare_prefix(control_trace, normal_trace, args.cutoff)
    payload = {
        "schema": "backtester.research-causal-prefix-universe-diagnostic/1",
        "cutoff": args.cutoff,
        "normal_prefix_vs_baseline": normal_cmp,
        "full_timeline_control_vs_baseline": control_cmp,
        "normal_prefix_vs_full_timeline_control": between_cmp,
        "root_cause_confirmed": normal_cmp.get("status") == "FAIL" and control_cmp.get("status") == "PASS",
        "classification": "causal instrumentation/harness defect" if normal_cmp.get("status") == "FAIL" and control_cmp.get("status") == "PASS" else "unresolved",
        "interpretation": (
            "If the strict prefix diverges but the full-timeline control is byte-identical to baseline, "
            "the mismatch is caused by prefix-dependent metadata-universe/index layout rather than future observations or strategy decisions."
        ),
    }
    (out / "diagnosis.json").write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2, sort_keys=True), flush=True)
    return 0 if payload["root_cause_confirmed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
