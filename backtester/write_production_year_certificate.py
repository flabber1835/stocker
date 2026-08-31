#!/usr/bin/env python3
"""Issue and verify production-only annual replay certificates.

The certificate is intentionally separate from the restart image.  The restart
image contains every internal state owner required by the frozen runner, while
this file exposes only the strict-PIT Production result and its SPY benchmark.
"""
from __future__ import annotations

import argparse
import copy
import csv
from datetime import date
import gzip
import hashlib
import json
import math
import os
from pathlib import Path
from statistics import fmean, stdev
from typing import Mapping, Sequence

from backtester.production_year_checkpoint_overlay import (
    FORMAT_GENERATION as CHECKPOINT_FORMAT_GENERATION,
    SCHEMA as CHECKPOINT_SCHEMA,
    hash_value,
    load_checkpoint,
    sha256_file,
)


SCHEMA = "backtester.production-year-certificate/1"
CHAIN_SCHEMA = "backtester.production-year-certificate-chain/1"
EQUIVALENCE_SCHEMA = "backtester.production-resume-equivalence/1"
CHAIN_GENERATION = 1
FIRST_YEAR = 2006
FINAL_YEAR = 2026
MEASUREMENT_START = "2006-07-31"
FINAL_END = "2026-07-31"

_HEX64 = set("0123456789abcdef")
_CERTIFICATE_FIELDS = {
    "schema",
    "chain_generation",
    "status",
    "year",
    "segment_end",
    "identities",
    "current_run",
    "predecessor",
    "checkpoint",
    "metrics",
    "evidence_sha256",
    "complete_20_year_certificate",
    "certificate_hash",
    "chain_hash",
}
_IDENTITY_FIELDS = {
    "source_sha",
    "workflow_sha",
    "chain_ref",
    "production_main_sha",
    "production_overlay_sha256",
    "dataset_hash",
    "checkpoint_schema",
    "checkpoint_format_generation",
}
_RUN_FIELDS = {"id", "attempt", "artifact_name"}
_PREDECESSOR_FIELDS = {
    "year",
    "run_id",
    "run_attempt",
    "artifact_name",
    "certificate_hash",
    "chain_hash",
    "checkpoint_sha256",
}
_CHECKPOINT_FIELDS = {
    "file_sha256",
    "payload_sha256",
    "session_hash",
    "canonical_prefix_sha256",
    "daily_prefix_sha256",
    "expected_pointer",
    "production_state_hash",
    "next_session",
    "next_session_hash",
}
_METRICS_FIELDS = {"measurement_start", "end", "Production", "SPY"}
_METRIC_BLOCK_FIELDS = {
    "start",
    "end",
    "sessions",
    "elapsed_years",
    "cagr",
    "sharpe",
    "max_drawdown",
    "ending_multiple",
}


def _require_exact_fields(value: Mapping, expected: set[str], label: str) -> None:
    if not isinstance(value, Mapping) or set(value) != expected:
        observed = set(value) if isinstance(value, Mapping) else set()
        raise RuntimeError(
            f"{label} fields differ: {sorted(observed ^ expected)}"
        )


def _is_sha256(value: object) -> bool:
    text = str(value or "")
    return len(text) == 64 and all(ch in _HEX64 for ch in text)


def _require_hex(value: object, label: str, length: int) -> str:
    text = str(value or "")
    if len(text) != length or any(ch not in _HEX64 for ch in text):
        raise RuntimeError(f"{label} is not a lowercase {length}-hex digest")
    return text


def _require_sha256(value: object, label: str) -> str:
    return _require_hex(value, label, 64)


def _json_hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def _load_json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"expected JSON object in {path}")
    return value


def _read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        columns = list(reader.fieldnames or [])
        return columns, [dict(row) for row in reader]


def _finite_float(value: object, label: str, *, positive: bool = False) -> float:
    if isinstance(value, bool):
        raise RuntimeError(f"{label} is boolean, not numeric")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f"{label} is not numeric") from exc
    if not math.isfinite(number) or (positive and number <= 0):
        raise RuntimeError(f"{label} is not a valid finite value")
    return number


def metric_block(
    rows: Sequence[Mapping[str, object]],
    value_key: str,
    *,
    start: str = MEASUREMENT_START,
    end: str,
) -> dict:
    """Return cumulative metrics rebased to the declared measurement anchor."""
    selected = [
        row for row in rows
        if start <= str(row.get("date") or "") <= end
    ]
    if len(selected) < 2:
        raise RuntimeError(f"{value_key} has fewer than two measurement rows")
    observed_start = str(selected[0].get("date") or "")
    observed_end = str(selected[-1].get("date") or "")
    if observed_start != start or observed_end != end:
        raise RuntimeError(
            f"{value_key} measurement axis is {observed_start}..{observed_end}, "
            f"expected {start}..{end}"
        )
    values = [
        _finite_float(row.get(value_key), f"{value_key} on {row.get('date')}", positive=True)
        for row in selected
    ]
    normalized = [value / values[0] for value in values]
    returns = [
        normalized[index] / normalized[index - 1] - 1.0
        for index in range(1, len(normalized))
    ]
    elapsed_years = (
        date.fromisoformat(observed_end) - date.fromisoformat(observed_start)
    ).days / 365.2425
    if elapsed_years <= 0:
        raise RuntimeError("measurement elapsed years is non-positive")
    volatility = stdev(returns) if len(returns) > 1 else 0.0
    sharpe = (
        fmean(returns) / volatility * math.sqrt(252.0)
        if volatility > 0 else 0.0
    )
    peak = normalized[0]
    max_drawdown = 0.0
    for value in normalized:
        peak = max(peak, value)
        max_drawdown = min(max_drawdown, value / peak - 1.0)
    block = {
        "start": observed_start,
        "end": observed_end,
        "sessions": len(selected),
        "elapsed_years": elapsed_years,
        "cagr": normalized[-1] ** (1.0 / elapsed_years) - 1.0,
        "sharpe": sharpe,
        "max_drawdown": max_drawdown,
        "ending_multiple": normalized[-1],
    }
    for key, value in block.items():
        if key not in {"start", "end", "sessions"}:
            _finite_float(value, f"metric {key}")
    return block


