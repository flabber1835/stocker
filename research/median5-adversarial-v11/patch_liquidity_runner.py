#!/usr/bin/env python3
"""Patch frozen experiment runner for stricter-liquidity traversal validation."""
from pathlib import Path
import argparse

OLD = '''    if summary.get("strict_security_type_counts") != EXPECTED_SECURITY_COUNTS:\n        raise RuntimeError("security-type traversal differs from certified baseline")\n    coverage = summary.get("strict_candidate_security_type_coverage") or {}\n    for key, expected in EXPECTED_CANDIDATE_COVERAGE.items():\n        if coverage.get(key) != expected:\n            raise RuntimeError(f"candidate classification coverage changed for {key}: {coverage.get(key)} != {expected}")\n'''

NEW = '''    counts = summary.get("strict_security_type_counts") or {}\n    coverage = summary.get("strict_candidate_security_type_coverage") or {}\n    if "LIQ_" in args.arm:\n        if set(counts) != set(EXPECTED_SECURITY_COUNTS):\n            raise RuntimeError(f"unexpected security-type accounting keys: {sorted(counts)}")\n        if any(not isinstance(v, int) or v < 0 for v in counts.values()):\n            raise RuntimeError(f"invalid security-type accounting values: {counts}")\n        for key, baseline_value in EXPECTED_SECURITY_COUNTS.items():\n            if counts[key] > baseline_value:\n                raise RuntimeError(f"liquidity stress increased {key} traversal: {counts[key]} > {baseline_value}")\n        if coverage.get("sessions") != EXPECTED_CANDIDATE_COVERAGE["sessions"]:\n            raise RuntimeError(f"classification session coverage changed: {coverage.get('sessions')}")\n        if coverage.get("sessions_with_unknown") != EXPECTED_CANDIDATE_COVERAGE["sessions_with_unknown"]:\n            raise RuntimeError(f"unknown-classification session coverage changed: {coverage.get('sessions_with_unknown')}")\n        traversed = sum(counts.values())\n        if coverage.get("base_candidates") != traversed:\n            raise RuntimeError(f"classification accounting does not close: {coverage.get('base_candidates')} != {traversed}")\n        known = counts["auto_common"] + counts["manual_common"] + counts["manual_non_common"]\n        if coverage.get("known_classifications") != known:\n            raise RuntimeError(f"known-classification accounting does not close: {coverage.get('known_classifications')} != {known}")\n        if coverage.get("unknown_classifications") != counts["unknown_ineligible"]:\n            raise RuntimeError("unknown-classification accounting does not close")\n        if coverage.get("base_candidates", 0) >= EXPECTED_CANDIDATE_COVERAGE["base_candidates"]:\n            raise RuntimeError("liquidity stress did not bind the candidate traversal")\n    else:\n        if counts != EXPECTED_SECURITY_COUNTS:\n            raise RuntimeError("security-type traversal differs from certified baseline")\n        for key, expected in EXPECTED_CANDIDATE_COVERAGE.items():\n            if coverage.get(key) != expected:\n                raise RuntimeError(f"candidate classification coverage changed for {key}: {coverage.get(key)} != {expected}")\n'''


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("path", type=Path)
    args = ap.parse_args()
    text = args.path.read_text()
    if text.count(OLD) != 1:
        raise RuntimeError(f"expected exactly one frozen validation block, got {text.count(OLD)}")
    patched = text.replace(OLD, NEW, 1)
    compile(patched, str(args.path), "exec")
    args.path.write_text(patched)
    print("PASS Median-5 liquidity traversal validation patch applied exactly once")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
