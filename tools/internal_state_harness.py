#!/usr/bin/env python3
"""Run or exactly replay the composed internal-state lab (requires local PostgreSQL)."""
from __future__ import annotations

import argparse
import hashlib
from importlib.metadata import version
import json
from pathlib import Path
import platform
import subprocess
import sys
import tempfile
import traceback

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "shared")]

from tests.internal_state.contract import InvariantFailure, Trace, reduce_trace
from tests.internal_state.runtime import Lifecycle, plain, write
from tests.internal_state.scenarios import catalogue, generated


def source_identity():
    def git(*args):
        return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()
    return {"commit": git("rev-parse", "HEAD"), "tree": git("rev-parse", "HEAD^{tree}"),
        "tracked_dirty": bool(git("status", "--porcelain", "--untracked-files=no")),
        "python": platform.python_version(),
        "dependencies": {name: version(name) for name in
            ("psycopg", "httpx", "exchange_calendars", "pandas", "numpy", "pydantic", "pytest")},
        "locks": {path: hashlib.sha256((ROOT / path).read_bytes()).hexdigest()
                  for path in ("sentinel/requirements.lock", "tests/requirements.lock")},
        "authority": "synthetic model; no deployment or broker capability certification"}


def run_trace(trace, output):
    output.mkdir(parents=True, exist_ok=False)
    write(output / "trace.json", trace.envelope())
    report = source_identity() | {"verdict": "FAIL", "scenario": trace.name,
        "profile": trace.profile, "seed": trace.seed, "replay": f"python tools/internal_state_harness.py --replay {output / 'trace.json'} --output NEW_DIRECTORY"}
    lifecycle = Lifecycle(trace, output)
    try:
        with lifecycle:
            report["postgres"] = lifecycle.cluster.sql("SHOW server_version")[0]
            report["strategy_identity"] = lifecycle.identity
            report.update(lifecycle.run())
            report["verdict"] = "PASS"
    except BaseException as exc:
        report["error"] = {"type": type(exc).__name__, "detail": str(exc),
                           "index": lifecycle.action_index, "traceback": traceback.format_exc()}
        if isinstance(exc, InvariantFailure):
            report["error"].update(invariant=exc.invariant, index=exc.index,
                                   expected=plain(exc.expected), actual=plain(exc.actual))
        raise
    finally:
        report["coverage"] = sorted(lifecycle.coverage)
        write(output / "provider-transcript.json", lifecycle.provider.transcript)
        write(output / "report.json", report)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--scenario", action="append")
    parser.add_argument("--seeds", type=int, default=16)
    parser.add_argument("--seed-start", type=int, default=0)
    parser.add_argument("--replay", type=Path)
    parser.add_argument("--minimize", action="store_true")
    parser.add_argument("--shard", type=int, default=0)
    parser.add_argument("--shards", type=int, default=1)
    args = parser.parse_args(argv)
    if not (0 <= args.seeds <= 4096 and 0 <= args.seed_start < 2**32
            and 0 <= args.shard < args.shards <= 64):
        parser.error("invalid campaign budget or shard")
    if args.output.exists():
        parser.error("output must be new; prior evidence cannot satisfy this run")
    selected = [Trace.decode(json.loads(args.replay.read_text()))] if args.replay else [
        *catalogue(), *(generated(s) for s in range(args.seed_start, args.seed_start + args.seeds))]
    if args.scenario:
        missing = set(args.scenario) - {t.name for t in selected}
        if missing:
            parser.error(f"unknown scenarios: {sorted(missing)}")
        selected = [t for t in selected if t.name in args.scenario]
    selected = [t for i, t in enumerate(selected) if i % args.shards == args.shard]
    if not selected:
        parser.error("empty campaign")
    args.output.mkdir(parents=True)
    reports = []
    failures = []
    for trace in selected:
        path = args.output / (trace.name + "-" + trace.profile)
        try:
            reports.append(run_trace(trace, path))
        except BaseException as exc:
            failures.append({"scenario": trace.name, "profile": trace.profile, "error": str(exc)})
            print(traceback.format_exc(), flush=True)
            if args.minimize and isinstance(exc, InvariantFailure):
                try:
                    def replay(candidate):
                        with tempfile.TemporaryDirectory(prefix="state_reducer_") as root:
                            return run_trace(candidate, Path(root) / "run")
                    reduced, evidence = reduce_trace(trace, replay, exc.invariant)
                    write(path / "reduced-trace.json", reduced.envelope())
                    write(path / "reduction.json", evidence)
                except Exception as reduction_error:
                    write(path / "reduction-error.json", {"error": repr(reduction_error)})
            # A broken fixture should not start dozens of expensive clusters.
            if not isinstance(exc, InvariantFailure):
                break
    write(args.output / "campaign.json", source_identity() | {
        "verdict": "FAIL" if failures or len(reports) != len(selected) else "PASS",
        "planned": [t.name + "-" + t.profile for t in selected],
        "completed": [r["scenario"] + "-" + r["profile"] for r in reports],
        "failures": failures, "shard": args.shard, "shards": args.shards,
        "coverage": sorted({c for r in reports for c in r["coverage"]})})
    return int(bool(failures) or len(reports) != len(selected))


if __name__ == "__main__":
    raise SystemExit(main())
