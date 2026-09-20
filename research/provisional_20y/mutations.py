"""Run broken-guard controls in disposable subprocesses, never edit production."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys


TEST = "tests/sentinel/test_provisional_historical_performance.py"
CASES = (
    ("benchmark-boundary", "research.provisional_20y.inputs",
     'scale = Decimal(base[0]["level"]) / (Decimal(prefix[-1]["level"]) * factor)',
     'scale = Decimal(1)',
     "test_partition_rebase_preserves_true_boundary_and_within_partition_returns"),
    ("reconstruction-status", "research.provisional_20y.inputs",
     'if manifest.get("status") != "PASS":', 'if False:',
     "test_manifest_requires_passing_reconstruction_and_exact_bytes"),
    ("member-bytes", "research.provisional_20y.inputs",
     'if len(data) != item["bytes"] or digest != item["sha256"]:', 'if False:',
     "test_manifest_requires_passing_reconstruction_and_exact_bytes"),
    ("complete-schedule", "research.provisional_20y.run",
     'if [r["session"] for r in rows] != expected:', 'if False:',
     "test_incomplete_or_invalid_path_cannot_publish_twenty_year_returns[gap]"),
    ("production-source", "research.provisional_20y.run",
     'if observed != expected:', 'if False:',
     "test_modified_production_source_is_refused"),
)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    baseline = subprocess.run([sys.executable, "-m", "pytest", TEST, "-q", "-p", "no:cacheprovider"],
                              capture_output=True, text=True)
    (args.output / "baseline.log").write_text(baseline.stdout + baseline.stderr, encoding="utf-8")
    if baseline.returncode:
        raise RuntimeError("positive baseline failed")
    results = []
    for name, module, old, new, test in CASES:
        script = "\n".join([
            "import importlib, inspect, pytest",
            f"m=importlib.import_module({module!r})",
            "source=inspect.getsource(m)",
            f"assert source.count({old!r}) == 1",
            f"exec(compile(source.replace({old!r}, {new!r}), m.__file__, 'exec'), m.__dict__)",
            f"raise SystemExit(pytest.main([{(TEST+'::'+test)!r}, '-q', '-p', 'no:cacheprovider']))",
        ])
        result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True)
        (args.output / (name + ".log")).write_text(result.stdout + result.stderr, encoding="utf-8")
        killed = result.returncode == 1 and "1 failed" in result.stdout
        results.append({"guard": name, "killed": killed, "exit": result.returncode})
        if not killed:
            raise RuntimeError("broken guard was not detected: " + name)
    (args.output / "result.json").write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(results), flush=True)


if __name__ == "__main__":
    main()
