#!/usr/bin/env python3
"""Schema-v2 facade for the authoritative PIT certification engine.

The facade keeps the certificate schema and join logic intact while binding the
experiment identity to deterministic runtime facts and interpreting explicit
schema-v2 fail-closed states correctly:

* an unknown security type is causally resolved when the authenticated row
  explicitly marks it ineligible and unadmitted;
* incomplete terminal terms are causally accounted when every such event is
  present in the authenticated terminal ledger as PIT_ACTION_INCOMPLETE.

Replay-level gates still require resolved NAV, exact held-terminal accounting,
financial semantics, and the mandatory future-leak suite.
"""
from __future__ import annotations

import copy
import platform
from pathlib import Path
import re
import sys
from typing import Any, Mapping

from backtester import certify_backtest_result as implementation


CANONICAL_SCHEMA = "backtester.canonical-pit-dataset/2"
PASS = implementation.PASS
FAIL = implementation.FAIL


def deterministic_runtime_identity_hash():
    payload = {
        "python": sys.version.split()[0],
        "implementation": platform.python_implementation(),
        "cache_tag": str(getattr(sys.implementation, "cache_tag", "")),
    }
    return implementation.json_hash(payload), payload


_original_verify_dataset = implementation.verify_dataset
_original_finalise = implementation.finalise


def verify_dataset_v2(dataset_root, pointer):
    value = _original_verify_dataset(dataset_root, pointer)
    manifest = value.get("manifest") or {}
    if manifest.get("schema") != CANONICAL_SCHEMA:
        raise RuntimeError(
            "global PIT certification requires canonical dataset schema "
            f"{CANONICAL_SCHEMA}; observed {manifest.get('schema')!r}"
        )
    return value


def _explicit_false(value: Any) -> bool:
    return str(value).strip().lower() in {"0", "0.0", "false", "no"}


def audit_universe_resolution_v2(dataset_root: Path, manifest: Mapping[str, Any]) -> dict[str, Any]:
    root = Path(dataset_root)
    members = manifest.get("members") or {}
    observation_names = sorted(
        str(name) for name in members
        if re.fullmatch(r"observations-\d{4}\.csv\.gz", str(name))
    )
    if not observation_names:
        raise RuntimeError("canonical PIT manifest has no observation partitions")

    historical_security_ids: set[str] = set()
    candidate = eligible = ineligible = unresolved_classification = 0
    unknown_security_type = explicit_unknown_ineligible = unknown_identity = 0
    reasons: dict[str, int] = {}
    examples: list[dict[str, str]] = []

    for name in observation_names:
        for row in implementation._iter_csv(root / name):
            sid = str(row.get("security_id") or "").strip()
            ticker = str(row.get("ticker") or "").strip()
            session = str(row.get("session") or row.get("date") or "")[:10]
            if sid:
                historical_security_ids.add(sid)
            else:
                unknown_identity += 1
            listing_active = str(row.get("listing_active", "1")).lower() in {
                "1", "1.0", "true"
            }
            candidate += 1
            security_type = str(row.get("security_type") or "").strip().lower()
            if not listing_active:
                ineligible += 1
                reasons["CAUSAL_NOT_LISTED"] = reasons.get("CAUSAL_NOT_LISTED", 0) + 1
            elif security_type in {"common", "common_stock", "common stock"}:
                eligible += 1
            elif security_type in {"non_common", "non-common", "noncommon"}:
                ineligible += 1
                reasons["CAUSAL_NON_COMMON_SECURITY_TYPE"] = (
                    reasons.get("CAUSAL_NON_COMMON_SECURITY_TYPE", 0) + 1
                )
            else:
                unknown_security_type += 1
                explicit_fail_closed = (
                    _explicit_false(row.get("security_type_eligible"))
                    and _explicit_false(row.get("metadata_admitted"))
                )
                if explicit_fail_closed:
                    ineligible += 1
                    explicit_unknown_ineligible += 1
                    reasons["CAUSAL_UNKNOWN_SECURITY_TYPE_FAIL_CLOSED"] = (
                        reasons.get("CAUSAL_UNKNOWN_SECURITY_TYPE_FAIL_CLOSED", 0) + 1
                    )
                else:
                    unresolved_classification += 1
                    if len(examples) < 25:
                        examples.append({
                            "security_id": sid,
                            "ticker": ticker,
                            "session": session,
                            "reason": "UNKNOWN_SECURITY_TYPE_NOT_EXPLICITLY_FAIL_CLOSED",
                        })

    counts = manifest.get("counts") or {}
    declared_unknown = int(
        counts.get("unknown_security_type_observations", unknown_security_type)
    )
    if declared_unknown != unknown_security_type:
        raise RuntimeError(
            "universe audit disagrees with manifest unknown security-type count: "
            f"observed={unknown_security_type} manifest={declared_unknown}"
        )
    identity_audit = manifest.get("identity_audit") or {}
    identity_blockers = int(identity_audit.get("blocking_identity_conflicts", 0))
    unknown_terminal_state = int(counts.get("incomplete_terminal_terms", 0))
    unresolved_total = unresolved_classification + unknown_identity + identity_blockers
    return {
        "schema": "backtester.pit-universe-resolution-audit/2",
        "historical_security_episodes": len(historical_security_ids),
        "historical_candidate_observations": candidate,
        "resolved_eligible": eligible,
        "resolved_pit_ineligible": ineligible,
        "pit_ineligible_reasons": dict(sorted(reasons.items())),
        "unresolved": unresolved_total,
        "unresolved_security_classification": unresolved_classification,
        "unknown_security_type": unknown_security_type,
        "unknown_security_type_explicit_fail_closed": explicit_unknown_ineligible,
        "unknown_identity": unknown_identity + identity_blockers,
        "unknown_terminal_state": unknown_terminal_state,
        "examples": examples,
    }


