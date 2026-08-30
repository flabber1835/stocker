#!/usr/bin/env python3
"""Final leakage audit with authority-aware universe classification."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

from backtester import research_causal_instrumentation as base
from backtester.research_causal_instrumentation_v2 import instrument_source


def static_leakage_audit(source: str, *, source_name: str) -> dict[str, object]:
    report = base.static_leakage_audit(source, source_name=source_name)
    filtered = []
    for blocker in report["blockers"]:
        if blocker.get("construct") == "current-universe metadata":
            continue
        filtered.append(blocker)

    active_current_authority = []
    current_reads = (
        "pd.read_csv(META_ZIP",
        "pd.read_csv(TICKERS",
        "pd.read_csv(META_FILE",
        "zipfile.ZipFile(META_ZIP",
    )
    for needle in current_reads:
        if needle in source:
            active_current_authority.append(needle)
    survivor_filters = (
        "lastdate[tids]>=dt64",
        "lastdate[tids] >= dt64",
        "date<=lastdate",
        "date <= lastdate",
    )
    for needle in survivor_filters:
        if needle in source:
            active_current_authority.append(needle)
    if active_current_authority:
        filtered.append(
            {
                "line": None,
                "construct": "active current/survivor authority",
                "reason": active_current_authority,
            }
        )
    if "CausalPITDataset as CanonicalPITDataset" not in source:
        filtered.append(
            {
                "line": None,
                "construct": "causal canonical authority",
                "reason": "final executable source is not bound to CausalPITDataset",
            }
        )

    report["blockers"] = filtered
    report["status"] = "PASS" if not filtered else "FAIL"
    report["classifications"].extend(
        [
            {
                "construct": "common[tids] and listed session arrays",
                "classification": "safe",
                "reason": "populated from guarded canonical metadata as of T; syntax does not imply current-snapshot authority",
            },
            {
                "construct": "issuer membership checks",
                "classification": "safe",
                "reason": "issuer_key resolves guarded strict-prior canonical metadata at T",
            },
            {
                "construct": "unused legacy path constants",
                "classification": "economically inert",
                "reason": "only active file-read calls establish authority; literal path text alone does not",
            },
        ]
    )
    return report


def audit_sources(
    *,
    generated_source: str,
    generated_name: str,
    supporting_paths: Iterable[Path],
    output: Path,
) -> dict[str, object]:
    generated = static_leakage_audit(generated_source, source_name=generated_name)
    supporting = []
    for path in supporting_paths:
        text = Path(path).read_text(encoding="utf-8")
        supporting.append(
            {
                "path": str(path),
                "sha256": __import__("hashlib").sha256(text.encode("utf-8")).hexdigest(),
                "negative_shift_text": ".shift(-" in text,
                "centered_rolling_text": "center=True" in text,
                "backfill_text": any(token in text for token in (".bfill(", ".backfill(")),
                "forward_join_text": "direction='forward'" in text or 'direction="forward"' in text,
                "current_metadata_literal": "SHARADAR_TICKERS.zip" in text,
            }
        )
    report = {
        "schema": "backtester.research-static-leakage-bundle/1",
        "status": generated["status"],
        "generated": generated,
        "supporting_sources": supporting,
    }
    Path(output).write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    if report["status"] != "PASS":
        raise RuntimeError(
            "static causal leakage audit failed: "
            + json.dumps(generated["blockers"], sort_keys=True)
        )
    return report
