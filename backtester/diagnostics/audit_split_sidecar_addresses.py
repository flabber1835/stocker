#!/usr/bin/env python3
"""Enumerate causal split sidecar filename/content SHA-256 mismatches."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "data" / "causal-split-overrides-v1.d"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def main() -> int:
    rows = []
    for path in sorted(ROOT.glob("*.json")):
        expected = path.stem.rsplit("_", 1)[-1]
        observed = sha256(path)
        if expected != observed:
            rows.append({"path": str(path), "expected": expected, "observed": observed})
    print(json.dumps({"sidecars": len(list(ROOT.glob('*.json'))), "mismatches": rows, "mismatch_count": len(rows)}, indent=2, sort_keys=True))
    return 1 if rows else 0


if __name__ == "__main__":
    raise SystemExit(main())
