#!/usr/bin/env python3
"""Diagnose the first 20-year prefix-invariance divergence without weakening certification."""
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


def _control(dataset: Path, output: Path, cutoff: str, patch: str, label: str) -> None:
    code = r'''
import sys
import backtester.run_research_causal_single_20y as single
original = single.instrument_research_source
PATCH = sys.argv[4]
LABEL = sys.argv[5]

def diagnostic_instrument(text):
    source = original(text)
    seam = "    _CANONICAL=CausalPITDataset("
    if source.count(seam) != 1:
        raise RuntimeError("diagnostic expected exactly one canonical dataset seam")
    result = source.replace(seam, PATCH + "\n" + seam, 1)
    compile(result, f"<diagnostic-{LABEL}>", "exec")
    return result
single.instrument_research_source = diagnostic_instrument
sys.argv = [sys.argv[0], "--canonical-dataset", sys.argv[1], "--output", sys.argv[2], "--view", "prefix", "--cutoff", sys.argv[3]]
raise SystemExit(single.main())
'''
    _run([sys.executable, "-c", code, str(dataset.resolve()), str(output), cutoff, patch, label])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--canonical-dataset", type=Path, required=True)
    ap.add_argument("--baseline-trace", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--cutoff", default="2006-08-07")
    args = ap.parse_args()
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=True)
    normal = out / "normal-prefix"
    base_cmd = [sys.executable, "backtester/run_research_causal_single_20y.py", "--canonical-dataset", str(args.canonical_dataset.resolve()), "--view", "prefix", "--cutoff", args.cutoff]
    _run([*base_cmd, "--output", str(normal)])

    controls = {
        "full-timeline": "    CausalPITDataset._restrict_timeline=lambda self, cutoff: None",
        "full-observations": "    CausalPITDataset.observations=lambda self, year: CausalPITDataset.__mro__[1].observations(self, year)",
        "full-sessions-for-funds": """    _DIAG_INIT=CausalPITDataset.__init__
    def _diag_init(self,*a,**kw):
        _DIAG_INIT(self,*a,**kw)
        self.sessions=self._immutable_sessions
    CausalPITDataset.__init__=_diag_init""",
        "full-timeline-and-observations": """    CausalPITDataset._restrict_timeline=lambda self, cutoff: None
    CausalPITDataset.observations=lambda self, year: CausalPITDataset.__mro__[1].observations(self, year)""",
    }
    baseline = read_trace(args.baseline_trace.resolve())
    comparisons = {"normal-prefix": compare_prefix(baseline, read_trace(normal / "causal-trace.jsonl.gz"), args.cutoff)}
    for label, patch in controls.items():
        target = out / label
        _control(args.canonical_dataset, target, args.cutoff, patch, label)
        comparisons[label] = compare_prefix(baseline, read_trace(target / "causal-trace.jsonl.gz"), args.cutoff)

    passing_controls = sorted(k for k,v in comparisons.items() if k != "normal-prefix" and v.get("status") == "PASS")
    payload = {
        "schema": "backtester.research-causal-prefix-surface-diagnostic/2",
        "cutoff": args.cutoff,
        "comparisons": comparisons,
        "passing_controls": passing_controls,
        "root_cause_surface_isolated": bool(passing_controls),
        "classification": "causal instrumentation/harness defect" if passing_controls else "unresolved",
        "interpretation": "A passing control identifies a prefix read-surface transformation that changes historical numerical trace bytes; no certification gate is waived by this diagnostic.",
    }
    (out / "diagnosis.json").write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2, sort_keys=True), flush=True)
    return 0 if passing_controls else 2

if __name__ == "__main__":
    raise SystemExit(main())
