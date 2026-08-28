#!/usr/bin/env python3
"""A/D v3: v2 causal terminal replay plus frozen primary-source split adjudications.

This launcher is research-only.  Production/main is loaded from the exact pinned
checkout by v2.  The split overlay does not rewrite Sharadar ACTIONS evidence:
it validates the original stated value and frozen SEP-derived witness, then lets
the exact production SplitStreamReconciler return a distinct adjudicated result
for only the frozen event keys.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path


V2_PATH = Path(__file__).with_name("run_sector_ad_causal_terminal_terms_v2.py")
spec = importlib.util.spec_from_file_location("sector_ad_v3_base", V2_PATH)
if spec is None or spec.loader is None:
    raise RuntimeError(f"cannot import {V2_PATH}")
v2 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(v2)

from backtester.causal_split_overrides import (  # noqa: E402
    ADJUDICATED_DISPOSITION,
    SCHEMA as SPLIT_OVERRIDE_SCHEMA,
    install_primary_split_adjudication,
    load_frozen_split_overrides,
)
import stock_strategy_shared.split_reconciliation as split_module  # noqa: E402

runner = v2.runner
runner.EXPERIMENT_ID = "2026-08-27-sector-ad-v3-causal-terminal-splits"

SPLIT_DATA = v2.LAB_ROOT / "backtester" / "data" / "causal-split-overrides-v1.json"
SPLIT_SUMS = v2.LAB_ROOT / "backtester" / "data" / "causal-split-overrides-v1.SHA256"

_real_load_actions = runner.load_actions
_real_load_current_metadata = runner.load_current_metadata
_sessions = None
_authority = None
_overrides = None
_split_digest = None
_real_split_decide = None


def _capture_actions(path, sessions, main):
    global _sessions, _authority
    result = _real_load_actions(path, sessions, main)
    _sessions = tuple(map(str, sessions))
    _authority = result[1]
    return result


def _install_after_metadata(path, main):
    global _overrides, _split_digest, _real_split_decide
    result = _real_load_current_metadata(path, main)
    _meta, _sectors, resolver, _sid_to_ticker = result
    if _sessions is None or _authority is None:
        raise RuntimeError("split adjudication setup ran before ACTIONS/session axis")
    if _overrides is not None:
        raise RuntimeError("split adjudication metadata setup executed more than once")
    _split_digest, _overrides = load_frozen_split_overrides(
        SPLIT_DATA,
        SPLIT_SUMS,
        authority=_authority,
        sessions=_sessions,
        resolve_identity=resolver.resolve,
    )
    _real_split_decide = install_primary_split_adjudication(split_module, _overrides)
    print(
        f"[RUN] frozen causal split adjudications sha256={_split_digest} "
        f"events={len(_overrides)}",
        flush=True,
    )
    return result


runner.load_actions = _capture_actions
runner.load_current_metadata = _install_after_metadata


def _augment_split_provenance() -> None:
    if _split_digest is None or _overrides is None:
        raise RuntimeError("split adjudications were never installed by replay")

    output = v2.OUTPUT
    summary_path = output / "summary.json"
    manifest_path = output / "manifest.json"
    sums_path = output / "SHA256SUMS.txt"
    daily_path = output / "daily.csv.gz"
    metrics_path = output / "metrics.csv"

    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary["causal_split_overrides"] = {
        "schema": SPLIT_OVERRIDE_SCHEMA,
        "sha256": _split_digest,
        "disposition": ADJUDICATED_DISPOSITION,
        "event_count": len(_overrides),
        "events": [
            {
                "ticker": row["ticker"],
                "session": row["effective_session"],
                "security_id": row["security_id"],
                "known_by": row["known_by"],
                "legal_multiplier": row["multiplier"],
                "vendor_stated": row["expected_vendor_stated"],
                "sep_derived": row["expected_sep_derived"],
                "reference": row["reference"],
                "sources": row["sources"],
            }
            for _key, row in sorted(_overrides.items())
        ],
        "vendor_evidence_preserved": True,
        "sep_witness_preserved": True,
        "research_only": True,
    }
    summary_path.write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["experiment"] = runner.EXPERIMENT_ID
    inputs = manifest.setdefault("input_files", {})
    for path in (SPLIT_DATA, SPLIT_SUMS):
        inputs[str(path.relative_to(v2.LAB_ROOT))] = {
            "sha256": v2._sha256(path),
            "bytes": path.stat().st_size,
        }
    manifest["input_files"] = dict(sorted(inputs.items()))
    for path in (daily_path, metrics_path, summary_path):
        manifest.setdefault("outputs", {})[path.name] = {
            "sha256": v2._sha256(path),
            "bytes": path.stat().st_size,
        }
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    files = (daily_path, metrics_path, summary_path, manifest_path)
    sums_path.write_text(
        "".join(f"{v2._sha256(path)}  {path.name}\n" for path in files),
        encoding="utf-8",
    )


def main() -> int:
    global _real_split_decide
    try:
        rc = int(v2.main())
        if rc != 0:
            return rc
        _augment_split_provenance()
        print(
            "[PASS] A/D v3 causal terminal + primary split adjudication provenance recorded",
            flush=True,
        )
        return 0
    finally:
        if _real_split_decide is not None:
            split_module.SplitStreamReconciler.decide = _real_split_decide
            _real_split_decide = None


if __name__ == "__main__":
    raise SystemExit(main())