def _assert_metric_close(observed: Mapping, expected: Mapping, label: str) -> None:
    _require_exact_fields(observed, _METRIC_BLOCK_FIELDS, label)
    for key in ("start", "end", "sessions"):
        if observed.get(key) != expected.get(key):
            raise RuntimeError(f"{label} {key} mismatch")
    for key in _METRIC_BLOCK_FIELDS - {"start", "end", "sessions"}:
        left = _finite_float(observed.get(key), f"{label} {key}")
        right = _finite_float(expected.get(key), f"expected {label} {key}")
        if not math.isclose(left, right, rel_tol=1e-10, abs_tol=1e-12):
            raise RuntimeError(f"{label} {key} mismatch: {left} != {right}")


def _validate_public_result(
    root: Path,
    checkpoint_payload: Mapping,
    *,
    segment_end: str,
    source_sha: str,
    dataset_hash: str,
) -> tuple[dict, dict[str, str], int]:
    required = {
        "daily.csv.gz",
        "metrics.csv",
        "summary.json",
        "manifest.json",
        "SHA256SUMS.txt",
        "metadata_authority_audit.json",
    }
    for name in required:
        if not (root / name).is_file():
            raise RuntimeError(f"finalized Production evidence is missing {name}")

    columns, rows = _read_csv(root / "daily.csv.gz")
    if not rows:
        raise RuntimeError("finalized Production daily evidence is empty")
    forbidden = {
        column for column in columns
        if column.startswith(("A_", "B_", "D_"))
    }
    if forbidden:
        raise RuntimeError(
            f"finalized Production daily evidence exposes legacy labels: {sorted(forbidden)}"
        )
    needed = {"date", "Production_nav", "SPY_level"}
    if not needed.issubset(columns):
        raise RuntimeError(
            f"finalized Production daily evidence lacks {sorted(needed - set(columns))}"
        )
    if str(rows[-1]["date"]) != segment_end:
        raise RuntimeError("finalized Production daily evidence ends at wrong session")

    checkpoint_daily = checkpoint_payload["daily"]
    raw_columns = list(checkpoint_daily["columns"])
    raw_rows = list(checkpoint_daily["rows"])
    date_index = raw_columns.index("date")
    production_index = raw_columns.index("B_nav")
    spy_index = raw_columns.index("SPY_level")
    if len(rows) != len(raw_rows):
        raise RuntimeError("public and authenticated daily row counts differ")
    for index, (public, raw) in enumerate(zip(rows, raw_rows)):
        if str(public["date"]) != str(raw[date_index]):
            raise RuntimeError(f"public daily date differs at row {index}")
        for public_key, raw_index in (
            ("Production_nav", production_index),
            ("SPY_level", spy_index),
        ):
            observed = _finite_float(public[public_key], f"public {public_key}", positive=True)
            expected = _finite_float(raw[raw_index], f"authenticated {public_key}", positive=True)
            if not math.isclose(observed, expected, rel_tol=1e-13, abs_tol=1e-14):
                raise RuntimeError(
                    f"public {public_key} differs from authenticated replay at row {index}"
                )

    metrics = {
        "measurement_start": MEASUREMENT_START,
        "end": segment_end,
        "Production": metric_block(rows, "Production_nav", end=segment_end),
        "SPY": metric_block(rows, "SPY_level", end=segment_end),
    }

    metric_columns, metric_rows = _read_csv(root / "metrics.csv")
    if "variant" not in metric_columns:
        raise RuntimeError("finalized metrics lack variant column")
    variants = {str(row.get("variant") or "") for row in metric_rows}
    if variants != {"Production", "SPY"}:
        raise RuntimeError(f"finalized metrics variants are not Production/SPY: {sorted(variants)}")
    max_rows = {
        str(row["variant"]): row
        for row in metric_rows
        if str(row.get("window_years") or "") == "max"
    }
    if set(max_rows) != {"Production", "SPY"}:
        raise RuntimeError("finalized metrics lack Production/SPY maximum-history rows")
    for role in ("Production", "SPY"):
        observed = {
            "start": str(max_rows[role]["start"]),
            "end": str(max_rows[role]["end"]),
            "sessions": int(max_rows[role]["sessions"]),
            "cagr": float(max_rows[role]["cagr"]),
            "sharpe": float(max_rows[role]["sharpe"]),
            "max_drawdown": float(max_rows[role]["max_drawdown"]),
            "ending_multiple": float(max_rows[role]["ending_multiple"]),
        }
        for key in ("start", "end", "sessions"):
            if observed[key] != metrics[role][key]:
                raise RuntimeError(f"metrics.csv {role} {key} mismatch")
        for key in ("cagr", "sharpe", "max_drawdown", "ending_multiple"):
            if not math.isclose(
                observed[key], metrics[role][key], rel_tol=1e-10, abs_tol=1e-12
            ):
                raise RuntimeError(f"metrics.csv {role} {key} mismatch")

    summary = _load_json(root / "summary.json")
    if summary.get("status") != "PASS":
        raise RuntimeError("finalized Production summary is not PASS")
    if summary.get("canonical_pit_dataset_hash") != dataset_hash:
        raise RuntimeError("finalized Production summary dataset hash mismatch")
    if summary.get("backtester_sha") != source_sha:
        raise RuntimeError("finalized Production summary source SHA mismatch")
    summary_metrics = summary.get("metrics") or {}
    for window, blocks in summary_metrics.items():
        if not isinstance(blocks, Mapping) or set(blocks) != {"Production", "SPY"}:
            raise RuntimeError(
                f"summary metric window {window} is not Production/SPY-only"
            )
    if "max" not in summary_metrics:
        raise RuntimeError("finalized Production summary lacks maximum-history metrics")
    for role in ("Production", "SPY"):
        _assert_metric_close(
            summary_metrics["max"][role], metrics[role], f"summary {role}"
        )

    authority = _load_json(root / "metadata_authority_audit.json")
    if authority.get("role") != "Production":
        raise RuntimeError("metadata authority role mismatch")
    if authority.get("current_SHARADAR_TICKERS_economically_active_fields") != []:
        raise RuntimeError("current TICKERS retained economic authority")
    if authority.get("fallbacks", {}).get("security_type_unknown") != "ineligible":
        raise RuntimeError("security-type unknown fallback is not fail-closed")

    sums: dict[str, str] = {}
    for line in (root / "SHA256SUMS.txt").read_text(encoding="utf-8").splitlines():
        parts = line.split()
        if len(parts) != 2:
            raise RuntimeError("malformed finalized SHA256SUMS row")
        digest, name = parts[0], parts[1].lstrip("*")
        if Path(name).name != name or not (root / name).is_file():
            raise RuntimeError(f"unsafe or missing finalized SHA256SUMS target {name!r}")
        _require_sha256(digest, f"SHA256SUMS digest for {name}")
        if sha256_file(root / name) != digest:
            raise RuntimeError(f"finalized SHA256SUMS mismatch for {name}")
        sums[f"production_output/{name}"] = digest
    for name in required:
        sums.setdefault(f"production_output/{name}", sha256_file(root / name))
    return metrics, dict(sorted(sums.items())), len(rows)


