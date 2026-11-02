"""Offline canonical baseline prefix review; reads only stopped worker output."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from research.pooled_vacancy_funding import backtest, runtime
from research.pooled_vacancy_funding.journal import Journal, read_checkpoint
from research.pooled_input_support import bundle

POLICY = "wealth-core-v5-zero-share-fixed-2008-v1"


def require(value, code):
    if not value:
        raise ValueError(code)


def compare_prefix(actual: Path, expected: Path, count: int, *, phase='FORMATION') -> str:
    require(phase in {'FORMATION','MEASURED'},'REFUSED_COMPARISON_PHASE')
    digest = hashlib.sha256()
    with actual.open("rb") as new, expected.open("rb") as old:
        for _ in range(count):
            left, right = new.readline(), old.readline()
            require(left and left == right, "REFUSED_CANONICAL_FORMATION_RECORD")
            row = json.loads(left)
            require(row["phase"] == phase, "REFUSED_PREFIX_PHASE")
            digest.update(left)
        require(not new.read(1), "REFUSED_EXTRA_PREFIX_RECORD")
    return digest.hexdigest()


def review(actual: Path, expected: Path) -> dict:
    before = {p.name: backtest.file_sha(p) for p in actual.glob("*.jsonl")}
    prefix_sha = compare_prefix(actual/"formation.jsonl", expected/"formation.jsonl", 32)
    saved = read_checkpoint(actual/"checkpoint.json.gz")
    require(saved["source_cursor"] == "2007-10-05" and saved["completed"] == 0,
            "REFUSED_PREFIX_AXIS")
    require(saved["base"]["policy"] == POLICY and not saved["repairs"],
            "REFUSED_PREFIX_POLICY_OR_REPAIR")
    full_axis = bundle.axis()
    axis = full_axis[full_axis.index(backtest.START)-425:]
    backtest.validate_checkpoint(saved, saved["base"], axis)
    restored = runtime.restore(saved["run"], policy=POLICY,
                               input_sha256=backtest.input_hash(saved["base"], []))
    require(runtime.checkpoint(restored) == saved["run"], "REFUSED_CANONICAL_ROUNDTRIP")
    journal = Journal(actual, resume=True)
    try:
        journal.verify(saved["journals"])
    finally:
        journal.close()
    for name, commitment in saved["journals"].items():
        require((actual/(name+".jsonl")).stat().st_size == commitment["bytes"],
                "REFUSED_PREFIX_TAIL")
    require({p.name:backtest.file_sha(p) for p in actual.glob("*.jsonl")} == before,
            "REFUSED_REVIEW_MUTATED_JOURNAL")
    return dict(schema="research.capital-risk-prefix-review/1", status="PREFIX_PASSED",
                formation_records=32, measured_closes=0, session="2007-10-05",
                exact_records_sha256=prefix_sha, checkpoint_sha256=saved["sha256"],
                canonical_roundtrip=True, journals_verified=4, tails=0,
                zero_transition_restore_preserved_journals=True,
                full_baseline_gate_satisfied=False)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--actual",required=True,type=Path)
    parser.add_argument("--expected",required=True,type=Path)
    parser.add_argument("--output",required=True,type=Path)
    args=parser.parse_args()
    args.output.write_text(json.dumps(review(args.actual,args.expected),indent=2)+"\n")
    print("PREFIX_PASSED")


if __name__=="__main__": main()
