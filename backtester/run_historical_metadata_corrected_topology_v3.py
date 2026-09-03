#!/usr/bin/env python3
"""Run the corrected-topology bridge with a Python-3.12-safe pinned-module loader."""
from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path

from backtester import rebuild_historical_metadata_identity_topology_v3 as base


def _load_registered(path: Path):
    name = "corrected_strict_pit_metadata"
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import corrected identity source: {path}")
    module = importlib.util.module_from_spec(spec)
    # Python 3.12 dataclasses resolve annotations through sys.modules while the
    # class decorator runs. A dynamically executed module must therefore be
    # registered before exec_module(), exactly as normal import machinery does.
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(name, None)
        raise
    required = (
        "_price_dates",
        "_cik_changes",
        "_changes_as_of",
        "_terminal_identity_evidence",
        "_identity_boundary_classification",
        "_sid",
        "IDENTITY_AUTHORITY",
    )
    missing = [attr for attr in required if not hasattr(module, attr)]
    if missing:
        raise RuntimeError(f"corrected identity source missing API: {missing}")
    return module


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--identity-source-root", type=Path, required=True)
    parser.add_argument("--identity-source-sha", required=True)
    parser.add_argument("--v2-root", type=Path, required=True)
    parser.add_argument("--v3-candidate-root", type=Path, required=True)
    parser.add_argument("--v3-authority-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    base.load_corrected_identity_module = _load_registered
    summary = base.main_rebuild(
        identity_source_root=args.identity_source_root,
        identity_source_sha=args.identity_source_sha,
        v2_root=args.v2_root,
        v3_candidate_root=args.v3_candidate_root,
        v3_authority_root=args.v3_authority_root,
        output=args.output,
    )
    import json
    print(json.dumps(summary, indent=2, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