def _validate_metric_block(block: Mapping, label: str) -> None:
    _require_exact_fields(block, _METRIC_BLOCK_FIELDS, label)
    if not isinstance(block["start"], str) or not isinstance(block["end"], str):
        raise RuntimeError(f"{label} dates must be strings")
    if isinstance(block["sessions"], bool) or not isinstance(block["sessions"], int):
        raise RuntimeError(f"{label} sessions must be an integer")
    if block["sessions"] < 2:
        raise RuntimeError(f"{label} sessions must be at least two")
    for key in _METRIC_BLOCK_FIELDS - {"start", "end", "sessions"}:
        _finite_float(block[key], f"{label} {key}")


def validate_certificate(certificate: Mapping) -> None:
    """Strictly validate a certificate and recompute both content hashes."""
    _require_exact_fields(certificate, _CERTIFICATE_FIELDS, "certificate")
    if certificate["schema"] != SCHEMA:
        raise RuntimeError("unexpected annual certificate schema")
    if certificate["chain_generation"] != CHAIN_GENERATION:
        raise RuntimeError("annual certificate generation mismatch")
    if certificate["status"] != "PASS":
        raise RuntimeError("annual certificate is not PASS")
    year = certificate["year"]
    if isinstance(year, bool) or not isinstance(year, int) or not FIRST_YEAR <= year <= FINAL_YEAR:
        raise RuntimeError("annual certificate year is invalid")
    if not isinstance(certificate["segment_end"], str):
        raise RuntimeError("annual certificate segment end is invalid")

    identities = certificate["identities"]
    _require_exact_fields(identities, _IDENTITY_FIELDS, "certificate identities")
    for key in ("source_sha", "workflow_sha", "production_main_sha"):
        _require_hex(identities[key], f"certificate identity {key}", 40)
    for key in ("production_overlay_sha256", "dataset_hash"):
        _require_sha256(identities[key], f"certificate identity {key}")
    if identities["source_sha"] != identities["workflow_sha"]:
        raise RuntimeError("workflow and source SHA are not frozen together")
    if identities["checkpoint_schema"] != CHECKPOINT_SCHEMA:
        raise RuntimeError("certificate checkpoint schema mismatch")
    if identities["checkpoint_format_generation"] != CHECKPOINT_FORMAT_GENERATION:
        raise RuntimeError("certificate checkpoint format generation mismatch")
    if not isinstance(identities["chain_ref"], str) or not identities["chain_ref"]:
        raise RuntimeError("certificate chain ref is empty")

    current_run = certificate["current_run"]
    _require_exact_fields(current_run, _RUN_FIELDS, "certificate current run")
    if not str(current_run["id"]).isdigit():
        raise RuntimeError("certificate run ID is invalid")
    if isinstance(current_run["attempt"], bool) or not isinstance(current_run["attempt"], int):
        raise RuntimeError("certificate run attempt is invalid")
    if current_run["attempt"] < 1 or not isinstance(current_run["artifact_name"], str):
        raise RuntimeError("certificate current-run identity is invalid")

    predecessor = certificate["predecessor"]
    if year == FIRST_YEAR:
        if predecessor is not None:
            raise RuntimeError("genesis annual certificate has a predecessor")
    else:
        _require_exact_fields(predecessor, _PREDECESSOR_FIELDS, "certificate predecessor")
        if predecessor["year"] != year - 1:
            raise RuntimeError("certificate predecessor year is not contiguous")
        if not str(predecessor["run_id"]).isdigit():
            raise RuntimeError("certificate predecessor run ID is invalid")
        if isinstance(predecessor["run_attempt"], bool) or not isinstance(
            predecessor["run_attempt"], int
        ) or predecessor["run_attempt"] < 1:
            raise RuntimeError("certificate predecessor run attempt is invalid")
        for key in ("certificate_hash", "chain_hash", "checkpoint_sha256"):
            _require_sha256(predecessor[key], f"certificate predecessor {key}")

    checkpoint = certificate["checkpoint"]
    _require_exact_fields(checkpoint, _CHECKPOINT_FIELDS, "certificate checkpoint")
    for key in (
        "file_sha256",
        "payload_sha256",
        "session_hash",
        "canonical_prefix_sha256",
        "daily_prefix_sha256",
        "production_state_hash",
    ):
        _require_sha256(checkpoint[key], f"certificate checkpoint {key}")
    for key in ("next_session_hash",):
        if checkpoint[key] is not None:
            _require_sha256(checkpoint[key], f"certificate checkpoint {key}")
    if checkpoint["next_session"] is None and checkpoint["next_session_hash"] is not None:
        raise RuntimeError("certificate next-session hash lacks next session")
    if isinstance(checkpoint["expected_pointer"], bool) or not isinstance(
        checkpoint["expected_pointer"], int
    ) or checkpoint["expected_pointer"] <= 0:
        raise RuntimeError("certificate checkpoint pointer is invalid")

    metrics = certificate["metrics"]
    _require_exact_fields(metrics, _METRICS_FIELDS, "certificate metrics")
    if metrics["measurement_start"] != MEASUREMENT_START:
        raise RuntimeError("certificate measurement anchor mismatch")
    if metrics["end"] != certificate["segment_end"]:
        raise RuntimeError("certificate metrics end mismatch")
    _validate_metric_block(metrics["Production"], "Production metrics")
    _validate_metric_block(metrics["SPY"], "SPY metrics")

    evidence = certificate["evidence_sha256"]
    if not isinstance(evidence, Mapping) or not evidence:
        raise RuntimeError("certificate evidence map is empty")
    for key, digest in evidence.items():
        if not isinstance(key, str) or not key:
            raise RuntimeError("certificate evidence key is invalid")
        _require_sha256(digest, f"certificate evidence {key}")

    complete = year == FINAL_YEAR and certificate["segment_end"] == FINAL_END
    if certificate["complete_20_year_certificate"] is not complete:
        raise RuntimeError("annual certificate completion flag is invalid")

    body = {
        key: copy.deepcopy(value)
        for key, value in certificate.items()
        if key not in {"certificate_hash", "chain_hash"}
    }
    certificate_hash = _json_hash(body)
    if certificate["certificate_hash"] != certificate_hash:
        raise RuntimeError("annual certificate content hash mismatch")
    previous_chain = None if predecessor is None else predecessor["chain_hash"]
    expected_chain = hashlib.sha256(
        ((previous_chain or "GENESIS") + "\n" + certificate_hash).encode("utf-8")
    ).hexdigest()
    if certificate["chain_hash"] != expected_chain:
        raise RuntimeError("annual certificate chain hash mismatch")


