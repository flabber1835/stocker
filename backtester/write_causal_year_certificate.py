#!/usr/bin/env python3
"""Issue one content-addressed annual link in the 20-year causal certificate chain."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path

import pandas as pd

SCHEMA = "backtester.causal-year-certificate/3"
CHAIN_GENERATION = 3
CHECKPOINT_SCHEMA = "backtester.production-year-checkpoint/2"
CHECKPOINT_GENERATION = 2
FINAL_END = "2026-07-31"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _verify_sha256sums(bundle_root: Path) -> None:
    """Authenticate the finalized child bundle using its declared checksum file."""
    sums_path = bundle_root / "SHA256SUMS.txt"
    if not sums_path.is_file():
        raise RuntimeError(f"bundle checksum file missing: {sums_path}")
    seen: set[str] = set()
    for line_number, raw in enumerate(
        sums_path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        line = raw.strip()
        if not line:
            continue
        parts = line.split(None, 1)
        if len(parts) != 2:
            raise RuntimeError(
                f"malformed checksum line {line_number} in {sums_path}"
            )
        expected, name = parts
        name = name.strip().lstrip("*")
        if (
            len(expected) != 64
            or any(ch not in "0123456789abcdef" for ch in expected.lower())
            or not name
            or "/" in name
            or "\\" in name
            or name in {".", ".."}
            or name in seen
        ):
            raise RuntimeError(
                f"invalid checksum entry on line {line_number} in {sums_path}"
            )
        path = bundle_root / name
        if not path.is_file():
            raise RuntimeError(f"checksummed bundle member missing: {path}")
        observed = _sha256(path)
        if observed != expected.lower():
            raise RuntimeError(
                f"bundle checksum mismatch for {path}: {observed} != {expected.lower()}"
            )
        seen.add(name)
    if not seen:
        raise RuntimeError(f"bundle checksum file is empty: {sums_path}")


def _json_hash(value: object) -> str:
    blob = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode()
    return hashlib.sha256(blob).hexdigest()


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--year", type=int, required=True)
    parser.add_argument("--segment-end", required=True)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--dataset-hash", required=True)
    parser.add_argument("--previous-certificate", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    root = args.output_root.resolve()
    checkpoint_path = args.checkpoint.resolve()
    checkpoint_sidecar = Path(str(checkpoint_path) + ".sha256")
    if not checkpoint_path.is_file():
        raise RuntimeError(f"production checkpoint missing: {checkpoint_path}")
    if not checkpoint_sidecar.is_file():
        raise RuntimeError(f"production checkpoint sidecar missing: {checkpoint_sidecar}")
    checkpoint_digest = _sha256(checkpoint_path)
    sidecar_parts = checkpoint_sidecar.read_text(encoding="utf-8").strip().split()
    if not sidecar_parts or sidecar_parts[0] != checkpoint_digest:
        raise RuntimeError("production checkpoint sidecar does not authenticate checkpoint")

    checkpoint = _load(checkpoint_path)
    consumption = _load(root / "canonical_input_consumption_audit.json")
    progress = _load(root / "certification_progress_audit.json")
    strong = _load(root / "strong_equivalence_audit.json")
    production_summary = _load(root / "production" / "summary.json")
    research_summary = _load(root / "research" / "summary.json")
    production_authority = _load(root / "production" / "metadata_authority_audit.json")
    research_authority = _load(root / "research" / "metadata_authority_audit.json")

    if checkpoint.get("schema") != CHECKPOINT_SCHEMA:
        raise RuntimeError("unexpected production checkpoint schema")
    if int(checkpoint.get("generation", -1)) != CHECKPOINT_GENERATION:
        raise RuntimeError("production checkpoint format generation mismatch")
    if checkpoint.get("backtester_sha") != args.source_sha:
        raise RuntimeError("checkpoint source SHA mismatch")
    if checkpoint.get("dataset_hash") != args.dataset_hash:
        raise RuntimeError("checkpoint dataset hash mismatch")
    if checkpoint.get("end_session") != args.segment_end:
        raise RuntimeError("checkpoint segment-end mismatch")
    module_state = checkpoint.get("module_state") or {}
    fullstack = module_state.get("fullstack")
    strict_state = module_state.get("strict")
    if not isinstance(fullstack, dict):
        raise RuntimeError("checkpoint lacks full-stack PIT continuation state")
    if not isinstance(fullstack.get("pit_core_by_session"), dict):
        raise RuntimeError("checkpoint lacks cumulative PIT Wealth Core history")
    if args.segment_end not in fullstack["pit_core_by_session"]:
        raise RuntimeError("checkpoint PIT Wealth Core history lacks annual boundary")
    if not isinstance(strict_state, dict):
        raise RuntimeError("checkpoint lacks cumulative strict-authority state")

    if consumption.get("schema") != "backtester.canonical-input-consumption/3":
        raise RuntimeError("unexpected canonical prefix-consumption audit schema")
    if consumption.get("dataset_hash") != args.dataset_hash:
        raise RuntimeError("canonical input audit dataset hash mismatch")
    if consumption.get("prefix_end") != args.segment_end:
        raise RuntimeError("canonical input audit annual boundary mismatch")
    if not consumption.get("child_bundles_preserved"):
        raise RuntimeError("child result bundles were modified after finalization")
    if not consumption.get("per_session_hashes_identical"):
        raise RuntimeError("research and production canonical session hashes differ")
    if not consumption.get("package_prefix_authenticated"):
        raise RuntimeError("canonical annual prefix was not authenticated")
    prefix_hashes = consumption.get("prefix_evidence_sha256") or {}
    for role in ("production", "research"):
        prefix_path = root / role / "canonical_input_session_hashes_prefix.csv"
        if not prefix_path.is_file():
            raise RuntimeError(f"{role} canonical prefix evidence is missing")
        if prefix_hashes.get(role) != _sha256(prefix_path):
            raise RuntimeError(f"{role} canonical prefix evidence hash mismatch")

    if progress.get("first_divergence") is not None:
        raise RuntimeError("NAV divergence remains in annual causal segment")
    if strong.get("first_divergence") is not None:
        raise RuntimeError("internal strategy-state divergence remains in annual causal segment")
    if production_summary.get("canonical_pit_dataset_hash") != args.dataset_hash:
        raise RuntimeError("production summary dataset hash mismatch")
    if research_summary.get("canonical_pit_dataset_hash") != args.dataset_hash:
        raise RuntimeError("research summary dataset hash mismatch")
    for role, authority in (
        ("production", production_authority),
        ("research", research_authority),
    ):
        if authority.get("role") != role:
            raise RuntimeError(f"{role} metadata authority role mismatch")
        if authority.get("current_SHARADAR_TICKERS_economically_active_fields") != []:
            raise RuntimeError(f"{role} retained current TICKERS economic authority")
        if authority.get("fallbacks", {}).get("security_type_unknown") != "ineligible":
            raise RuntimeError(f"{role} security-type fallback is not fail-closed")

    # Production has both a manifest and SHA256SUMS contract. Retained research
    # intentionally has SHA256SUMS only. Validate each child's actual finalized
    # checksum contract instead of requiring a nonexistent research manifest.
    _verify_sha256sums(root / "production")
    _verify_sha256sums(root / "research")

    production_daily = pd.read_csv(
        root / "production" / "daily.csv.gz", compression="gzip", low_memory=False
    )
    research_daily = pd.read_csv(
        root / "research" / "daily.csv.gz", compression="gzip", low_memory=False
    )
    if production_daily.empty or research_daily.empty:
        raise RuntimeError("annual causal daily evidence is empty")
    if str(production_daily.iloc[-1]["date"])[:10] != args.segment_end:
        raise RuntimeError("production daily evidence ends at wrong session")
    if str(research_daily.iloc[-1]["date"])[:10] != args.segment_end:
        raise RuntimeError("research daily evidence ends at wrong session")
    if int(strong.get("sessions_compared", -1)) != len(production_daily):
        raise RuntimeError("strong-equivalence session count disagrees with production evidence")
    if len(production_daily) != len(research_daily):
        raise RuntimeError("research and production daily evidence lengths differ")

    previous = None
    previous_chain_hash = None
    if args.previous_certificate is not None:
        previous = _load(args.previous_certificate.resolve())
        if previous.get("schema") != SCHEMA:
            raise RuntimeError("previous annual certificate schema mismatch")
        if int(previous.get("generation", -1)) != CHAIN_GENERATION:
            raise RuntimeError("previous annual certificate chain generation mismatch")
        if int(previous.get("year", -1)) != args.year - 1:
            raise RuntimeError("previous annual certificate year is not contiguous")
        if previous.get("source_sha") != args.source_sha:
            raise RuntimeError("previous annual certificate source SHA mismatch")
        if previous.get("dataset_hash") != args.dataset_hash:
            raise RuntimeError("previous annual certificate dataset hash mismatch")
        if checkpoint.get("previous_checkpoint_sha256") != previous.get(
            "production_checkpoint_sha256"
        ):
            raise RuntimeError("production checkpoint does not link to prior certified checkpoint")
        previous_chain_hash = str(previous.get("chain_hash") or "")
        if len(previous_chain_hash) != 64:
            raise RuntimeError("previous annual certificate lacks a valid chain hash")
    elif checkpoint.get("previous_checkpoint_sha256") is not None:
        raise RuntimeError("genesis checkpoint unexpectedly references a predecessor")

    evidence_hashes = {
        "checkpoint": checkpoint_digest,
        "checkpoint_sha256_sidecar": _sha256(checkpoint_sidecar),
        "canonical_input_consumption_audit": _sha256(
            root / "canonical_input_consumption_audit.json"
        ),
        "production_input_prefix": _sha256(
            root / "production" / "canonical_input_session_hashes_prefix.csv"
        ),
        "research_input_prefix": _sha256(
            root / "research" / "canonical_input_session_hashes_prefix.csv"
        ),
        "certification_progress_audit": _sha256(
            root / "certification_progress_audit.json"
        ),
        "strong_equivalence_audit": _sha256(root / "strong_equivalence_audit.json"),
        "production_daily": _sha256(root / "production" / "daily.csv.gz"),
        "research_daily": _sha256(root / "research" / "daily.csv.gz"),
        "production_manifest": _sha256(root / "production" / "manifest.json"),
        "production_sha256sums": _sha256(root / "production" / "SHA256SUMS.txt"),
        "research_sha256sums": _sha256(root / "research" / "SHA256SUMS.txt"),
        "production_summary": _sha256(root / "production" / "summary.json"),
        "research_summary": _sha256(root / "research" / "summary.json"),
    }

    body = {
        "schema": SCHEMA,
        "generation": CHAIN_GENERATION,
        "checkpoint_format_generation": CHECKPOINT_GENERATION,
        "status": "PASS",
        "year": args.year,
        "segment_end": args.segment_end,
        "source_sha": args.source_sha,
        "production_main_sha": checkpoint.get("main_sha"),
        "dataset_hash": args.dataset_hash,
        "github_run_id": os.environ.get("GITHUB_RUN_ID"),
        "production_checkpoint_sha256": checkpoint_digest,
        "previous_certificate_hash": (
            None if previous is None else previous.get("certificate_hash")
        ),
        "previous_chain_hash": previous_chain_hash,
        "sessions_compared": int(strong.get("sessions_compared", 0)),
        "production_rows": int(len(production_daily)),
        "research_rows": int(len(research_daily)),
        "last_session_hash": checkpoint.get("session_hash"),
        "canonical_sessions_identical": True,
        "canonical_prefix_authenticated": True,
        "child_bundles_preserved": True,
        "nav_equivalent": True,
        "internal_state_equivalent": True,
        "causal_metadata_fail_closed": True,
        "restart_state_complete": True,
        "evidence_sha256": evidence_hashes,
        "complete_20_year_certificate": (
            args.year == 2026 and args.segment_end == FINAL_END
        ),
    }
    certificate_hash = _json_hash(body)
    chain_material = (previous_chain_hash or "GENESIS") + "\n" + certificate_hash
    chain_hash = hashlib.sha256(chain_material.encode()).hexdigest()
    certificate = {
        **body,
        "certificate_hash": certificate_hash,
        "chain_hash": chain_hash,
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(certificate, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(certificate, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())