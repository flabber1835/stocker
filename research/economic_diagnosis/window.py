"""Passive capture from an unmodified, source-bound historical replay runner."""
from __future__ import annotations

import argparse
import gzip
import hashlib
import importlib
import json
from pathlib import Path
import subprocess
import sys

REPLAY = "7b5dda96ce4235363c5c6ded3974d3fb2970f432"


class ReplayMismatch(BaseException):
    """Do not let the original runner wait for action evidence on a mismatch."""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("harness", "checkpoint", "archive", "sfp", "supplements", "scratch", "output"):
        parser.add_argument("--"+name, type=Path, required=True)
    parser.add_argument("--end", required=True)
    args = parser.parse_args()
    raw = args.checkpoint.read_bytes()
    packet = json.loads(gzip.decompress(raw))
    start = packet["state"]["last_processed_session"]
    args.scratch.mkdir(parents=True, exist_ok=False)
    pointer = dict(path=str(args.checkpoint.resolve()), sha256=hashlib.sha256(raw).hexdigest(),
                   bytes=len(raw), last_session=start)
    (args.scratch/"resume.json").write_text(json.dumps(pointer), encoding="utf-8")
    # The old evidence is immutable; include only its applied actions and future
    # actions from the completed run. The original runner validates this lineage.
    future = json.loads(args.supplements.read_text(encoding="utf-8"))
    selected = list(packet["applied_supplements"].values()) + [r for r in future if r["effective_session"] > start]
    (args.scratch/"supplements.json").write_text(json.dumps(selected), encoding="utf-8")
    expected_raw = subprocess.check_output(["git", "show", f"{REPLAY}:audit/economic-replay-resume-430/accepted-daily.jsonl.gz"])
    expected = {r["date"]: r for r in map(json.loads, gzip.decompress(expected_raw).splitlines())
                if start < r["date"] <= args.end}
    if not expected or max(expected) != args.end:
        raise ValueError("end must be a retained session after checkpoint")
    sys.path[:0] = [str(args.harness.resolve()), str(args.harness.resolve()/"shared")]
    sys.argv = ["passive-window", "--harness", str(args.harness)]
    run = importlib.import_module("research.economic_replay60.run")
    original_sessions = run.JanuaryInputs.sessions
    def bounded(self, after=None):
        for day, rows in original_sessions(self, after):
            if day > args.end:
                break
            yield day, rows
    run.JanuaryInputs.sessions = bounded
    original_advance = run.EconomicPath.advance
    observations = []
    def capture(self, *, previous, state, strategy_prices):
        result = original_advance(self, previous=previous, state=state, strategy_prices=strategy_prices)
        day = state.last_processed_session
        anchor = expected[day]
        if result != anchor["economics"] or state.last_decision != anchor["decision"]:
            raise ReplayMismatch(f"retained economics/decision mismatch on {day}")
        evidence = state.last_evidence
        observations.append(dict(session=day, observation=evidence["observation"],
            leadership=evidence["recent_leadership"], decision=state.last_decision,
            held_count=len(state.wealth_core["episodes"]),
            cash_fraction=state.wealth_core["cash"]/evidence["observation"]["shadow_nav"],
            labels=evidence.get("breadth")))
        # Aggregate labels suffice; do not retain licensed per-security details.
        if isinstance(observations[-1]["labels"], dict):
            observations[-1]["labels"] = {k: v for k, v in observations[-1]["labels"].items() if k != "holdings"}
        return result
    run.EconomicPath.advance = capture
    sys.argv = ["passive-window", "--harness", str(args.harness), "--archive", str(args.archive),
                "--sfp", str(args.sfp), "--output", str(args.scratch/"run"),
                "--supplements", str(args.scratch/"supplements.json"), "--resume", str(args.scratch/"resume.json"),
                "--seconds", "900"]
    run.main()
    if [r["session"] for r in observations] != list(expected):
        raise ReplayMismatch("incomplete or duplicated replay window")
    report = dict(schema="sentinel.passive-window/1", source_binding=packet["binding"],
        checkpoint=pointer, end=args.end, exact_economic_and_decision_pairs=len(observations),
        accepted_daily_sha256=hashlib.sha256(expected_raw).hexdigest(),
        supplement_sha256=hashlib.sha256((args.scratch/"supplements.json").read_bytes()).hexdigest(),
        observations=observations)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(gzip.compress(json.dumps(report, allow_nan=False).encode(), mtime=0))
    print(json.dumps({"checkpoint_session": start, "end": args.end, "exact_pairs": len(observations)}))


if __name__ == "__main__":
    main()