def validate_chain(chain: Mapping) -> list[dict]:
    _require_exact_fields(
        chain,
        {"schema", "chain_generation", "certificates", "chain_hash"},
        "certificate chain",
    )
    if chain["schema"] != CHAIN_SCHEMA or chain["chain_generation"] != CHAIN_GENERATION:
        raise RuntimeError("certificate chain schema/generation mismatch")
    certificates = chain["certificates"]
    if not isinstance(certificates, list) or not certificates:
        raise RuntimeError("certificate chain is empty")
    for index, certificate in enumerate(certificates):
        validate_certificate(certificate)
        expected_year = FIRST_YEAR + index
        if certificate["year"] != expected_year:
            raise RuntimeError("certificate chain years are not contiguous from genesis")
        if index:
            previous = certificates[index - 1]
            link = certificate["predecessor"]
            if link["certificate_hash"] != previous["certificate_hash"]:
                raise RuntimeError("certificate chain predecessor content hash mismatch")
            if link["chain_hash"] != previous["chain_hash"]:
                raise RuntimeError("certificate chain predecessor chain hash mismatch")
            if link["checkpoint_sha256"] != previous["checkpoint"]["file_sha256"]:
                raise RuntimeError("certificate chain predecessor checkpoint mismatch")
    if chain["chain_hash"] != certificates[-1]["chain_hash"]:
        raise RuntimeError("certificate-chain terminal hash mismatch")
    return certificates


