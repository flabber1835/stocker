"""Synthetic actual-producer records for authority evidence integration tests."""
from __future__ import annotations

import base64
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform

from tools import wealth_core_baseline_run as baseline


APPROVED_CERTIFICATION_REVISION = (
    "7f12174273dfa071a25614d2c4a1be8ebfdfbc3a")
APPROVED_EXPECTED_HASH_PRODUCER_SHA256 = (
    "8ea492a9f53d1f3cb6ba28ca3c6f5d50d1471942772b5fa04832fdd7d215c2b4")


def external_loader_bundle() -> dict:
    """Return the loader manifest preserved at the approved certification pin."""
    sources = {
        "services/backtester/app/wealth_core_replay.py":
            "03c966510fe47b6572c6f2c629797e3a898a6ed3ec14114e7d094b92d558142a",
        "services/backtester/app/wealth_core_replay_impl.py":
            "2ebce6ca026f944b812ab2b0bf290db5eaa4df7b42a12710b6f3bb41613c2f7d",
        "shared/stock_strategy_shared/split_reconciliation.py":
            "a32f6698763bfd110b309fc42d9bb39b1c2e0272bd81e5ff659a5f7a5017dfd7",
    }
    payload = {
        "schema": "wealth_core.canonical-loader-bundle/1",
        "sources": sources,
    }
    payload["sha256"] = hashlib.sha256(json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        allow_nan=False).encode("ascii")).hexdigest()
    return payload


def complete_expected(value: dict) -> dict:
    """Fill only producer fields needed by the formal baseline contract."""
    from stock_strategy_shared.runtime_identity import wealth_core_baseline_identity

    value["window"].update({
        "requested_start": "2021-01-04", "requested_end": "2023-12-29"})
    value["corpus"].update({
        "status": "READY", "source_mode": "sharadar",
        "split_source": "actions"})
    behavior = wealth_core_baseline_identity()
    value["run"].update({
        "starting_cash": 1_000_000.0,
        "config_hash": behavior["engine_config_hash"],
        "behavior_identity": behavior,
    })
    return value


def complete_manifest(value: dict) -> dict:
    value.update({
        "git_tree_clean": True,
        "bt_engine_app_source_hash": "6" * 64,
        "bt_engine_image": {
            "id": "sha256:" + "7" * 64,
            "ref": "stocker-bt-engine@sha256:" + "8" * 64,
            "source_revision": value["git_commit"],
            "repo_digests": ["stocker-bt-engine@sha256:" + "8" * 64],
        },
        "bt_engine_runtime_identity": {
            "requirements_lock_sha256": value["requirements_lock_sha256"],
            "distributions_sha256": "9" * 64,
            "distributions_count": 10,
        },
    })
    return value


def write_record(*, expected_path: Path, manifest_path: Path,
                 output: Path) -> dict:
    expected_raw = expected_path.read_bytes()
    manifest_raw = manifest_path.read_bytes()
    expected = json.loads(expected_raw)
    manifest = json.loads(manifest_raw)
    request = baseline.canonical_request(expected)
    run_id = "11111111-1111-4111-8111-111111111111"
    started = "2026-08-13T10:00:00Z"
    accepted = "2026-08-13T10:00:01Z"
    recorded = "2026-08-13T10:00:03Z"
    engine = {
        "python": platform.python_version(),
        "wealth_core_source_hash": manifest["wealth_core_source_hash"],
        "bt_engine_app_source_hash": manifest["bt_engine_app_source_hash"],
        "image_id": manifest["bt_engine_image"]["id"],
        "image_ref": manifest["bt_engine_image"]["ref"],
        "source_revision": manifest["git_commit"],
        **manifest["bt_engine_runtime_identity"],
    }
    row = {
        "run_id": run_id, "mode": "baseline_replay", "status": "success",
        "started_at": started, "completed_at": "2026-08-13T10:00:02Z",
        "spec": {**request, "engine_identity": engine,
                 "baseline_identity": expected["run"]["behavior_identity"]},
        "summary": {
            "divergence": {"identical": True},
            "provenance": {
                "bt_data_version": expected["corpus"]["version"],
                "bt_data_status": "READY", "bt_data_source_mode": "sharadar",
                "split_source": "actions",
            },
        },
        "parity_hashes": expected["hashes"], "error_message": None,
    }
    argv = ["python", "-m", "tools.wealth_core_baseline_run",
            "--expected-hashes", str(expected_path), "--manifest",
            str(manifest_path), "--bt-engine-url", "http://127.0.0.1:8031",
            "--output", str(output)]
    entries = [
        {"event": "invocation_started", "at": started,
         "request_sha256": baseline.canonical_sha256(request)},
        {"event": "run_accepted", "at": accepted, "run_id": run_id},
        {"event": "row_observed", "at": recorded, "run_id": run_id,
         "status": "success"},
    ]
    producer_path = Path(baseline.__file__).resolve()
    record = {
        "schema": baseline.SCHEMA, "status": "success", "run_id": run_id,
        "invocation": {
            "invocation_id": "22222222-2222-4222-8222-222222222222",
            "argv": argv, "argv_sha256": baseline.canonical_sha256(argv),
            "started_at": started, "accepted_at": accepted,
            "recorded_at": recorded,
            "endpoint": {"base_url": "http://127.0.0.1:8031",
                         "submit_path": "/wealth-core/jobs/run",
                         "row_path": f"/wealth-core/runs/{run_id}"},
            "request": request,
            "request_sha256": baseline.canonical_sha256(request),
            "producer": {
                "path": baseline.PRODUCER,
                "sha256": hashlib.sha256(producer_path.read_bytes()).hexdigest(),
                "python": platform.python_version()},
            "log": {"entries": entries,
                    "sha256": baseline.canonical_sha256(entries)},
        },
        "expected_hashes": {
            "sha256": hashlib.sha256(expected_raw).hexdigest(),
            "bytes_base64": base64.b64encode(expected_raw).decode("ascii"),
            "artifact": expected},
        "certification_manifest": {
            "sha256": hashlib.sha256(manifest_raw).hexdigest(),
            "bytes_base64": base64.b64encode(manifest_raw).decode("ascii"),
            "artifact": manifest},
        "terminal_run": {
            "sha256": baseline.canonical_sha256(row), "row": row},
        "outcome": {
            "status": "success", "divergence_identical": True,
            "parity_hashes_sha256": baseline.canonical_sha256(
                expected["hashes"]),
            "bt_data_version": str(expected["corpus"]["version"]),
            "bt_data_status": "READY", "bt_data_source_mode": "sharadar",
            "split_source": "actions",
        },
    }
    baseline.validate_record(record)
    baseline.write_record_atomic(output, record)
    return record
