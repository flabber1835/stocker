#!/usr/bin/env python3
"""Validate permanent test ownership and refuse new incident-named test files."""
from __future__ import annotations

import argparse
import fnmatch
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
AUTHORITY = ROOT / "tests" / "test-responsibility.json"
REQUIRED_OWNERS = {
    "sentinel.complete",
    "production-champion.regressions",
    "wealth-core.prospective",
    "scripts.operator",
    "host-python38.compatibility",
    "backup.reliability",
    "internal-state.contract",
    "internal-state.campaign",
    "core.infrastructure",
    "sharadar.daily-replay",
    "alpaca.contracts",
    "alpaca.mutations",
}
REQUIRED_SCOPES = {"exact-head", "synthetic-merge"}
INCIDENT_PATTERNS = ("test_pr*.py", "test_issue*.py", "test_review*.py")


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def _resolve(pattern: str) -> list[Path]:
    if any(ch in pattern for ch in "*?["):
        return sorted(ROOT.glob(pattern))
    path = ROOT / pattern
    return [path] if path.exists() else []


def validate(*, base: str | None = None) -> dict:
    authority = json.loads(AUTHORITY.read_text())
    assert authority.get("schema") == "stocker.test-responsibility/1", "invalid responsibility schema"
    owners = authority.get("owners")
    assert isinstance(owners, dict), "missing owner map"
    assert REQUIRED_OWNERS.issubset(owners), "required test owner is missing"

    resolved = {}
    for name, owner in owners.items():
        paths = owner.get("paths")
        scopes = set(owner.get("scopes", []))
        assert isinstance(paths, list) and paths, f"{name}: empty owner path list"
        assert REQUIRED_SCOPES.issubset(scopes), f"{name}: exact/synthetic scope ownership missing"
        matches = []
        for pattern in paths:
            found = _resolve(pattern)
            assert found, f"{name}: owner path resolves to nothing: {pattern}"
            matches.extend(str(path.relative_to(ROOT)) for path in found)
        resolved[name] = sorted(set(matches))

    required_contracts = authority.get("alpaca", {}).get("required_contracts")
    required_mutations = authority.get("alpaca", {}).get("required_mutations")
    assert isinstance(required_contracts, dict) and required_contracts, "missing Alpaca contract authority"
    assert len(required_contracts) == len(set(required_contracts)), "duplicate Alpaca contract id"
    assert all(isinstance(v, str) and v for v in required_contracts.values()), "invalid Alpaca contract selector"
    assert isinstance(required_mutations, list) and required_mutations, "missing Alpaca mutation authority"
    assert len(required_mutations) == len(set(required_mutations)), "duplicate Alpaca mutation id"

    added_incident_tests = []
    if base:
        git("cat-file", "-e", f"{base}^{{commit}}")
        changed = git("diff", "--name-only", "--diff-filter=A", base, "HEAD", "--", "tests")
        for name in filter(None, changed.splitlines()):
            base_name = Path(name).name
            if any(fnmatch.fnmatch(base_name, pattern) for pattern in INCIDENT_PATTERNS):
                added_incident_tests.append(name)
        assert not added_incident_tests, (
            "new incident-named regression files are forbidden; move the regression into its "
            f"permanent behavior owner: {added_incident_tests}"
        )

    return {
        "schema": "stocker.test-responsibility-verdict/1",
        "verdict": "PASS",
        "owners": len(owners),
        "alpaca_contracts": len(required_contracts),
        "alpaca_mutations": len(required_mutations),
        "base": base,
        "added_incident_tests": added_incident_tests,
        "resolved": resolved,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = validate(base=args.base)
    payload = json.dumps(result, sort_keys=True, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload)
    print(payload, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