def validate_handoff(
    *,
    certificate_path: Path,
    chain_path: Path,
    checkpoint_path: Path,
    expected_year: int,
    source_sha: str,
    workflow_sha: str,
    chain_ref: str,
    dataset_hash: str,
    production_main_sha: str,
    overlay_sha256: str,
    run_id: str,
    run_attempt: int,
    artifact_name: str,
    certificate_hash: str,
    chain_hash: str,
) -> dict:
    """Authenticate the predecessor before any resumed economic session runs."""
    certificate = _load_json(certificate_path.resolve())
    validate_certificate(certificate)
    chain = _load_json(chain_path.resolve())
    certificates = validate_chain(chain)
    if certificates[-1] != certificate:
        raise RuntimeError("predecessor certificate is not the supplied chain tip")
    checkpoint_payload = load_checkpoint(checkpoint_path.resolve())
    checkpoint_envelope = _load_json(checkpoint_path.resolve())
    checkpoint_digest = sha256_file(checkpoint_path.resolve())
    expected = {
        "year": expected_year,
        "source_sha": source_sha,
        "workflow_sha": workflow_sha,
        "chain_ref": chain_ref,
        "dataset_hash": dataset_hash,
        "production_main_sha": production_main_sha,
        "production_overlay_sha256": overlay_sha256,
        "run_id": str(run_id),
        "run_attempt": int(run_attempt),
        "artifact_name": artifact_name,
        "certificate_hash": certificate_hash,
        "chain_hash": chain_hash,
    }
    if certificate["year"] != expected["year"]:
        raise RuntimeError("predecessor handoff year mismatch")
    for key in (
        "source_sha",
        "workflow_sha",
        "chain_ref",
        "dataset_hash",
        "production_main_sha",
        "production_overlay_sha256",
    ):
        if certificate["identities"][key] != expected[key]:
            raise RuntimeError(f"predecessor handoff {key} mismatch")
    if certificate["current_run"] != {
        "id": expected["run_id"],
        "attempt": expected["run_attempt"],
        "artifact_name": expected["artifact_name"],
    }:
        raise RuntimeError("predecessor handoff run/artifact identity mismatch")
    if certificate["certificate_hash"] != expected["certificate_hash"]:
        raise RuntimeError("predecessor handoff certificate hash mismatch")
    if certificate["chain_hash"] != expected["chain_hash"]:
        raise RuntimeError("predecessor handoff chain hash mismatch")
    if certificate["checkpoint"]["file_sha256"] != checkpoint_digest:
        raise RuntimeError("predecessor certificate does not authenticate checkpoint")
    if certificate["checkpoint"]["payload_sha256"] != checkpoint_envelope["payload_sha256"]:
        raise RuntimeError("predecessor certificate does not authenticate checkpoint payload")
    checkpoint_chain = checkpoint_payload["chain"]
    checkpoint_daily = checkpoint_payload["daily"]
    checkpoint_production = checkpoint_payload["states"]["production"]
    linked_values = {
        "session_hash": checkpoint_chain["session_hash"],
        "canonical_prefix_sha256": checkpoint_chain["canonical_prefix_sha256"],
        "daily_prefix_sha256": checkpoint_daily["prefix_sha256"],
        "expected_pointer": checkpoint_chain["expected_pointer"],
        "production_state_hash": checkpoint_production["state_hash"],
        "next_session": checkpoint_chain["next_session"],
        "next_session_hash": checkpoint_chain["next_session_hash"],
    }
    for key, value in linked_values.items():
        if certificate["checkpoint"][key] != value:
            raise RuntimeError(f"predecessor certificate checkpoint {key} mismatch")
    if checkpoint_payload["identities"]["backtester_sha"] != source_sha:
        raise RuntimeError("predecessor checkpoint source SHA mismatch")
    if checkpoint_payload["canonical"]["dataset_hash"] != dataset_hash:
        raise RuntimeError("predecessor checkpoint canonical dataset mismatch")
    if checkpoint_payload["identities"]["production_main_sha"] != production_main_sha:
        raise RuntimeError("predecessor checkpoint production source mismatch")
    if checkpoint_payload["identities"]["production_overlay_sha256"] != overlay_sha256:
        raise RuntimeError("predecessor checkpoint Production overlay mismatch")
    if checkpoint_payload["chain"]["segment_year"] != expected_year:
        raise RuntimeError("predecessor checkpoint year mismatch")
    print(
        f"[HANDOFF PASS] Production year={expected_year} "
        f"certificate={certificate_hash} checkpoint={checkpoint_digest}",
        flush=True,
    )
    return certificate


def compare_resume(
    *,
    uninterrupted_output: Path,
    resumed_output: Path,
    uninterrupted_checkpoint: Path,
    resumed_checkpoint: Path,
    split_checkpoint: Path,
    output: Path,
) -> dict:
    uninterrupted_payload = load_checkpoint(uninterrupted_checkpoint.resolve())
    resumed_payload = load_checkpoint(resumed_checkpoint.resolve())
    split_payload = load_checkpoint(split_checkpoint.resolve())
    uninterrupted_previous = uninterrupted_payload["chain"]["previous_checkpoint_sha256"]
    resumed_previous = resumed_payload["chain"]["previous_checkpoint_sha256"]
    split_digest = sha256_file(split_checkpoint.resolve())
    if uninterrupted_previous is not None:
        raise RuntimeError("uninterrupted equivalence checkpoint is not genesis")
    if resumed_previous != split_digest:
        raise RuntimeError("resumed equivalence checkpoint does not bind the split checkpoint")
    if split_payload["chain"]["end_session"] >= resumed_payload["chain"]["end_session"]:
        raise RuntimeError("equivalence split is not a nontrivial earlier boundary")

    uninterrupted_semantic = copy.deepcopy(uninterrupted_payload)
    resumed_semantic = copy.deepcopy(resumed_payload)
    uninterrupted_semantic["chain"]["previous_checkpoint_sha256"] = None
    resumed_semantic["chain"]["previous_checkpoint_sha256"] = None
    if uninterrupted_semantic != resumed_semantic:
        raise RuntimeError("uninterrupted and resumed Production restart state diverged")

    files = (
        "daily.csv.gz",
        "metrics.csv",
        "summary.json",
        "manifest.json",
        "SHA256SUMS.txt",
        "metadata_authority_audit.json",
        "canonical_input_session_hashes.csv",
    )
    output_hashes: dict[str, str] = {}
    for name in files:
        left = uninterrupted_output / name
        right = resumed_output / name
        if not left.is_file() or not right.is_file():
            raise RuntimeError(f"equivalence output is missing {name}")
        left_hash = sha256_file(left)
        if sha256_file(right) != left_hash:
            raise RuntimeError(f"uninterrupted and resumed Production {name} differ")
        output_hashes[name] = left_hash

    audit_body = {
        "schema": EQUIVALENCE_SCHEMA,
        "status": "PASS",
        "source_sha": uninterrupted_payload["identities"]["backtester_sha"],
        "dataset_hash": uninterrupted_payload["canonical"]["dataset_hash"],
        "end_session": uninterrupted_payload["chain"]["end_session"],
        "split_session": split_payload["chain"]["end_session"],
        "uninterrupted_checkpoint_sha256": sha256_file(uninterrupted_checkpoint),
        "resumed_checkpoint_sha256": sha256_file(resumed_checkpoint),
        "split_checkpoint_sha256": split_digest,
        "semantic_payload_sha256": hash_value(uninterrupted_semantic),
        "output_sha256": dict(sorted(output_hashes.items())),
    }
    audit = {**audit_body, "audit_hash": _json_hash(audit_body)}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(audit, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        f"[EQUIVALENCE PASS] Production uninterrupted/resume through "
        f"{audit['end_session']} hash={audit['audit_hash']}",
        flush=True,
    )
    return audit


