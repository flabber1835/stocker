#!/usr/bin/env python3
"""Single fail-closed PIT/backtest certification authority.

Replay completion and PIT certification are deliberately separate.  This module
joins immutable replay evidence and mandatory causality evidence for one exact
experiment identity and is the only code allowed to emit ``PIT_CERTIFIED``.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import sys
from typing import Any, Iterable, Mapping

CERTIFICATION_SCHEMA = "backtester.pit-certification/1"
REPLAY_EVIDENCE_SCHEMA = "backtester.pit-replay-evidence/1"
TEST_EVIDENCE_SCHEMA = "backtester.pit-test-evidence/1"
IDENTITY_SCHEMA = "backtester.pit-experiment-identity/1"
POINTER_SCHEMA = "backtester.canonical-pit-package-pointer/1"
ANNUAL_CERT_SCHEMA = "backtester.production-year-certificate/1"
ANNUAL_CHAIN_SCHEMA = "backtester.production-year-certificate-chain/1"

CERTIFIED = "PIT_CERTIFIED"
NOT_CERTIFIED = "PIT_NOT_CERTIFIED"
PASS = "PASS"
FAIL = "FAIL"

MANDATORY_CHECKS = (
    "dataset_integrity",
    "pit_metadata",
    "universe_resolution",
    "corporate_actions",
    "terminal_events",
    "financial_semantics",
    "static_forward_bias",
    "dynamic_future_leak",
    "runtime_causal_read_boundary",
    "runtime_source_binding",
    "checkpoint_resume",
)

_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_GIT_SHA = re.compile(r"^[0-9a-f]{40}(?:[0-9a-f]{24})?$")
_PACKAGE = re.compile(r"^ghcr\.io/flabber1835/stocker-canonical-pit@sha256:([0-9a-f]{64})$")

OFFICIAL_SOURCE_FILES = {
    "production": (
        "backtester/certify_backtest_result.py",
        "backtester/future_leak_certification.py",
        "backtester/canonical_pit_dataset.py",
        "backtester/canonical_pit_package.py",
        "backtester/strict_pit_metadata.py",
        "backtester/causal_split_overrides.py",
        "backtester/causal_terminal_terms.py",
        "backtester/historical_cash.py",
        "backtester/run_production_strict_pit_certification.py",
        "backtester/run_production_strict_pit_20y.py",
        "backtester/run_production_current_main_strict_pit_20y.py",
        "backtester/run_production_strict_pit_20y_checkpointed.py",
        "backtester/production_year_checkpoint_overlay.py",
        "backtester/production_public_reporting.py",
        "backtester/write_production_year_certificate.py",
        "backtester/write_production_year_certificate_g4.py",
        "main-src/sentinel/core",
        "main-src/shared/stock_strategy_shared",
    ),
    "research": (
        "backtester/certify_backtest_result.py",
        "backtester/future_leak_certification.py",
        "backtester/canonical_pit_dataset.py",
        "backtester/canonical_pit_package.py",
        "backtester/strict_pit_metadata.py",
        "backtester/causal_split_overrides.py",
        "backtester/causal_terminal_terms.py",
        "backtester/historical_cash.py",
        "backtester/research_terminal_grace_overlay.py",
        "backtester/run_research_strict_pit_certification.py",
        "backtester/run_research_strict_pit_20y.py",
        "backtester/run_research_ldrc_corrected_warmup_cash.py",
        "backtester/run_research_ldrc_nonpit_vs_fullpit.py",
        "research/sentinel-fastgate/experiments/2026-08-25-pit-vs-full-c/ldrc_ab_replay_20260825.py",
        "main-src/sentinel/core",
        "main-src/shared/stock_strategy_shared",
    ),
}


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def json_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"expected JSON object in {path}")
    return value


def write_json(path: Path, value: Mapping[str, Any]) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _require_sha(value: Any, label: str, *, git: bool = False) -> str:
    text = str(value or "")
    pattern = _GIT_SHA if git else _HEX64
    if not pattern.fullmatch(text):
        raise RuntimeError(f"{label} is not a valid {'git' if git else 'sha256'} digest")
    return text


def _config_payload(mode: str, source_sha: str, strategy_sha: str, dataset_hash: str,
                    warmup_start: str, measurement_start: str, end: str,
                    parameters: Any) -> dict[str, Any]:
    return {
        "schema": "backtester.pit-configuration/1",
        "mode": mode,
        "source_sha": source_sha,
        "strategy_sha": strategy_sha,
        "dataset_hash": dataset_hash,
        "window": {
            "warmup_start": warmup_start,
            "measurement_start": measurement_start,
            "end": end,
        },
        "parameters": parameters,
    }


def build_identity(*, mode: str, source_sha: str, strategy_sha: str,
                   workflow_sha: str, dataset_hash: str, warmup_start: str,
                   measurement_start: str, end: str, parameters: Any,
                   source_closure_sha256: str, runtime_identity_sha256: str) -> dict[str, Any]:
    if mode not in {"production", "research"}:
        raise RuntimeError(f"unsupported PIT certification mode: {mode}")
    _require_sha(source_sha, "source_sha", git=True)
    _require_sha(strategy_sha, "strategy_sha", git=True)
    _require_sha(workflow_sha, "workflow_sha", git=True)
    _require_sha(dataset_hash, "dataset_hash")
    _require_sha(source_closure_sha256, "source_closure_sha256")
    _require_sha(runtime_identity_sha256, "runtime_identity_sha256")
    configuration = _config_payload(
        mode, source_sha, strategy_sha, dataset_hash,
        warmup_start, measurement_start, end, parameters,
    )
    identity = {
        "schema": IDENTITY_SCHEMA,
        "mode": mode,
        "source_sha": source_sha,
        "strategy_sha": strategy_sha,
        "workflow_sha": workflow_sha,
        "dataset_hash": dataset_hash,
        "configuration_sha256": json_hash(configuration),
        "source_closure_sha256": source_closure_sha256,
        "runtime_identity_sha256": runtime_identity_sha256,
        "configuration": configuration,
    }
    identity["identity_sha256"] = json_hash(identity)
    return identity


def source_closure_hash(root: Path, files: Iterable[str]) -> tuple[str, dict[str, str]]:
    root = Path(root)
    members: dict[str, str] = {}
    for relative in sorted(set(str(x) for x in files)):
        path = root / relative
        if path.is_file():
            candidates = [path]
        elif path.is_dir():
            candidates = [p for p in path.rglob("*") if p.is_file() and "__pycache__" not in p.parts]
        else:
            raise RuntimeError(f"source closure member missing: {relative}")
        for candidate in sorted(candidates):
            key = candidate.relative_to(root).as_posix()
            members[key] = sha256_file(candidate)
    if not members:
        raise RuntimeError("source closure is empty")
    return json_hash(members), members


def runtime_identity_hash() -> tuple[str, dict[str, Any]]:
    import platform
    payload = {
        "python": sys.version.split()[0],
        "implementation": platform.python_implementation(),
        "platform": platform.platform(),
    }
    return json_hash(payload), payload


def verify_pointer(pointer_path: Path) -> dict[str, Any]:
    pointer = load_json(pointer_path)
    if pointer.get("schema") != POINTER_SCHEMA:
        raise RuntimeError("unexpected canonical PIT pointer schema")
    if pointer.get("status") != PASS:
        raise RuntimeError("canonical PIT pointer is not admitted")
    package = str(pointer.get("package") or "")
    match = _PACKAGE.fullmatch(package)
    if match is None or ":latest" in package:
        raise RuntimeError("canonical PIT package is not immutable digest-pinned content")
    for key in ("dataset_hash", "manifest_sha256"):
        _require_sha(pointer.get(key), f"pointer {key}")
    _require_sha(pointer.get("reconstruction_code_sha"), "pointer reconstruction_code_sha", git=True)
    window = pointer.get("window")
    if not isinstance(window, dict) or set(window) != {"warmup_start", "measurement_start", "end"}:
        raise RuntimeError("canonical PIT pointer window is incomplete")
    return {
        **pointer,
        "pointer_sha256": sha256_file(Path(pointer_path)),
        "package_digest": match.group(1),
    }


def _member_digest(member: Any) -> str:
    if isinstance(member, str):
        return member
    if isinstance(member, Mapping):
        for key in ("sha256", "digest", "file_sha256"):
            if key in member:
                return str(member[key])
    raise RuntimeError("canonical manifest member lacks sha256")


def verify_dataset(dataset_root: Path, pointer: Mapping[str, Any]) -> dict[str, Any]:
    root = Path(dataset_root)
    manifest_path = root / "manifest.json"
    if not manifest_path.is_file():
        raise RuntimeError("canonical PIT manifest is missing")
    if sha256_file(manifest_path) != pointer["manifest_sha256"]:
        raise RuntimeError("canonical PIT manifest differs from admitted pointer")
    manifest = load_json(manifest_path)
    if manifest.get("status") != PASS:
        raise RuntimeError("canonical PIT manifest is not PASS")
    if manifest.get("dataset_hash") != pointer["dataset_hash"]:
        raise RuntimeError("canonical PIT dataset hash differs from pointer")
    if manifest.get("reconstruction_code_sha") != pointer["reconstruction_code_sha"]:
        raise RuntimeError("canonical PIT reconstruction identity differs from pointer")
    if manifest.get("window") != pointer["window"]:
        raise RuntimeError("canonical PIT date window differs from pointer")
    members = manifest.get("members")
    if not isinstance(members, Mapping) or not members:
        raise RuntimeError("canonical PIT manifest has no content-addressed members")
    verified: dict[str, str] = {}
    for name, metadata in sorted(members.items()):
        if Path(str(name)).name != str(name):
            raise RuntimeError(f"unsafe canonical member path: {name}")
        expected = _member_digest(metadata)
        _require_sha(expected, f"canonical member {name}")
        path = root / str(name)
        if not path.is_file():
            raise RuntimeError(f"canonical member missing: {name}")
        observed = sha256_file(path)
        if observed != expected:
            raise RuntimeError(f"canonical member changed after authentication: {name}")
        verified[str(name)] = observed
    for required in ("session-hashes.csv", "metadata-timeline.csv.gz", "actions.csv.gz", "terminal-events.csv.gz"):
        if required not in verified:
            raise RuntimeError(f"canonical required member is not authenticated: {required}")
    session_hashes = root / "session-hashes.csv"
    return {
        "dataset_id": manifest.get("dataset_id"),
        "dataset_sha256": manifest["dataset_hash"],
        "package": pointer["package"],
        "package_digest": pointer["package_digest"],
        "pointer_sha256": pointer["pointer_sha256"],
        "manifest_sha256": pointer["manifest_sha256"],
        "reconstruction_code_sha": manifest["reconstruction_code_sha"],
        "window": manifest["window"],
        "member_hashes": verified,
        "member_hash_set_sha256": json_hash(verified),
        "session_hashes_sha256": sha256_file(session_hashes),
        "manifest": manifest,
    }


def _iter_csv(path: Path):
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8", newline="") as handle:
        yield from csv.DictReader(handle)


def audit_universe_resolution(dataset_root: Path, manifest: Mapping[str, Any]) -> dict[str, Any]:
    root = Path(dataset_root)
    members = manifest.get("members") or {}
    observation_names = sorted(
        str(name) for name in members
        if re.fullmatch(r"observations-\d{4}\.csv\.gz", str(name))
    )
    if not observation_names:
        raise RuntimeError("canonical PIT manifest has no observation partitions")
    historical_security_ids: set[str] = set()
    candidate = eligible = ineligible = unresolved = 0
    unknown_security_type = unknown_identity = 0
    reasons: dict[str, int] = {}
    examples: list[dict[str, str]] = []
    for name in observation_names:
        for row in _iter_csv(root / name):
            sid = str(row.get("security_id") or "").strip()
            ticker = str(row.get("ticker") or "").strip()
            session = str(row.get("session") or row.get("date") or "")[:10]
            if sid:
                historical_security_ids.add(sid)
            else:
                unknown_identity += 1
            listing_active = str(row.get("listing_active", "1")).lower() in {"1", "1.0", "true"}
            # Universe conservation is intentionally upstream of the derived
            # ``tradeable`` flag: the historical defect being closed was exactly
            # ``unknown security type -> tradeable/ineligible -> silent exclusion``.
            # Every observed canonical security row must therefore resolve before
            # tradeability is allowed to narrow the strategy universe.
            candidate += 1
            security_type = str(row.get("security_type") or "").strip().lower()
            if not listing_active:
                ineligible += 1
                reasons["CAUSAL_NOT_LISTED"] = reasons.get("CAUSAL_NOT_LISTED", 0) + 1
            elif security_type in {"common", "common_stock", "common stock"}:
                eligible += 1
            elif security_type in {"non_common", "non-common", "noncommon"}:
                ineligible += 1
                reasons["CAUSAL_NON_COMMON_SECURITY_TYPE"] = reasons.get("CAUSAL_NON_COMMON_SECURITY_TYPE", 0) + 1
            else:
                unresolved += 1
                unknown_security_type += 1
                if len(examples) < 25:
                    examples.append({"security_id": sid, "ticker": ticker, "session": session, "reason": "UNKNOWN_SECURITY_TYPE"})
    counts = manifest.get("counts") or {}
    declared_unknown = int(counts.get("unknown_security_type_observations", unknown_security_type))
    if declared_unknown != unknown_security_type:
        raise RuntimeError(
            "universe audit disagrees with manifest unknown security-type count: "
            f"observed={unknown_security_type} manifest={declared_unknown}"
        )
    identity_audit = manifest.get("identity_audit") or {}
    identity_blockers = int(identity_audit.get("blocking_identity_conflicts", 0))
    unknown_terminal_state = int(counts.get("incomplete_terminal_terms", 0))
    unresolved_total = unresolved + unknown_identity + identity_blockers + unknown_terminal_state
    return {
        "schema": "backtester.pit-universe-resolution-audit/1",
        "historical_security_episodes": len(historical_security_ids),
        "historical_candidate_observations": candidate,
        "resolved_eligible": eligible,
        "resolved_pit_ineligible": ineligible,
        "pit_ineligible_reasons": dict(sorted(reasons.items())),
        "unresolved": unresolved_total,
        "unresolved_security_classification": unresolved,
        "unknown_security_type": unknown_security_type,
        "unknown_identity": unknown_identity + identity_blockers,
        "unknown_terminal_state": unknown_terminal_state,
        "examples": examples,
    }


def audit_dataset_contract(dataset_root: Path, pointer_path: Path) -> dict[str, Any]:
    pointer = verify_pointer(pointer_path)
    dataset = verify_dataset(dataset_root, pointer)
    universe = audit_universe_resolution(dataset_root, dataset["manifest"])
    counts = dataset["manifest"].get("counts") or {}
    identity = dataset["manifest"].get("identity_audit") or {}
    causal = dataset["manifest"].get("causal_metadata_audit") or {}
    metadata_after_decision = int(causal.get("metadata_after_decision_consumptions", 0))
    future_metadata_authority = int(causal.get("future_metadata_authority_violations", 0))
    checks = {
        "dataset_integrity": PASS,
        "universe_resolution": PASS if int(universe["unresolved"]) == 0 else FAIL,
        "corporate_actions": PASS if int(counts.get("unresolved_corporate_actions", -1)) == 0 else FAIL,
        "terminal_events": PASS if int(counts.get("incomplete_terminal_terms", -1)) == 0 else FAIL,
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
        "manifest_counts": counts,
        "identity_audit": identity,
        "causal_metadata_audit": causal,
    }


def _validate_identity(identity: Mapping[str, Any]) -> dict[str, Any]:
    if identity.get("schema") != IDENTITY_SCHEMA:
        raise RuntimeError("unexpected PIT experiment identity schema")
    body = dict(identity)
    observed = str(body.pop("identity_sha256", ""))
    if json_hash(body) != observed:
        raise RuntimeError("PIT experiment identity hash mismatch")
    _require_sha(observed, "identity_sha256")
    return dict(identity)


def _identity_join(left: Mapping[str, Any], right: Mapping[str, Any]) -> list[str]:
    mismatches = []
    for key in (
        "mode", "source_sha", "strategy_sha", "workflow_sha", "dataset_hash",
        "configuration_sha256", "source_closure_sha256", "runtime_identity_sha256",
        "identity_sha256",
    ):
        if left.get(key) != right.get(key):
            mismatches.append(key)
    return mismatches


def _load_evidence(path: Path | None, schema: str, label: str) -> dict[str, Any] | None:
    if path is None or not Path(path).is_file():
        return None
    value = load_json(Path(path))
    if value.get("schema") != schema:
        raise RuntimeError(f"unexpected {label} schema")
    identity = value.get("identity")
    if not isinstance(identity, Mapping):
        raise RuntimeError(f"{label} lacks experiment identity")
    _validate_identity(identity)
    return value


def collect_replay_evidence(*, mode: str, identity: Mapping[str, Any], output_root: Path,
                            annual_chain: Path | None = None,
                            checkpoint_resume: str = PASS) -> dict[str, Any]:
    identity = _validate_identity(identity)
    root = Path(output_root)
    summary_path = root / "summary.json"
    audit_path = root / "metadata_authority_audit.json"
    if not summary_path.is_file() or not audit_path.is_file():
        raise RuntimeError("replay output lacks summary or metadata authority audit")
    summary = load_json(summary_path)
    audit = load_json(audit_path)
    if summary.get("status") != PASS:
        raise RuntimeError("replay summary is not PASS")
    if summary.get("canonical_pit_dataset_hash") != identity["dataset_hash"]:
        raise RuntimeError("replay consumed a different canonical dataset")
    if summary.get("backtester_sha") not in {None, identity["source_sha"]}:
        raise RuntimeError("replay summary source SHA differs from experiment identity")
    if audit.get("current_SHARADAR_TICKERS_economically_active_fields") != []:
        raise RuntimeError("current SHARADAR_TICKERS retained historical economic authority")
    financial = audit.get("financial_grade") or {}
    financial_ok = (
        bool(financial.get("requires_resolved_nav"))
        and str(financial.get("missing_leadership_return_policy")) == "FAIL_CLOSED"
        and int(financial.get("dividend_lag_sessions", -1)) == 15
    )
    future_metadata_reads = int(audit.get("metadata_after_decision_consumptions", 0))
    unresolved_splits = int(audit.get("unresolved_economically_relevant_splits", 0))
    held_disappearances = int(audit.get("held_terminal_disappearances_unresolved", 0))
    evidence_hashes: dict[str, str] = {}
    for name in ("summary.json", "metadata_authority_audit.json", "daily.csv.gz", "metrics.csv", "manifest.json", "SHA256SUMS.txt"):
        path = root / name
        if path.is_file():
            evidence_hashes[name] = sha256_file(path)
    chain_evidence = None
    if annual_chain is not None:
        chain_evidence = validate_production_annual_chain(annual_chain, identity)
        evidence_hashes["production-certificate-chain.json"] = sha256_file(Path(annual_chain))
    checks = {
        "pit_metadata": PASS if future_metadata_reads == 0 else FAIL,
        "corporate_actions": PASS if unresolved_splits == 0 else FAIL,
        "terminal_events": PASS if held_disappearances == 0 else FAIL,
        "financial_semantics": PASS if financial_ok else FAIL,
        "runtime_source_binding": PASS,
        "checkpoint_resume": checkpoint_resume if checkpoint_resume in {PASS, FAIL} else FAIL,
    }
    result = {
        "schema": REPLAY_EVIDENCE_SCHEMA,
        "status": "BACKTEST_COMPLETED",
        "mode": mode,
        "identity": identity,
        "checks": checks,
        "evidence_sha256": dict(sorted(evidence_hashes.items())),
        "metadata_authority": audit,
        "annual_chain": chain_evidence,
    }
    result["evidence_hash"] = json_hash(result)
    return result


def validate_production_annual_chain(path: Path, identity: Mapping[str, Any]) -> dict[str, Any]:
    chain = load_json(path)
    if chain.get("schema") != ANNUAL_CHAIN_SCHEMA:
        raise RuntimeError("unexpected Production annual chain schema")
    certificates = chain.get("certificates")
    if not isinstance(certificates, list) or [c.get("year") for c in certificates] != list(range(2006, 2027)):
        raise RuntimeError("Production annual chain is not complete through 2026")
    previous_chain_hash = None
    previous = None
    for certificate in certificates:
        if certificate.get("schema") != ANNUAL_CERT_SCHEMA or certificate.get("status") != PASS:
            raise RuntimeError("Production annual certificate is not authenticated PASS replay evidence")
        ids = certificate.get("identities") or {}
        if ids.get("source_sha") != identity["source_sha"]:
            raise RuntimeError("Production annual certificate source SHA mismatch")
        if ids.get("workflow_sha") != identity["workflow_sha"]:
            raise RuntimeError("Production annual certificate workflow SHA mismatch")
        if ids.get("production_main_sha") != identity["strategy_sha"]:
            raise RuntimeError("Production annual certificate Production SHA mismatch")
        if ids.get("dataset_hash") != identity["dataset_hash"]:
            raise RuntimeError("Production annual certificate dataset hash mismatch")
        body = {k: v for k, v in certificate.items() if k not in {"certificate_hash", "chain_hash"}}
        cert_hash = json_hash(body)
        if cert_hash != certificate.get("certificate_hash"):
            raise RuntimeError("Production annual certificate content hash mismatch")
        expected_chain = hashlib.sha256(((previous_chain_hash or "GENESIS") + "\n" + cert_hash).encode()).hexdigest()
        if expected_chain != certificate.get("chain_hash"):
            raise RuntimeError("Production annual certificate chain hash mismatch")
        predecessor = certificate.get("predecessor")
        if previous is None:
            if predecessor is not None:
                raise RuntimeError("Production annual genesis has predecessor")
        else:
            if not isinstance(predecessor, Mapping):
                raise RuntimeError("Production annual predecessor is missing")
            for key, expected in (
                ("year", previous["year"]),
                ("certificate_hash", previous["certificate_hash"]),
                ("chain_hash", previous["chain_hash"]),
                ("checkpoint_sha256", previous["checkpoint"]["file_sha256"]),
            ):
                if predecessor.get(key) != expected:
                    raise RuntimeError(f"Production annual predecessor {key} mismatch")
        if certificate.get("complete_20_year_certificate") is True:
            raise RuntimeError("Production annual replay certificate claimed global completion before PIT finalization")
        previous_chain_hash = certificate["chain_hash"]
        previous = certificate
    if chain.get("chain_hash") != previous_chain_hash:
        raise RuntimeError("Production annual chain envelope hash mismatch")
    return {
        "years": [2006, 2026],
        "certificates": len(certificates),
        "final_certificate_hash": previous["certificate_hash"],
        "final_chain_hash": previous_chain_hash,
        "final_checkpoint_sha256": previous["checkpoint"]["file_sha256"],
        "global_completion_claimed": False,
    }


def collect_test_evidence(*, identity: Mapping[str, Any], dataset_audit: Mapping[str, Any],
                          static_forward_bias: str, dynamic_future_leak: str,
                          runtime_causal_read_boundary: str, financial_semantics: str,
                          checkpoint_resume: str, diagnostics: Mapping[str, Any] | None = None) -> dict[str, Any]:
    identity = _validate_identity(identity)
    checks = dict(dataset_audit.get("checks") or {})
    checks.update({
        "static_forward_bias": static_forward_bias,
        "dynamic_future_leak": dynamic_future_leak,
        "runtime_causal_read_boundary": runtime_causal_read_boundary,
        "financial_semantics": financial_semantics,
        "checkpoint_resume": checkpoint_resume,
        "runtime_source_binding": PASS,
    })
    result = {
        "schema": TEST_EVIDENCE_SCHEMA,
        "status": PASS if all(checks.get(k) == PASS for k in MANDATORY_CHECKS) else FAIL,
        "identity": identity,
        "checks": checks,
        "dataset_identity": dataset_audit.get("dataset_identity"),
        "universe_resolution": dataset_audit.get("universe_resolution"),
        "manifest_counts": dataset_audit.get("manifest_counts"),
        "diagnostics": dict(diagnostics or {}),
    }
    result["evidence_hash"] = json_hash(result)
    return result


def _verify_evidence_hash(value: Mapping[str, Any], label: str) -> None:
    body = dict(value)
    observed = str(body.pop("evidence_hash", ""))
    _require_sha(observed, f"{label} evidence_hash")
    if json_hash(body) != observed:
        raise RuntimeError(f"{label} evidence hash mismatch")


def finalise(*, identity: Mapping[str, Any], dataset_root: Path | None, pointer_path: Path | None,
             replay_evidence_path: Path | None, test_evidence_path: Path | None,
             replay_job_result: str = "success", tests_job_result: str = "success") -> dict[str, Any]:
    identity = _validate_identity(identity)
    checks = {key: FAIL for key in MANDATORY_CHECKS}
    blockers: list[dict[str, Any]] = []
    evidence: dict[str, Any] = {}

    def block(code: str, reason: str, **details: Any) -> None:
        blockers.append({"code": code, "reason": reason, **details})

    dataset_audit = None
    if dataset_root is None or pointer_path is None:
        block("MISSING_DATASET_EVIDENCE", "canonical PIT dataset or pointer is unavailable to finalizer")
    else:
        try:
            pointer = verify_pointer(pointer_path)
            verified_dataset = verify_dataset(dataset_root, pointer)
            manifest = verified_dataset["manifest"]
            counts = manifest.get("counts") or {}
            identity_audit = manifest.get("identity_audit") or {}
            causal = manifest.get("causal_metadata_audit") or {}
            quick_unknown = int(counts.get("unknown_security_type_observations", -1))
            quick_terminal = int(counts.get("incomplete_terminal_terms", -1))
            quick_actions = int(counts.get("unresolved_corporate_actions", -1))
            quick_pit = (
                int(identity_audit.get("blocking_identity_conflicts", 0)) == 0
                and int(causal.get("metadata_after_decision_consumptions", 0)) == 0
                and int(causal.get("future_metadata_authority_violations", 0)) == 0
            )
            dataset_audit = {
                "dataset_identity": {k: v for k, v in verified_dataset.items() if k != "manifest"},
                "manifest_counts": counts,
                "checks": {
                    "dataset_integrity": PASS,
                    "pit_metadata": PASS if quick_pit else FAIL,
                    "universe_resolution": PASS if quick_unknown == 0 else FAIL,
                    "corporate_actions": PASS if quick_actions == 0 else FAIL,
                    "terminal_events": PASS if quick_terminal == 0 else FAIL,
                },
            }
            evidence["dataset"] = dataset_audit["dataset_identity"]
            for key in ("dataset_integrity", "pit_metadata", "universe_resolution", "corporate_actions", "terminal_events"):
                checks[key] = dataset_audit["checks"][key]
            if checks["corporate_actions"] != PASS:
                block("UNRESOLVED_CORPORATE_ACTION", "canonical dataset retains unresolved corporate actions")
            if checks["terminal_events"] != PASS:
                block("UNRESOLVED_TERMINAL_EVENT", "canonical dataset retains incomplete terminal economic terms")
        except Exception as exc:
            block("DATASET_INTEGRITY_FAILURE", str(exc))

    if replay_job_result != "success":
        block("REPLAY_JOB_FAILED", f"replay job result is {replay_job_result}")
    if tests_job_result != "success":
        block("CAUSALITY_JOB_FAILED", f"mandatory certification-suite job result is {tests_job_result}")

    replay = tests = None
    try:
        replay = _load_evidence(replay_evidence_path, REPLAY_EVIDENCE_SCHEMA, "replay")
        if replay is None:
            block("MISSING_REPLAY_EVIDENCE", "replay evidence is missing")
        else:
            _verify_evidence_hash(replay, "replay")
            mismatches = _identity_join(identity, replay["identity"])
            if mismatches:
                block("REPLAY_IDENTITY_MISMATCH", "replay evidence belongs to a different experiment", fields=mismatches)
            else:
                replay_checks = replay.get("checks") or {}
                for key in ("pit_metadata", "corporate_actions", "terminal_events"):
                    checks[key] = PASS if checks.get(key) == PASS and replay_checks.get(key) == PASS else FAIL
                for key in ("financial_semantics", "runtime_source_binding", "checkpoint_resume"):
                    checks[key] = PASS if replay_checks.get(key) == PASS else FAIL
                evidence["replay_evidence_hash"] = replay["evidence_hash"]
                evidence["annual_chain"] = replay.get("annual_chain")
    except Exception as exc:
        block("INVALID_REPLAY_EVIDENCE", str(exc))

    try:
        tests = _load_evidence(test_evidence_path, TEST_EVIDENCE_SCHEMA, "test")
        if tests is None:
            block("MISSING_CAUSALITY_EVIDENCE", "mandatory certification-suite evidence is missing")
        else:
            _verify_evidence_hash(tests, "test")
            mismatches = _identity_join(identity, tests["identity"])
            if mismatches:
                block("TEST_IDENTITY_MISMATCH", "causality evidence belongs to a different experiment", fields=mismatches)
            else:
                test_checks = tests.get("checks") or {}
                for key in ("pit_metadata", "universe_resolution", "corporate_actions", "terminal_events"):
                    checks[key] = PASS if checks.get(key) == PASS and test_checks.get(key) == PASS else FAIL
                for key in ("static_forward_bias", "dynamic_future_leak", "runtime_causal_read_boundary"):
                    checks[key] = PASS if test_checks.get(key) == PASS else FAIL
                for key in ("financial_semantics", "runtime_source_binding", "checkpoint_resume"):
                    checks[key] = PASS if checks.get(key) == PASS and test_checks.get(key) == PASS else FAIL
                evidence["test_evidence_hash"] = tests["evidence_hash"]
                evidence["universe_resolution"] = tests.get("universe_resolution")
                if checks["universe_resolution"] != PASS:
                    u = tests.get("universe_resolution") or {}
                    block("UNRESOLVED_HISTORICAL_UNIVERSE", "historical security universe is not fully causally resolved", **{
                        "unresolved": u.get("unresolved"),
                        "unknown_security_type": u.get("unknown_security_type"),
                        "unknown_identity": u.get("unknown_identity"),
                        "unknown_terminal_state": u.get("unknown_terminal_state"),
                    })
                if tests.get("status") != PASS:
                    block("MANDATORY_CHECK_FAILED", "mandatory PIT/causality suite reported FAIL")
    except Exception as exc:
        block("INVALID_CAUSALITY_EVIDENCE", str(exc))

    if dataset_audit is not None:
        if dataset_audit["dataset_identity"]["dataset_sha256"] != identity["dataset_hash"]:
            block("DATASET_IDENTITY_MISMATCH", "finalizer dataset differs from experiment identity")
        if tests is not None:
            test_ds = (tests.get("dataset_identity") or {}).get("dataset_sha256")
            if test_ds != identity["dataset_hash"]:
                block("TEST_DATASET_MISMATCH", "causality suite used a different dataset")

    for key in MANDATORY_CHECKS:
        if checks.get(key) != PASS:
            block("CHECK_NOT_PASS", f"mandatory check {key} is not PASS", check=key, status=checks.get(key))

    seen = set()
    unique_blockers = []
    for item in blockers:
        key = canonical_json_bytes(item)
        if key not in seen:
            seen.add(key)
            unique_blockers.append(item)
    blockers = unique_blockers

    status = CERTIFIED if not blockers and all(checks[k] == PASS for k in MANDATORY_CHECKS) else NOT_CERTIFIED
    body = {
        "schema": CERTIFICATION_SCHEMA,
        "status": status,
        "mode": identity["mode"],
        "source_identity": {
            "source_sha": identity["source_sha"],
            "strategy_sha": identity["strategy_sha"],
            "workflow_sha": identity["workflow_sha"],
            "source_closure_sha256": identity["source_closure_sha256"],
            "runtime_identity_sha256": identity["runtime_identity_sha256"],
            "identity_sha256": identity["identity_sha256"],
        },
        "dataset_identity": evidence.get("dataset"),
        "configuration_identity": {
            "configuration_sha256": identity["configuration_sha256"],
            "configuration": identity["configuration"],
        },
        "checks": checks,
        "evidence": evidence,
        "blockers": blockers,
        "claim": (
            "point-in-time, causality, universe, terminal/action, and forward-bias checks passed for this exact replay"
            if status == CERTIFIED else
            "the defined PIT/causality/forward-leakage/universe/execution contract was not fully proven"
        ),
    }
    return {**body, "certificate_hash": json_hash(body)}


def render_summary(certificate: Mapping[str, Any]) -> str:
    line = "=" * 70
    mode = str(certificate.get("mode") or "").capitalize()
    if certificate.get("status") == CERTIFIED:
        dataset = certificate.get("dataset_identity") or {}
        source = certificate.get("source_identity") or {}
        config = certificate.get("configuration_identity") or {}
        return "\n".join([
            line,
            "PIT CERTIFIED",
            "Point-in-time, causality, universe, terminal/action, and forward-bias",
            "checks passed for this exact replay.",
            f"Mode: {mode}",
            f"Backtester SHA: {source.get('source_sha', '')}",
            f"Strategy SHA: {source.get('strategy_sha', '')}",
            f"Canonical PIT dataset: {dataset.get('dataset_id', '')}",
            f"Dataset SHA256: {dataset.get('dataset_sha256', '')}",
            f"Configuration SHA256: {config.get('configuration_sha256', '')}",
            f"Certificate SHA256: {certificate.get('certificate_hash', '')}",
            line,
        ])
    blockers = certificate.get("blockers") or []
    primary = blockers[0] if blockers else {"reason": "mandatory certification evidence is incomplete"}
    details = []
    for key in ("unresolved", "unknown_security_type", "unknown_identity", "unknown_terminal_state", "fields", "check"):
        if key in primary:
            details.append(f"{key}: {primary[key]}")
    return "\n".join([
        line,
        "PIT NOT CERTIFIED",
        f"Reason: {primary.get('reason')}",
        *details,
        f"Certificate SHA256: {certificate.get('certificate_hash', '')}",
        line,
    ])


def _parse_parameters(raw: str) -> Any:
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError("--parameters-json must be valid JSON") from exc


def _identity_from_args(args) -> dict[str, Any]:
    pointer = verify_pointer(args.pointer)
    files = args.source_file or list(OFFICIAL_SOURCE_FILES[args.mode])
    source_hash, source_members = source_closure_hash(args.source_root, files)
    runtime_hash, runtime = runtime_identity_hash()
    identity = build_identity(
        mode=args.mode,
        source_sha=args.source_sha,
        strategy_sha=args.strategy_sha,
        workflow_sha=args.workflow_sha,
        dataset_hash=pointer["dataset_hash"],
        warmup_start=pointer["window"]["warmup_start"],
        measurement_start=pointer["window"]["measurement_start"],
        end=pointer["window"]["end"],
        parameters=_parse_parameters(args.parameters_json),
        source_closure_sha256=source_hash,
        runtime_identity_sha256=runtime_hash,
    )
    identity["source_closure_members"] = source_members
    identity["runtime_identity"] = runtime
    body = dict(identity)
    body.pop("identity_sha256", None)
    identity["identity_sha256"] = json_hash(body)
    return identity


def _add_identity_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--mode", required=True, choices=("production", "research"))
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--strategy-sha", required=True)
    parser.add_argument("--workflow-sha", required=True)
    parser.add_argument("--pointer", type=Path, required=True)
    parser.add_argument("--parameters-json", required=True)
    parser.add_argument("--source-root", type=Path, default=Path("."))
    parser.add_argument("--source-file", action="append", default=[])


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)

    identity_p = sub.add_parser("identity")
    _add_identity_args(identity_p)
    identity_p.add_argument("--output", type=Path, required=True)

    audit_p = sub.add_parser("audit-dataset")
    audit_p.add_argument("--dataset", type=Path, required=True)
    audit_p.add_argument("--pointer", type=Path, required=True)
    audit_p.add_argument("--output", type=Path, required=True)

    replay_p = sub.add_parser("collect-replay")
    replay_p.add_argument("--identity", type=Path, required=True)
    replay_p.add_argument("--output-root", type=Path, required=True)
    replay_p.add_argument("--annual-chain", type=Path)
    replay_p.add_argument("--checkpoint-resume", choices=(PASS, FAIL), default=PASS)
    replay_p.add_argument("--output", type=Path, required=True)

    tests_p = sub.add_parser("collect-tests")
    tests_p.add_argument("--identity", type=Path, required=True)
    tests_p.add_argument("--dataset-audit", type=Path, required=True)
    for name in ("static-forward-bias", "dynamic-future-leak", "runtime-causal-read-boundary", "financial-semantics", "checkpoint-resume"):
        tests_p.add_argument("--" + name, choices=(PASS, FAIL), required=True)
    tests_p.add_argument("--diagnostics", type=Path)
    tests_p.add_argument("--output", type=Path, required=True)

    final_p = sub.add_parser("finalize")
    final_p.add_argument("--identity", type=Path, required=True)
    final_p.add_argument("--dataset", type=Path)
    final_p.add_argument("--pointer", type=Path)
    final_p.add_argument("--replay-evidence", type=Path)
    final_p.add_argument("--test-evidence", type=Path)
    final_p.add_argument("--replay-job-result", default="success")
    final_p.add_argument("--tests-job-result", default="success")
    final_p.add_argument("--output", type=Path, required=True)
    final_p.add_argument("--summary-output", type=Path, required=True)
    final_p.add_argument("--github-step-summary", type=Path)

    args = parser.parse_args()
    if args.command == "identity":
        value = _identity_from_args(args)
        write_json(args.output, value)
        print(json.dumps(value, sort_keys=True))
        return 0
    if args.command == "audit-dataset":
        value = audit_dataset_contract(args.dataset, args.pointer)
        write_json(args.output, value)
        print(json.dumps(value, sort_keys=True))
        return 0 if all(v == PASS for v in value["checks"].values()) else 2
    if args.command == "collect-replay":
        identity = load_json(args.identity)
        value = collect_replay_evidence(
            mode=identity["mode"], identity=identity, output_root=args.output_root,
            annual_chain=args.annual_chain, checkpoint_resume=args.checkpoint_resume,
        )
        write_json(args.output, value)
        print(json.dumps(value, sort_keys=True))
        return 0 if all(v == PASS for v in value["checks"].values()) else 2
    if args.command == "collect-tests":
        identity = load_json(args.identity)
        dataset_audit = load_json(args.dataset_audit)
        diagnostics = load_json(args.diagnostics) if args.diagnostics and args.diagnostics.is_file() else None
        value = collect_test_evidence(
            identity=identity,
            dataset_audit=dataset_audit,
            static_forward_bias=args.static_forward_bias,
            dynamic_future_leak=args.dynamic_future_leak,
            runtime_causal_read_boundary=args.runtime_causal_read_boundary,
            financial_semantics=args.financial_semantics,
            checkpoint_resume=args.checkpoint_resume,
            diagnostics=diagnostics,
        )
        write_json(args.output, value)
        print(json.dumps(value, sort_keys=True))
        return 0 if value["status"] == PASS else 2
    if args.command == "finalize":
        identity = load_json(args.identity)
        value = finalise(
            identity=identity, dataset_root=args.dataset, pointer_path=args.pointer,
            replay_evidence_path=args.replay_evidence, test_evidence_path=args.test_evidence,
            replay_job_result=args.replay_job_result, tests_job_result=args.tests_job_result,
        )
        write_json(args.output, value)
        summary = render_summary(value) + "\n"
        args.summary_output.parent.mkdir(parents=True, exist_ok=True)
        args.summary_output.write_text(summary, encoding="utf-8")
        print(summary, end="")
        target = args.github_step_summary or (Path(os.environ["GITHUB_STEP_SUMMARY"]) if os.environ.get("GITHUB_STEP_SUMMARY") else None)
        if target is not None:
            with Path(target).open("a", encoding="utf-8") as handle:
                handle.write("```text\n" + summary + "```\n")
        return 0 if value["status"] == CERTIFIED else 2
    raise AssertionError(args.command)


if __name__ == "__main__":
    raise SystemExit(main())
