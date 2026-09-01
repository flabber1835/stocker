#!/usr/bin/env python3
"""Run one V2 SEC CIK shard with exact live GitHub progress and fail-closed status."""
from __future__ import annotations

import argparse
import builtins
import json
import re
from pathlib import Path

from backtester import enforce_historical_metadata_type_authority_v2 as type_policy
from backtester import historical_metadata_reconstruction_v2 as base

SCHEMA = "backtester.historical-metadata-reconstruction-v2.web-shard-runner/1"
WEB_RE = re.compile(r"^\[WEB\]\s+ciks=(\d+)/(\d+)\s+attempts=(\d+)\s+successes=(\d+)\s+retries=(\d+)\s+failures=(\d+)")


def _source_count(output: Path) -> int:
    path = output / "web_source_manifest.csv.gz"
    if not path.exists():
        return 0
    try:
        return len(base.read_gzip_csv(path))
    except Exception:
        return 0


def run(args: argparse.Namespace) -> dict:
    output: Path = args.output
    output.mkdir(parents=True, exist_ok=True)
    original_print = builtins.print

    def progress_print(*values, **kwargs):
        text = " ".join(str(value) for value in values)
        original_print(*values, **kwargs)
        match = WEB_RE.match(text)
        if not match:
            return
        done, total, attempts, successes, retries, failures = (int(x) for x in match.groups())
        pct = 100.0 if total == 0 else done * 100.0 / total
        original_print(
            f"[PROGRESS] shard={args.shard_label} ciks={done}/{total} pct={pct:.1f}% "
            f"http_attempts={attempts} successes={successes} retries={retries} "
            f"failures={failures} retained_source_objects={_source_count(output)}",
            flush=True,
        )

    # historical_metadata_reconstruction_v2 resolves the global name `print` at
    # runtime; installing this module-global wrapper preserves every original
    # line and adds the required percentage line without duplicating the fetcher.
    base.print = progress_print
    try:
        result = base.fetch_web_fallback(
            args.plan,
            output,
            args.source_sha,
            args.canonical_hash,
            args.candidates_sha,
            args.parser_sha,
            args.min_interval,
            args.max_runtime,
            not args.no_resume,
            args.probe_limit,
        )
    finally:
        try:
            delattr(base, "print")
        except AttributeError:
            pass

    # 404/410 are explicit terminal source absence, not transport incompleteness.
    # They remain counted and auditable; unresolved metadata remains fail-closed
    # later in the timeline/admission gate.
    technical_failures = list(result.get("failures") or [])
    if bool(result.get("complete")) and not technical_failures:
        result["status"] = "PASS"
        result["transport_complete"] = True
        result["terminal_source_absences"] = int((result.get("transport") or {}).get("terminal_absences", 0))
        result["source_absence_policy"] = "404/410 retained as terminal source absence; never converted into positive metadata evidence"
    else:
        result["status"] = "PARTIAL"
        result["transport_complete"] = False

    coverage_path = output / "web_coverage.json"
    coverage_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    base.write_checksums(output, exclude={".http-cache"})

    if result["status"] != "PASS":
        original_print(json.dumps(result, indent=2, sort_keys=True), flush=True)
        raise base.ReconstructionError("SEC web shard did not complete transport-cleanly")

    filtered = type_policy.filter_web(output)
    verified = base.verify_checksums(output)
    final = {
        "schema": SCHEMA,
        "status": "PASS",
        "shard": args.shard_label,
        "web": filtered,
        "verified": verified,
        "checkpoint_sha256": base.sha256_file(output / "checkpoint.json"),
        "retained_source_objects": _source_count(output),
    }
    original_print(
        f"[PROGRESS] shard={args.shard_label} ciks={result.get('completed_unique_ciks', 0)}/"
        f"{result.get('planned_unique_ciks', 0)} pct=100.0% status=PASS "
        f"retained_source_objects={final['retained_source_objects']} checkpoint={final['checkpoint_sha256']}",
        flush=True,
    )
    (output / "shard_runner_coverage.json").write_text(json.dumps(final, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    base.write_checksums(output, exclude={".http-cache"})
    return final


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--canonical-hash", required=True)
    parser.add_argument("--candidates-sha", required=True)
    parser.add_argument("--parser-sha", required=True)
    parser.add_argument("--shard-label", default="probe")
    parser.add_argument("--min-interval", type=float, default=0.5)
    parser.add_argument("--max-runtime", type=float, default=3300.0)
    parser.add_argument("--probe-limit", type=int, default=0)
    parser.add_argument("--no-resume", action="store_true")
    args = parser.parse_args()
    result = run(args)
    print(json.dumps(result, indent=2, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