def _validate_equivalence(
    path: Path,
    payload: Mapping,
    source_sha: str,
    dataset_hash: str,
    checkpoint_digest: str,
) -> str:
    audit = _load_json(path)
    expected = {
        "schema",
        "status",
        "source_sha",
        "dataset_hash",
        "end_session",
        "split_session",
        "uninterrupted_checkpoint_sha256",
        "resumed_checkpoint_sha256",
        "split_checkpoint_sha256",
        "semantic_payload_sha256",
        "output_sha256",
        "audit_hash",
    }
    _require_exact_fields(audit, expected, "resume-equivalence audit")
    if audit["schema"] != EQUIVALENCE_SCHEMA or audit["status"] != "PASS":
        raise RuntimeError("resume-equivalence audit is not PASS")
    if audit["source_sha"] != source_sha or audit["dataset_hash"] != dataset_hash:
        raise RuntimeError("resume-equivalence identity mismatch")
    if audit["split_session"] != payload["chain"]["end_session"]:
        raise RuntimeError("resume-equivalence split is not the certified genesis boundary")
    if audit["split_checkpoint_sha256"] != checkpoint_digest:
        raise RuntimeError("resume-equivalence split checkpoint mismatch")
    if audit["end_session"] <= audit["split_session"]:
        raise RuntimeError("resume-equivalence continuation is not nontrivial")
    body = {key: value for key, value in audit.items() if key != "audit_hash"}
    if audit["audit_hash"] != _json_hash(body):
        raise RuntimeError("resume-equivalence audit hash mismatch")
    return sha256_file(path)