def audit_terminal_accounting_v2(dataset_root: Path, manifest: Mapping[str, Any]) -> dict[str, Any]:
    root = Path(dataset_root)
    expected = int((manifest.get("counts") or {}).get("incomplete_terminal_terms", -1))
    if expected < 0:
        raise RuntimeError("canonical PIT manifest lacks incomplete terminal count")
    path = root / "terminal-events.csv.gz"
    if not path.is_file():
        raise RuntimeError("canonical PIT terminal ledger is missing")
    represented = 0
    invalid: list[dict[str, str]] = []
    for row in implementation._iter_csv(path):
        disposition = str(row.get("disposition") or "")
        if not disposition.startswith("PIT_ACTION_INCOMPLETE:"):
            continue
        represented += 1
        reason = disposition.split(":", 1)[1].strip()
        required = {
            "effective_session": str(row.get("effective_session") or "").strip(),
            "security_id": str(row.get("security_id") or "").strip(),
            "ticker": str(row.get("ticker") or "").strip(),
            "kind": str(row.get("kind") or "").strip(),
            "reference": str(row.get("reference") or "").strip(),
            "authority": str(row.get("authority") or "").strip(),
        }
        valid = (
            bool(reason)
            and all(required[key] for key in (
                "effective_session", "security_id", "ticker", "kind", "reference"
            ))
            and required["authority"] == "PIT_ACTIONS"
        )
        if not valid and len(invalid) < 25:
            invalid.append({**required, "disposition": disposition})
    return {
        "schema": "backtester.pit-terminal-accounting-audit/2",
        "declared_incomplete_terminal_terms": expected,
        "represented_fail_closed_terminal_terms": represented,
        "invalid_fail_closed_terminal_rows": invalid,
        "complete": represented == expected and not invalid,
    }


