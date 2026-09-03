#!/usr/bin/env python3
"""Exploratory 20-year retained-research replay on a best-effort PIT dataset.

This entrypoint is intentionally not a certification path.  It preserves the
existing causal research mechanics and canonical artifact hash validation while
allowing a canonical dataset whose manifest contains unresolved certification
blockers.  Unknown security types remain ineligible under the strict research
engine.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import backtester.run_research_strict_pit_20y as base


LABEL = "EXPLORATORY_APPROXIMATE_PIT"
_original_dataset = base.strict.CanonicalPITDataset
_original_twenty_year_transform = base.corrected.transformed_source


def _allow_failed_dataset(*args, **kwargs):
    kwargs["require_pass"] = False
    return _original_dataset(*args, **kwargs)


def _exploratory_transform(mode: str, output: Path) -> str:
    text = _original_twenty_year_transform(mode, output)
    needle = "expected_end=os.environ.get('CERTIFICATION_END_SESSION'))"
    replacement = (
        "expected_end=os.environ.get('CERTIFICATION_END_SESSION'), "
        "require_pass=False)"
    )
    count = text.count(needle)
    if count != 1:
        raise RuntimeError(
            f"exploratory canonical require-pass seam changed: expected 1, found {count}"
        )
    return text.replace(needle, replacement, 1)


def _exploratory_strict_main() -> int:
    print(
        "[EXPLORATORY] approximate PIT replay; certification blockers are diagnostics",
        flush=True,
    )
    rc = int(base.strict.corrected.main())
    if rc != 0:
        return rc
    args = os.sys.argv[1:]
    try:
        output = Path(args[args.index("--output") + 1])
    except (ValueError, IndexError):
        raise RuntimeError("exploratory research wrapper requires --output")
    base.strict._write_authority_audit(output)
    return 0


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _finalize_exploratory(output: Path) -> None:
    dataset_root = Path(os.environ["CANONICAL_PIT_DATASET"])
    canonical = json.loads((dataset_root / "manifest.json").read_text(encoding="utf-8"))
    summary_path = output / "summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary["run_classification"] = LABEL
    summary["pit_certified"] = False
    summary["exploratory_universe"] = {
        "definition": (
            "historical Sharadar SEP tape candidates with the retained research "
            "engine's causal listing, liquidity, price and strict-prior common-stock filters"
        ),
        "russell_3000_membership_required": False,
        "known_limitation": (
            "candidate universe is broader than historical Russell 3000 membership; "
            "canonical manifest blockers are retained as diagnostics"
        ),
        "unknown_security_type_policy": "ineligible",
    }
    summary["canonical_manifest_status"] = canonical.get("status")
    summary["canonical_manifest_counts"] = canonical.get("counts") or {}
    summary["canonical_manifest_blockers"] = canonical.get("blockers") or {}
    summary_path.write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    names = [
        "daily.csv.gz",
        "metrics.csv",
        "summary.json",
        "metadata_authority_audit.json",
        "candidate_session_coverage.json",
        "candidate_session_unknown_breakdown.json",
        "canonical_input_session_hashes.csv",
    ]
    members = [output / name for name in names if (output / name).is_file()]
    (output / "SHA256SUMS.txt").write_text(
        "".join(f"{_sha256(path)}  {path.name}\n" for path in members),
        encoding="utf-8",
    )
    counts = canonical.get("counts") or {}
    print(
        f"[{LABEL}] canonical_status={canonical.get('status')} "
        f"unresolved_actions={counts.get('unresolved_corporate_actions', 0)} "
        f"unknown_security_type_observations={counts.get('unknown_security_type_observations', 0)}",
        flush=True,
    )


def main() -> int:
    if "--self-test-imports" in sys.argv[1:]:
        print(f"[SELFTEST PASS] {LABEL} root={ROOT}", flush=True)
        return 0
    if not os.environ.get("CANONICAL_PIT_DATASET"):
        raise RuntimeError("CANONICAL_PIT_DATASET is required")

    base.strict.CanonicalPITDataset = _allow_failed_dataset
    base.corrected.transformed_source = _exploratory_transform
    base.strict.main = _exploratory_strict_main

    print(
        f"[{LABEL}] purpose=go/no-go strategy evaluation certification=false",
        flush=True,
    )
    rc = int(base.main())
    if rc != 0:
        return rc
    args = os.sys.argv[1:]
    try:
        output = Path(args[args.index("--output") + 1])
    except (ValueError, IndexError):
        raise RuntimeError("exploratory 20-year wrapper requires --output")
    _finalize_exploratory(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