def issue_certificate(args: argparse.Namespace) -> dict:
    checkpoint_path = args.checkpoint.resolve()
    checkpoint_payload = load_checkpoint(checkpoint_path)
    checkpoint_envelope = _load_json(checkpoint_path)
    chain_state = checkpoint_payload["chain"]
    identities_state = checkpoint_payload["identities"]
    canonical_state = checkpoint_payload["canonical"]

    if identities_state["backtester_sha"] != args.source_sha:
        raise RuntimeError("checkpoint source SHA mismatch")
    if identities_state["production_main_sha"] != args.production_main_sha:
        raise RuntimeError("checkpoint production source mismatch")
    if identities_state["production_overlay_sha256"] != args.overlay_sha256:
        raise RuntimeError("checkpoint Production overlay mismatch")
    if canonical_state["dataset_hash"] != args.dataset_hash:
        raise RuntimeError("checkpoint canonical dataset mismatch")
    if chain_state["segment_year"] != args.year:
        raise RuntimeError("checkpoint year mismatch")
    if chain_state["end_session"] != args.segment_end:
        raise RuntimeError("checkpoint annual boundary mismatch")
    if chain_state["measurement_start"] != MEASUREMENT_START:
        raise RuntimeError("checkpoint measurement anchor mismatch")
    if args.workflow_sha != args.source_sha:
        raise RuntimeError("workflow SHA must equal the frozen source SHA")

    overlay = _load_json(args.overlay_evidence.resolve())
    if overlay.get("diff_sha256") != args.overlay_sha256:
        raise RuntimeError("Production overlay evidence digest mismatch")
    if not args.overlay_diff.resolve().is_file():
        raise RuntimeError("Production overlay diff evidence is missing")

    metrics, evidence, production_rows = _validate_public_result(
        args.output_root.resolve(),
        checkpoint_payload,
        segment_end=args.segment_end,
        source_sha=args.source_sha,
        dataset_hash=args.dataset_hash,
    )
    checkpoint_digest = sha256_file(checkpoint_path)
    checkpoint_sidecar = Path(str(checkpoint_path) + ".sha256")
    evidence.update({
        "production_checkpoint": checkpoint_digest,
        "production_checkpoint_sidecar": sha256_file(checkpoint_sidecar),
        "production_overlay_evidence": sha256_file(args.overlay_evidence.resolve()),
        "production_overlay_diff": sha256_file(args.overlay_diff.resolve()),
    })

    previous = None
    previous_certificates: list[dict] = []
    predecessor = None
    if args.year == FIRST_YEAR:
        forbidden = (
            args.previous_certificate,
            args.previous_chain,
            args.previous_run_id,
            args.previous_run_attempt,
            args.previous_artifact_name,
            args.expected_previous_certificate_hash,
            args.expected_previous_chain_hash,
        )
        if any(value not in (None, "") for value in forbidden):
            raise RuntimeError("genesis certificate received predecessor inputs")
        if chain_state["previous_checkpoint_sha256"] is not None:
            raise RuntimeError("genesis checkpoint references a predecessor")
        if args.equivalence_audit is None:
            raise RuntimeError("genesis certificate requires restart equivalence evidence")
        evidence["production_resume_equivalence"] = _validate_equivalence(
            args.equivalence_audit.resolve(),
            checkpoint_payload,
            args.source_sha,
            args.dataset_hash,
            checkpoint_digest,
        )
    else:
        required = (
            args.previous_certificate,
            args.previous_chain,
            args.previous_run_id,
            args.previous_run_attempt,
            args.previous_artifact_name,
            args.expected_previous_certificate_hash,
            args.expected_previous_chain_hash,
        )
        if any(value in (None, "") for value in required):
            raise RuntimeError("non-genesis certificate lacks exact predecessor inputs")
        if args.equivalence_audit is not None:
            raise RuntimeError("restart equivalence evidence is genesis-only")
        previous = _load_json(args.previous_certificate.resolve())
        validate_certificate(previous)
        previous_chain = _load_json(args.previous_chain.resolve())
        previous_certificates = validate_chain(previous_chain)
        if previous_certificates[-1] != previous:
            raise RuntimeError("predecessor certificate is not the chain tip")
        checks = {
            "year": args.year - 1,
            "run_id": str(args.previous_run_id),
            "run_attempt": int(args.previous_run_attempt),
            "artifact_name": args.previous_artifact_name,
            "certificate_hash": args.expected_previous_certificate_hash,
            "chain_hash": args.expected_previous_chain_hash,
        }
        if previous["year"] != checks["year"]:
            raise RuntimeError("predecessor certificate year mismatch")
        if previous["current_run"]["id"] != checks["run_id"]:
            raise RuntimeError("predecessor run ID mismatch")
        if previous["current_run"]["attempt"] != checks["run_attempt"]:
            raise RuntimeError("predecessor run attempt mismatch")
        if previous["current_run"]["artifact_name"] != checks["artifact_name"]:
            raise RuntimeError("predecessor artifact name mismatch")
        if previous["certificate_hash"] != checks["certificate_hash"]:
            raise RuntimeError("predecessor certificate dispatch hash mismatch")
        if previous["chain_hash"] != checks["chain_hash"]:
            raise RuntimeError("predecessor chain dispatch hash mismatch")
        for key in (
            "source_sha",
            "workflow_sha",
            "chain_ref",
            "production_main_sha",
            "production_overlay_sha256",
            "dataset_hash",
        ):
            current = {
                "source_sha": args.source_sha,
                "workflow_sha": args.workflow_sha,
                "chain_ref": args.chain_ref,
                "production_main_sha": args.production_main_sha,
                "production_overlay_sha256": args.overlay_sha256,
                "dataset_hash": args.dataset_hash,
            }[key]
            if previous["identities"][key] != current:
                raise RuntimeError(f"predecessor {key} mismatch")
        if chain_state["previous_checkpoint_sha256"] != previous["checkpoint"]["file_sha256"]:
            raise RuntimeError("checkpoint does not link to certified predecessor")
        predecessor = {
            **checks,
            "checkpoint_sha256": previous["checkpoint"]["file_sha256"],
        }

    production_state = checkpoint_payload["states"]["production"]
    body = {
        "schema": SCHEMA,
        "chain_generation": CHAIN_GENERATION,
        "status": "PASS",
        "year": args.year,
        "segment_end": args.segment_end,
        "identities": {
            "source_sha": args.source_sha,
            "workflow_sha": args.workflow_sha,
            "chain_ref": args.chain_ref,
            "production_main_sha": args.production_main_sha,
            "production_overlay_sha256": args.overlay_sha256,
            "dataset_hash": args.dataset_hash,
            "checkpoint_schema": CHECKPOINT_SCHEMA,
            "checkpoint_format_generation": CHECKPOINT_FORMAT_GENERATION,
        },
        "current_run": {
            "id": str(args.run_id),
            "attempt": int(args.run_attempt),
            "artifact_name": args.artifact_name,
        },
        "predecessor": predecessor,
        "checkpoint": {
            "file_sha256": checkpoint_digest,
            "payload_sha256": checkpoint_envelope["payload_sha256"],
            "session_hash": chain_state["session_hash"],
            "canonical_prefix_sha256": chain_state["canonical_prefix_sha256"],
            "daily_prefix_sha256": checkpoint_payload["daily"]["prefix_sha256"],
            "expected_pointer": chain_state["expected_pointer"],
            "production_state_hash": production_state["state_hash"],
            "next_session": chain_state["next_session"],
            "next_session_hash": chain_state["next_session_hash"],
        },
        "metrics": metrics,
        "evidence_sha256": dict(sorted(evidence.items())),
        "complete_20_year_certificate": (
            args.year == FINAL_YEAR and args.segment_end == FINAL_END
        ),
    }
    certificate_hash = _json_hash(body)
    previous_chain_hash = None if previous is None else previous["chain_hash"]
    chain_hash = hashlib.sha256(
        ((previous_chain_hash or "GENESIS") + "\n" + certificate_hash).encode("utf-8")
    ).hexdigest()
    certificate = {
        **body,
        "certificate_hash": certificate_hash,
        "chain_hash": chain_hash,
    }
    validate_certificate(certificate)

    chain = {
        "schema": CHAIN_SCHEMA,
        "chain_generation": CHAIN_GENERATION,
        "certificates": [*previous_certificates, certificate],
        "chain_hash": chain_hash,
    }
    validate_chain(chain)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(certificate, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    args.chain_output.parent.mkdir(parents=True, exist_ok=True)
    args.chain_output.write_text(
        json.dumps(chain, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    _append_step_summary(certificate, args.step_summary)
    print(json.dumps(certificate, indent=2, sort_keys=True), flush=True)
    return certificate


def _append_step_summary(certificate: Mapping, path: Path | None) -> None:
    if path is None:
        raw = os.environ.get("GITHUB_STEP_SUMMARY", "").strip()
        path = Path(raw) if raw else None
    if path is None:
        return
    metrics = certificate["metrics"]
    lines = [
        f"## Production PIT annual certificate — {certificate['year']}",
        "",
        f"Certified through `{certificate['segment_end']}` from the "
        f"`{metrics['measurement_start']}` measurement anchor.",
        "",
        "| Series | Ending multiple | Cumulative CAGR | Sharpe | Maximum drawdown |",
        "|---|---:|---:|---:|---:|",
    ]
    for role in ("Production", "SPY"):
        block = metrics[role]
        lines.append(
            f"| {role} | {block['ending_multiple']:.6f} | {block['cagr']:.4%} | "
            f"{block['sharpe']:.4f} | {block['max_drawdown']:.4%} |"
        )
    lines.extend([
        "",
        f"Certificate: `{certificate['certificate_hash']}`",
        f"Chain: `{certificate['chain_hash']}`",
        "",
    ])
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write("\n".join(lines))


def _add_issue_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--year", type=int, required=True)
    parser.add_argument("--segment-end", required=True)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--workflow-sha", required=True)
    parser.add_argument("--chain-ref", required=True)
    parser.add_argument("--dataset-hash", required=True)
    parser.add_argument("--production-main-sha", required=True)
    parser.add_argument("--overlay-sha256", required=True)
    parser.add_argument("--overlay-evidence", type=Path, required=True)
    parser.add_argument("--overlay-diff", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--run-attempt", type=int, required=True)
    parser.add_argument("--artifact-name", required=True)
    parser.add_argument("--previous-certificate", type=Path)
    parser.add_argument("--previous-chain", type=Path)
    parser.add_argument("--previous-run-id")
    parser.add_argument("--previous-run-attempt", type=int)
    parser.add_argument("--previous-artifact-name")
    parser.add_argument("--expected-previous-certificate-hash")
    parser.add_argument("--expected-previous-chain-hash")
    parser.add_argument("--equivalence-audit", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--chain-output", type=Path, required=True)
    parser.add_argument("--step-summary", type=Path)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    issue = subparsers.add_parser("issue")
    _add_issue_arguments(issue)
    compare = subparsers.add_parser("compare-resume")
    compare.add_argument("--uninterrupted-output", type=Path, required=True)
    compare.add_argument("--resumed-output", type=Path, required=True)
    compare.add_argument("--uninterrupted-checkpoint", type=Path, required=True)
    compare.add_argument("--resumed-checkpoint", type=Path, required=True)
    compare.add_argument("--split-checkpoint", type=Path, required=True)
    compare.add_argument("--output", type=Path, required=True)
    handoff = subparsers.add_parser("validate-handoff")
    handoff.add_argument("--certificate", type=Path, required=True)
    handoff.add_argument("--chain", type=Path, required=True)
    handoff.add_argument("--checkpoint", type=Path, required=True)
    handoff.add_argument("--expected-year", type=int, required=True)
    handoff.add_argument("--source-sha", required=True)
    handoff.add_argument("--workflow-sha", required=True)
    handoff.add_argument("--chain-ref", required=True)
    handoff.add_argument("--dataset-hash", required=True)
    handoff.add_argument("--production-main-sha", required=True)
    handoff.add_argument("--overlay-sha256", required=True)
    handoff.add_argument("--run-id", required=True)
    handoff.add_argument("--run-attempt", type=int, required=True)
    handoff.add_argument("--artifact-name", required=True)
    handoff.add_argument("--certificate-hash", required=True)
    handoff.add_argument("--chain-hash", required=True)
    args = parser.parse_args(argv)
    if args.command == "issue":
        issue_certificate(args)
    elif args.command == "compare-resume":
        compare_resume(
            uninterrupted_output=args.uninterrupted_output.resolve(),
            resumed_output=args.resumed_output.resolve(),
            uninterrupted_checkpoint=args.uninterrupted_checkpoint.resolve(),
            resumed_checkpoint=args.resumed_checkpoint.resolve(),
            split_checkpoint=args.split_checkpoint.resolve(),
            output=args.output.resolve(),
        )
    else:
        validate_handoff(
            certificate_path=args.certificate,
            chain_path=args.chain,
            checkpoint_path=args.checkpoint,
            expected_year=args.expected_year,
            source_sha=args.source_sha,
            workflow_sha=args.workflow_sha,
            chain_ref=args.chain_ref,
            dataset_hash=args.dataset_hash,
            production_main_sha=args.production_main_sha,
            overlay_sha256=args.overlay_sha256,
            run_id=args.run_id,
            run_attempt=args.run_attempt,
            artifact_name=args.artifact_name,
            certificate_hash=args.certificate_hash,
            chain_hash=args.chain_hash,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