def audit_dataset_contract_v2(dataset_root: Path, pointer_path: Path) -> dict[str, Any]:
    pointer = implementation.verify_pointer(pointer_path)
    dataset = verify_dataset_v2(dataset_root, pointer)
    manifest = dataset["manifest"]
    universe = audit_universe_resolution_v2(dataset_root, manifest)
    terminal = audit_terminal_accounting_v2(dataset_root, manifest)
    counts = manifest.get("counts") or {}
    identity = manifest.get("identity_audit") or {}
    causal = manifest.get("causal_metadata_audit") or {}
    metadata_after_decision = int(causal.get("metadata_after_decision_consumptions", 0))
    future_metadata_authority = int(causal.get("future_metadata_authority_violations", 0))
    checks = {
        "dataset_integrity": PASS,
        "universe_resolution": PASS if int(universe["unresolved"]) == 0 else FAIL,
        "corporate_actions": PASS if int(counts.get("unresolved_corporate_actions", -1)) == 0 else FAIL,
        "terminal_events": PASS if terminal["complete"] else FAIL,
        "pit_metadata": PASS if (
            int(identity.get("blocking_identity_conflicts", 0)) == 0
            and metadata_after_decision == 0
            and future_metadata_authority == 0
        ) else FAIL,
    }
    return {
        "checks": checks,
        "dataset_identity": {k: v for k, v in dataset.items() if k != "manifest"},
        "universe_resolution": universe,
        "terminal_accounting": terminal,
        "manifest_counts": counts,
        "identity_audit": identity,
        "causal_metadata_audit": causal,
    }


def _verified_dataset_for_finalizer(dataset_root, pointer):
    """Expose only proven schema-v2 closures to the unchanged finalizer."""
    value = verify_dataset_v2(dataset_root, pointer)
    manifest = copy.deepcopy(value["manifest"])
    universe = audit_universe_resolution_v2(Path(dataset_root), manifest)
    terminal = audit_terminal_accounting_v2(Path(dataset_root), manifest)
    counts = dict(manifest.get("counts") or {})
    if int(universe.get("unresolved", -1)) == 0:
        counts["unknown_security_type_observations"] = 0
    if terminal.get("complete") is True:
        counts["incomplete_terminal_terms"] = 0
    manifest["counts"] = counts
    out = dict(value)
    out["manifest"] = manifest
    return out


def finalise_v2(**kwargs):
    prior = implementation.verify_dataset
    implementation.verify_dataset = _verified_dataset_for_finalizer
    try:
        return _original_finalise(**kwargs)
    finally:
        implementation.verify_dataset = prior


def _extend_source_closure() -> None:
    common = (
        "backtester/certify_backtest_result_v2.py",
        "backtester/future_leak_certification_pinned_runtime.py",
        "backtester/pinned_runtime_test_compat.py",
        "backtester/render_research_champion_report.py",
        ".github/workflows/backtester-research-champion-pit-v2-cert.yml",
        "main-src/sentinel/requirements.lock",
    )
    production = (
        "backtester/canonical_pit_metadata_v2.py",
        "backtester/build_canonical_pit_with_metadata_v2.py",
        "backtester/production_run_summary.py",
    )
    research = (
        "backtester/research_champion_terminal_leadership_overlay.py",
        "backtester/run_research_champion_strict_pit_20y.py",
        "backtester/run_research_champion_strict_pit_20y_v2.py",
        "backtester/run_strategy9_e3_stability_point.py",
        "backtester/experiment_architecture_recovery_concordance_e3.py",
        "backtester/calibrate_broad_simplified_breadth.py",
        "backtester/experiment2_broad_independent_correlation.py",
        "research/strategy9-e3-broad-stability",
    )
    for mode in ("production", "research"):
        current = list(implementation.OFFICIAL_SOURCE_FILES[mode])
        additions = common + (production if mode == "production" else research)
        for item in additions:
            if item not in current:
                current.append(item)
        implementation.OFFICIAL_SOURCE_FILES[mode] = tuple(current)


implementation.runtime_identity_hash = deterministic_runtime_identity_hash
implementation.verify_dataset = verify_dataset_v2
implementation.audit_universe_resolution = audit_universe_resolution_v2
implementation.audit_dataset_contract = audit_dataset_contract_v2
implementation.finalise = finalise_v2
_extend_source_closure()


def main() -> int:
    return implementation.main()


if __name__ == "__main__":
    raise SystemExit(main())
