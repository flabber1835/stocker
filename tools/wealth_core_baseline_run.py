"""Invoke and retain one formal Wealth Core baseline authority record.

This is intentionally an invocation surface, not an exporter.  It has no
``--run-id`` or JSON-row input: a portable row can be useful audit material but
cannot prove which engine this process invoked.  One process validates the
retained inputs, submits the canonical request, polls that exact run UUID, and
atomically publishes the complete authority record.
"""
from __future__ import annotations

import argparse
import base64
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import re
import secrets
import sys
import time
from typing import Any, Callable, Mapping, Sequence
import urllib.error
import urllib.parse
import urllib.request
import uuid


SCHEMA = "sentinel.wealth-core-baseline-run/1"
PRODUCER = "tools/wealth_core_baseline_run.py"
EXPECTED_SCHEMA = "wealth_core_expected_hashes.v1"
MANIFEST_SCHEMA = "sentinel.certification_manifest/2"
CANONICAL_STARTING_CASH = 1_000_000.0
_SHA = re.compile(r"[0-9a-f]{64}")
_IMAGE = re.compile(r"sha256:[0-9a-f]{64}")
_GIT = re.compile(r"[0-9a-f]{40}")

TOP_FIELDS = {
    "schema", "status", "run_id", "invocation", "expected_hashes",
    "certification_manifest", "terminal_run", "outcome",
}
INVOCATION_FIELDS = {
    "invocation_id", "argv", "argv_sha256", "started_at", "accepted_at",
    "recorded_at", "endpoint", "request", "request_sha256", "producer",
    "log",
}
ENDPOINT_FIELDS = {"base_url", "submit_path", "row_path"}
PRODUCER_FIELDS = {"path", "sha256", "python"}
LOG_FIELDS = {"entries", "sha256"}
BOUND_FIELDS = {"sha256", "bytes_base64", "artifact"}
TERMINAL_FIELDS = {"sha256", "row"}
OUTCOME_FIELDS = {
    "status", "divergence_identical", "parity_hashes_sha256",
    "bt_data_version", "bt_data_status", "bt_data_source_mode",
    "split_source",
}
ROW_FIELDS = {
    "run_id", "mode", "status", "started_at", "completed_at", "spec",
    "summary", "parity_hashes", "error_message",
}
ENGINE_FIELDS = {
    "python", "wealth_core_source_hash", "bt_engine_app_source_hash",
    "image_id", "image_ref", "source_revision",
    "requirements_lock_sha256", "distributions_sha256",
    "distributions_count",
}


class BaselineRunRefused(RuntimeError):
    """The invocation cannot produce formal baseline authority."""


def canonical_bytes(value: Any) -> bytes:
    try:
        return json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
            allow_nan=False).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise BaselineRunRefused("record is not canonical JSON") from exc


def sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def canonical_sha256(value: Any) -> str:
    return sha256(canonical_bytes(value))


def _object(value: Any, *, label: str, fields: set[str]) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise BaselineRunRefused(f"{label} is not an object")
    actual = set(value)
    if actual != fields:
        raise BaselineRunRefused(
            f"{label} fields differ: missing={sorted(fields - actual)}, "
            f"unknown={sorted(actual - fields)}")
    return value


def _hex(value: Any, *, label: str, image: bool = False,
         git: bool = False) -> str:
    pattern = _IMAGE if image else _GIT if git else _SHA
    if not isinstance(value, str) or pattern.fullmatch(value) is None:
        raise BaselineRunRefused(f"{label} is not canonical")
    return value


def _iso(value: Any, *, label: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise BaselineRunRefused(f"{label} is not a timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise BaselineRunRefused(f"{label} is not an ISO timestamp") from exc
    if parsed.tzinfo is None:
        raise BaselineRunRefused(f"{label} has no timezone")
    return parsed


def _uuid(value: Any, *, label: str) -> str:
    try:
        parsed = uuid.UUID(str(value))
    except (ValueError, TypeError) as exc:
        raise BaselineRunRefused(f"{label} is not a UUID") from exc
    if str(parsed) != str(value):
        raise BaselineRunRefused(f"{label} is not a canonical UUID")
    return str(parsed)


def _producer_path() -> Path:
    return Path(__file__).resolve()


def _expected(artifact: Mapping[str, Any]) -> tuple[dict[str, str], str]:
    if artifact.get("schema") != EXPECTED_SCHEMA or artifact.get("status") != "ready":
        raise BaselineRunRefused("expected-hash artifact is not ready schema v1")
    hashes = artifact.get("hashes")
    from stock_strategy_shared.wealth_core.hashes import HASH_ORDER
    if not isinstance(hashes, Mapping) or set(hashes) != set(HASH_ORDER):
        raise BaselineRunRefused("expected hashes are not exact HASH_ORDER")
    values = {str(key): _hex(hashes[key], label=f"expected hashes.{key}")
              for key in HASH_ORDER}
    corpus = artifact.get("corpus")
    run = artifact.get("run")
    window = artifact.get("window")
    provenance = artifact.get("provenance")
    if not all(isinstance(value, Mapping) for value in (
            corpus, run, window, provenance)):
        raise BaselineRunRefused("expected-hash artifact is incomplete")
    if (corpus.get("status") != "READY"
            or corpus.get("source_mode") != "sharadar"
            or corpus.get("split_source") != "actions"
            or not corpus.get("version")):
        raise BaselineRunRefused("expected hashes do not bind a READY Sharadar ACTIONS corpus")
    if run.get("starting_cash") != CANONICAL_STARTING_CASH:
        raise BaselineRunRefused("expected hashes do not bind canonical starting cash")
    if (not isinstance(run.get("config_hash"), str)
            or re.fullmatch(r"[0-9a-f]{16}", run["config_hash"]) is None):
        raise BaselineRunRefused("expected run.config_hash is not canonical")
    from stock_strategy_shared.runtime_identity import wealth_core_baseline_identity
    behavior = run.get("behavior_identity")
    if behavior != wealth_core_baseline_identity():
        raise BaselineRunRefused(
            "expected hashes do not bind the canonical config/eligibility/cash identity")
    if run["config_hash"] != behavior["engine_config_hash"]:
        raise BaselineRunRefused(
            "expected run config differs from its behavior identity")
    for field in ("requested_start", "requested_end"):
        if not isinstance(window.get(field), str) or not window[field]:
            raise BaselineRunRefused(f"expected window.{field} is missing")
    return values, str(corpus["version"])


def _manifest(artifact: Mapping[str, Any]) -> tuple[Mapping[str, Any], Mapping[str, Any]]:
    if (artifact.get("schema") != MANIFEST_SCHEMA
            or artifact.get("lifecycle") != "FINALIZED"
            or artifact.get("verdict") != "PASS"
            or artifact.get("failures") != []):
        raise BaselineRunRefused("certification manifest is not FINALIZED/PASS schema /2")
    if artifact.get("git_tree_clean") is not True:
        raise BaselineRunRefused("certification manifest was not frozen from a clean tree")
    _hex(artifact.get("git_commit"), label="manifest git_commit", git=True)
    image = artifact.get("bt_engine_image")
    runtime = artifact.get("bt_engine_runtime_identity")
    if not isinstance(image, Mapping) or not isinstance(runtime, Mapping):
        raise BaselineRunRefused("manifest has no bt-engine image/runtime identity")
    _hex(image.get("id"), label="manifest bt-engine image id", image=True)
    image_revision = _hex(
        image.get("source_revision"),
        label="manifest bt-engine source revision", git=True)
    if image_revision != artifact["git_commit"]:
        raise BaselineRunRefused(
            "manifest bt-engine image revision differs from frozen commit")
    if not isinstance(image.get("ref"), str) or not image["ref"]:
        raise BaselineRunRefused("manifest bt-engine image reference is missing")
    _hex(artifact.get("bt_engine_app_source_hash"), label="manifest bt-engine app source")
    _hex(artifact.get("wealth_core_source_hash"), label="manifest Wealth Core source")
    for field in ("requirements_lock_sha256", "distributions_sha256"):
        _hex(runtime.get(field), label=f"manifest bt-engine runtime {field}")
    if type(runtime.get("distributions_count")) is not int or runtime["distributions_count"] < 1:
        raise BaselineRunRefused("manifest bt-engine distribution count is invalid")
    parity = artifact.get("parity_generations")
    if not isinstance(parity, Mapping) or not parity.get("canonical_data_version"):
        raise BaselineRunRefused("manifest has no canonical corpus generation")
    if not artifact.get("final_corpus_hash"):
        raise BaselineRunRefused("manifest has no finalized corpus hash")
    return image, runtime


def canonical_request(expected: Mapping[str, Any]) -> dict[str, Any]:
    hashes, version = _expected(expected)
    window = expected["window"]
    return {
        "mode": "baseline_replay",
        "start_date": window["requested_start"],
        "end_date": window["requested_end"],
        "starting_cash": CANONICAL_STARTING_CASH,
        "config": {},
        "eligibility": {},
        "change": {},
        "baseline_hashes": None,
        "expected_hashes": hashes,
        "expected_data_version": version,
        "retention_mode": "full",
        "retention_tail": 50,
    }


def _validated_base_url(value: Any) -> str:
    if not isinstance(value, str) or not value:
        raise BaselineRunRefused("invocation endpoint base URL is malformed")
    parsed = urllib.parse.urlsplit(value)
    if (parsed.scheme != "http" or parsed.hostname not in {
            "127.0.0.1", "localhost", "::1"}
            or parsed.username is not None or parsed.password is not None
            or parsed.query or parsed.fragment
            or parsed.path not in {"", "/"}):
        raise BaselineRunRefused(
            "formal baseline invocation requires a root loopback HTTP endpoint")
    return value.rstrip("/")


def _validate_argv(
        argv: Any, *, base_url: str, expected_path: Path | None = None,
        manifest_path: Path | None = None, output_path: Path | None = None,
        timeout_seconds: float | None = None,
        executable: str | None = None) -> list[str]:
    if (not isinstance(argv, list) or len(argv) < 11
            or any(not isinstance(item, str) or not item for item in argv)
            or argv[1:3] != ["-m", "tools.wealth_core_baseline_run"]):
        raise BaselineRunRefused("invocation argv is not the formal producer command")
    parser = argparse.ArgumentParser(add_help=False, allow_abbrev=False)
    parser.add_argument("--expected-hashes", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--bt-engine-url", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--timeout-seconds", type=float, default=14400.0)
    try:
        parsed = parser.parse_args(argv[3:])
    except SystemExit as exc:
        raise BaselineRunRefused("invocation argv has unknown/missing arguments") from exc
    required_flags = (
        "--expected-hashes", "--manifest", "--bt-engine-url", "--output")
    if (any(argv[3:].count(flag) != 1 for flag in required_flags)
            or argv[3:].count("--timeout-seconds") > 1
            or not math.isfinite(parsed.timeout_seconds)
            or parsed.timeout_seconds <= 0
            or _validated_base_url(parsed.bt_engine_url) != base_url):
        raise BaselineRunRefused("invocation argv endpoint/timeout differs")
    exact_values = (
        (expected_path, Path(parsed.expected_hashes)),
        (manifest_path, Path(parsed.manifest)),
        (output_path, Path(parsed.output)),
    )
    if any(wanted is not None and Path(wanted) != actual
           for wanted, actual in exact_values):
        raise BaselineRunRefused("invocation argv artifact path differs")
    if (timeout_seconds is not None
            and parsed.timeout_seconds != timeout_seconds):
        raise BaselineRunRefused("invocation argv timeout differs")
    if executable is not None and argv[0] != executable:
        raise BaselineRunRefused("invocation argv executable differs")
    return argv


def _validate_log(log: Mapping[str, Any], *, started: datetime,
                  accepted: datetime, recorded: datetime, run_id: str,
                  request_sha: str) -> None:
    entries = log["entries"]
    if not isinstance(entries, list) or len(entries) < 3:
        raise BaselineRunRefused("invocation log is incomplete")
    first = _object(entries[0], label="invocation log start", fields={
        "event", "at", "request_sha256"})
    second = _object(entries[1], label="invocation log acceptance", fields={
        "event", "at", "run_id"})
    if (first["event"] != "invocation_started"
            or first["request_sha256"] != request_sha
            or _iso(first["at"], label="log start at") != started
            or second["event"] != "run_accepted"
            or _uuid(second["run_id"], label="log accepted run") != run_id
            or _iso(second["at"], label="log accepted at") != accepted):
        raise BaselineRunRefused("invocation log start/acceptance differs")
    observed_times: list[datetime] = []
    observed_statuses: list[str] = []
    for index, raw in enumerate(entries[2:], start=2):
        entry = _object(raw, label=f"invocation log entry {index}", fields={
            "event", "at", "run_id", "status"})
        if (entry["event"] != "row_observed"
                or _uuid(entry["run_id"], label=f"log run {index}") != run_id
                or entry["status"] not in {"running", "success"}):
            raise BaselineRunRefused("invocation log contains a foreign event/run/status")
        observed_times.append(_iso(entry["at"], label=f"log observed at {index}"))
        observed_statuses.append(entry["status"])
    all_times = [started, accepted, *observed_times, recorded]
    if (all_times != sorted(all_times) or observed_statuses[-1] != "success"
            or "success" in observed_statuses[:-1]):
        raise BaselineRunRefused("invocation log sequence is not monotonic/terminal")


def _validate_cross_bindings(record: Mapping[str, Any], *,
                             producer_path: Path) -> None:
    expected_slot = _object(record["expected_hashes"], label="expected_hashes",
                            fields=BOUND_FIELDS)
    manifest_slot = _object(record["certification_manifest"],
                            label="certification_manifest", fields=BOUND_FIELDS)
    terminal_slot = _object(record["terminal_run"], label="terminal_run",
                            fields=TERMINAL_FIELDS)
    expected = expected_slot["artifact"]
    manifest = manifest_slot["artifact"]
    row = terminal_slot["row"]
    if not all(isinstance(value, Mapping) for value in (expected, manifest, row)):
        raise BaselineRunRefused("bound artifacts are not objects")
    _hex(expected_slot["sha256"], label="expected_hashes.sha256")
    _hex(manifest_slot["sha256"], label="certification_manifest.sha256")
    _hex(terminal_slot["sha256"], label="terminal_run.sha256")
    try:
        expected_raw = base64.b64decode(expected_slot["bytes_base64"], validate=True)
        manifest_raw = base64.b64decode(manifest_slot["bytes_base64"], validate=True)
    except (TypeError, ValueError) as exc:
        raise BaselineRunRefused("bound input bytes are not canonical base64") from exc
    if (base64.b64encode(expected_raw).decode("ascii")
            != expected_slot["bytes_base64"]
            or base64.b64encode(manifest_raw).decode("ascii")
            != manifest_slot["bytes_base64"]):
        raise BaselineRunRefused("bound input byte encoding is not canonical base64")
    try:
        expected_from_bytes = json.loads(expected_raw.decode("utf-8"))
        manifest_from_bytes = json.loads(manifest_raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BaselineRunRefused("bound input bytes are not UTF-8 JSON") from exc
    if expected_slot["sha256"] != sha256(expected_raw):
        raise BaselineRunRefused("expected-hash binding differs from embedded artifact")
    if manifest_slot["sha256"] != sha256(manifest_raw):
        raise BaselineRunRefused("manifest binding differs from embedded artifact")
    if expected_from_bytes != expected or manifest_from_bytes != manifest:
        raise BaselineRunRefused(
            "bound input bytes parse differently from embedded artifact")
    if terminal_slot["sha256"] != canonical_sha256(row):
        raise BaselineRunRefused("terminal row binding differs from embedded row")
    expected_values, version = _expected(expected)
    image, runtime = _manifest(manifest)

    invocation = _object(record["invocation"], label="invocation",
                         fields=INVOCATION_FIELDS)
    _uuid(invocation["invocation_id"], label="invocation id")
    argv = invocation["argv"]
    if invocation["argv_sha256"] != canonical_sha256(argv):
        raise BaselineRunRefused("invocation argv digest differs")
    started = _iso(invocation["started_at"], label="invocation started_at")
    accepted = _iso(invocation["accepted_at"], label="invocation accepted_at")
    recorded = _iso(invocation["recorded_at"], label="invocation recorded_at")
    if not started <= accepted <= recorded:
        raise BaselineRunRefused("invocation timestamps are not monotonic")
    endpoint = _object(invocation["endpoint"], label="invocation endpoint",
                       fields=ENDPOINT_FIELDS)
    if endpoint["submit_path"] != "/wealth-core/jobs/run":
        raise BaselineRunRefused("invocation used a noncanonical submit path")
    if endpoint["row_path"] != f"/wealth-core/runs/{record['run_id']}":
        raise BaselineRunRefused("invocation did not poll its exact run id")
    base_url = _validated_base_url(endpoint["base_url"])
    _validate_argv(argv, base_url=base_url)
    request = invocation["request"]
    if request != canonical_request(expected):
        raise BaselineRunRefused("invocation request is not canonical expected-hash request")
    if invocation["request_sha256"] != canonical_sha256(request):
        raise BaselineRunRefused("invocation request digest differs")
    producer = _object(invocation["producer"], label="invocation producer",
                       fields=PRODUCER_FIELDS)
    if producer["path"] != PRODUCER:
        raise BaselineRunRefused("record names a noncanonical producer")
    if producer["sha256"] != sha256(producer_path.read_bytes()):
        raise BaselineRunRefused("record producer source digest differs")
    if not isinstance(producer["python"], str) or not producer["python"]:
        raise BaselineRunRefused("record producer interpreter is missing")
    log = _object(invocation["log"], label="invocation log", fields=LOG_FIELDS)
    if log["sha256"] != canonical_sha256(log["entries"]):
        raise BaselineRunRefused("invocation log digest differs")

    _object(row, label="terminal run row", fields=ROW_FIELDS)
    run_id = _uuid(record["run_id"], label="record run id")
    _validate_log(
        log, started=started, accepted=accepted, recorded=recorded,
        run_id=run_id, request_sha=invocation["request_sha256"])
    if _uuid(row["run_id"], label="terminal row run id") != run_id:
        raise BaselineRunRefused("terminal row belongs to a different run")
    if (row["mode"] != "baseline_replay" or row["status"] != "success"
            or row["error_message"] is not None):
        raise BaselineRunRefused("terminal row is not a successful baseline replay")
    row_started = _iso(row["started_at"], label="terminal row started_at")
    row_completed = _iso(row["completed_at"], label="terminal row completed_at")
    if row_completed < row_started or row_started < started or row_completed > recorded:
        raise BaselineRunRefused("terminal row timestamps do not fit invocation")
    spec = row["spec"]
    summary = row["summary"]
    if not isinstance(spec, Mapping) or not isinstance(summary, Mapping):
        raise BaselineRunRefused("terminal row spec/summary is incomplete")
    expected_spec = dict(request)
    engine = spec.get("engine_identity")
    expected_spec["engine_identity"] = engine
    expected_spec["baseline_identity"] = expected["run"]["behavior_identity"]
    if dict(spec) != expected_spec:
        raise BaselineRunRefused("terminal row spec differs from exact submitted request")
    _object(engine, label="terminal engine identity", fields=ENGINE_FIELDS)
    engine_matches = {
        "image_id": image["id"],
        "image_ref": image["ref"],
        "source_revision": manifest["git_commit"],
        "wealth_core_source_hash": manifest["wealth_core_source_hash"],
        "bt_engine_app_source_hash": manifest["bt_engine_app_source_hash"],
        **runtime,
    }
    for field, wanted in engine_matches.items():
        if engine.get(field) != wanted:
            raise BaselineRunRefused(f"terminal engine identity {field} differs from manifest")
    for field in ("image_id",):
        _hex(engine[field], label=f"engine {field}", image=True)
    for field in ("source_revision",):
        _hex(engine[field], label=f"engine {field}", git=True)
    for field in ("wealth_core_source_hash", "bt_engine_app_source_hash",
                  "requirements_lock_sha256", "distributions_sha256"):
        _hex(engine[field], label=f"engine {field}")
    if row["parity_hashes"] != expected_values:
        raise BaselineRunRefused("terminal parity hashes differ from expected hashes")
    divergence = summary.get("divergence")
    provenance = summary.get("provenance")
    if not isinstance(divergence, Mapping) or not isinstance(provenance, Mapping):
        raise BaselineRunRefused("terminal summary lacks divergence/provenance")
    if divergence.get("identical") is not True:
        raise BaselineRunRefused("terminal baseline did not report exact parity")
    if (str(provenance.get("bt_data_version")) != version
            or provenance.get("bt_data_status") != "READY"
            or provenance.get("bt_data_source_mode") != "sharadar"
            or provenance.get("split_source") != "actions"):
        raise BaselineRunRefused("terminal baseline used a different corpus generation/source")

    outcome = _object(record["outcome"], label="outcome", fields=OUTCOME_FIELDS)
    wanted_outcome = {
        "status": "success", "divergence_identical": True,
        "parity_hashes_sha256": canonical_sha256(expected_values),
        "bt_data_version": version, "bt_data_status": "READY",
        "bt_data_source_mode": "sharadar", "split_source": "actions",
    }
    if dict(outcome) != wanted_outcome or record["status"] != "success":
        raise BaselineRunRefused("outcome does not derive from terminal row")


def validate_record(record: Mapping[str, Any], *,
                    producer_path: Path | None = None) -> Mapping[str, Any]:
    """Strictly validate a schema-/1 record and every embedded cross-binding."""
    _object(record, label="baseline record", fields=TOP_FIELDS)
    if record.get("schema") != SCHEMA:
        raise BaselineRunRefused("baseline record schema is unknown")
    path = (producer_path or _producer_path()).resolve()
    if not path.is_file():
        raise BaselineRunRefused("baseline producer source cannot be read")
    _validate_cross_bindings(record, producer_path=path)
    return record


def _json_file(path: Path, *, label: str) -> tuple[bytes, Mapping[str, Any]]:
    raw = path.read_bytes()
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BaselineRunRefused(f"{label} is not UTF-8 JSON") from exc
    if not isinstance(value, Mapping):
        raise BaselineRunRefused(f"{label} root is not an object")
    return raw, value


def _canonical_bound(raw: bytes, value: Mapping[str, Any], *, label: str) -> dict[str, Any]:
    # The input producers intentionally pretty-print operator-facing files.
    # Retain the exact bytes as well as their parsed form; reserializing the
    # object cannot prove a digest over the source artifact.
    return {"sha256": sha256(raw),
            "bytes_base64": base64.b64encode(raw).decode("ascii"),
            "artifact": value}


def _utc(now: Callable[[], datetime]) -> str:
    value = now()
    if value.tzinfo is None:
        raise BaselineRunRefused("clock returned a naive timestamp")
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _http_json(method: str, url: str, payload: Mapping[str, Any] | None,
               *, timeout: float) -> Mapping[str, Any]:
    data = None if payload is None else canonical_bytes(payload)
    request = urllib.request.Request(
        url, method=method, data=data,
        headers={"Accept": "application/json", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read()
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise BaselineRunRefused(
            f"bt-engine {method} request failed ({type(exc).__name__})") from exc
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BaselineRunRefused("bt-engine returned non-JSON") from exc
    if not isinstance(value, Mapping):
        raise BaselineRunRefused("bt-engine returned a non-object")
    return value


def invoke(*, expected_path: Path, manifest_path: Path, output_path: Path,
           base_url: str, argv: Sequence[str], timeout_seconds: float,
           poll_seconds: float = 2.0,
           request_json: Callable[..., Mapping[str, Any]] = _http_json,
           now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
           monotonic: Callable[[], float] = time.monotonic,
           sleeper: Callable[[float], None] = time.sleep) -> dict[str, Any]:
    """Actually invoke bt-engine and construct one validated authority record."""
    if (not math.isfinite(timeout_seconds) or timeout_seconds <= 0
            or not math.isfinite(poll_seconds) or poll_seconds <= 0):
        raise BaselineRunRefused("invocation timeout/poll interval must be finite and positive")
    raw_expected, expected = _json_file(expected_path, label="expected hashes")
    raw_manifest, manifest = _json_file(manifest_path, label="certification manifest")
    expected_slot = _canonical_bound(raw_expected, expected, label="expected hashes")
    manifest_slot = _canonical_bound(raw_manifest, manifest, label="certification manifest")
    _expected(expected)
    _manifest(manifest)
    request = canonical_request(expected)
    root = _validated_base_url(base_url)
    _validate_argv(
        list(argv), base_url=root, expected_path=expected_path,
        manifest_path=manifest_path, output_path=output_path,
        timeout_seconds=timeout_seconds, executable=sys.executable)
    started_at = _utc(now)
    invocation_id = str(uuid.uuid4())
    entries: list[dict[str, Any]] = [{
        "event": "invocation_started", "at": started_at,
        "request_sha256": canonical_sha256(request),
    }]
    accepted = request_json(
        "POST", root + "/wealth-core/jobs/run", request,
        timeout=min(timeout_seconds, 30.0))
    run_id = _uuid(accepted.get("run_id"), label="accepted run id")
    if (accepted.get("mode") != "baseline_replay"
            or accepted.get("status") != "running"):
        raise BaselineRunRefused("bt-engine did not accept a running baseline replay")
    accepted_at = _utc(now)
    entries.append({"event": "run_accepted", "at": accepted_at,
                    "run_id": run_id})
    deadline = monotonic() + timeout_seconds
    row_path = f"/wealth-core/runs/{run_id}"
    while True:
        row = request_json(
            "GET", root + row_path, None,
            timeout=min(max(0.1, deadline - monotonic()), 30.0))
        status = row.get("status")
        entries.append({"event": "row_observed", "at": _utc(now),
                        "run_id": run_id, "status": status})
        if status in {"success", "failed"}:
            break
        if status != "running":
            raise BaselineRunRefused("bt-engine returned an unknown run status")
        if monotonic() >= deadline:
            raise BaselineRunRefused("baseline invocation timed out; no authority record emitted")
        sleeper(min(poll_seconds, max(0.0, deadline - monotonic())))
    if row.get("status") != "success":
        raise BaselineRunRefused(
            "terminal row is not a successful baseline replay; no authority "
            "record emitted")
    recorded_at = _utc(now)
    record: dict[str, Any] = {
        "schema": SCHEMA, "status": "success", "run_id": run_id,
        "invocation": {
            "invocation_id": invocation_id, "argv": list(argv),
            "argv_sha256": canonical_sha256(list(argv)),
            "started_at": started_at, "accepted_at": accepted_at,
            "recorded_at": recorded_at,
            "endpoint": {"base_url": root,
                         "submit_path": "/wealth-core/jobs/run",
                         "row_path": row_path},
            "request": request, "request_sha256": canonical_sha256(request),
            "producer": {"path": PRODUCER,
                         "sha256": sha256(_producer_path().read_bytes()),
                         "python": platform.python_version()},
            "log": {"entries": entries, "sha256": canonical_sha256(entries)},
        },
        "expected_hashes": expected_slot,
        "certification_manifest": manifest_slot,
        "terminal_run": {"sha256": canonical_sha256(row), "row": row},
        "outcome": {
            "status": "success", "divergence_identical": True,
            "parity_hashes_sha256": canonical_sha256(expected["hashes"]),
            "bt_data_version": str(expected["corpus"]["version"]),
            "bt_data_status": "READY", "bt_data_source_mode": "sharadar",
            "split_source": "actions",
        },
    }
    validate_record(record)
    return record


def _fsync_directory(path: Path) -> None:
    if os.name == "nt":
        return
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _unlink_retry(path: Path, *, attempts: int = 4) -> None:
    failure: OSError | None = None
    for _attempt in range(attempts):
        try:
            path.unlink()
            return
        except FileNotFoundError:
            return
        except OSError as exc:
            failure = exc
    assert failure is not None
    raise failure


def _rollback_published(path: Path, original: BaseException) -> None:
    """Remove the authoritative name, quarantining on stubborn unlink."""
    try:
        _unlink_retry(path)
    except OSError as cleanup:
        quarantine = path.with_name(
            f".{path.name}.rollback.{os.getpid()}.{secrets.token_hex(4)}")
        try:
            os.replace(path, quarantine)
            try:
                _unlink_retry(quarantine)
            except OSError as residual:
                if hasattr(original, "add_note"):
                    original.add_note(
                        f"rollback quarantine remains at {quarantine}: "
                        f"{residual!r}")
        except OSError as rename_error:
            if hasattr(original, "add_note"):
                original.add_note(
                    f"could not remove published path: {cleanup!r}; "
                    f"rename fallback failed: {rename_error!r}")
    try:
        _fsync_directory(path.parent)
    except BaseException as cleanup_fsync:
        if hasattr(original, "add_note"):
            original.add_note(
                f"rollback parent fsync also failed: {cleanup_fsync!r}")


def _same_file(left: Path, right: Path) -> bool:
    """Whether both names identify the same inode, without following guesses."""
    try:
        return left.samefile(right)
    except (FileNotFoundError, OSError):
        return False


def write_record_atomic(path: Path, record: Mapping[str, Any]) -> None:
    """Publish canonical bytes durably and atomically without overwriting."""
    validate_record(record)
    target = Path(path)
    parent = target.parent
    if not parent.is_dir():
        raise BaselineRunRefused(f"output directory does not exist: {parent}")
    if target.exists():
        raise BaselineRunRefused(f"output exists; refusing overwrite: {target}")
    payload = canonical_bytes(record)
    temporary = parent / f".{target.name}.{secrets.token_hex(12)}.tmp"
    linked = False
    try:
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, target)
            linked = True
        except FileExistsError as exc:
            raise BaselineRunRefused(
                f"output exists; refusing overwrite: {target}") from exc
        _fsync_directory(parent)
        _unlink_retry(temporary)
        _fsync_directory(parent)
    except BaseException as exc:
        # A wrapper, signal or filesystem can report failure after link(2)
        # created the directory entry but before `linked = True` executed. The
        # inode check proves whether the visible name is our staging object;
        # never remove an unrelated target that won an ordinary no-clobber race.
        if linked or _same_file(temporary, target):
            _rollback_published(target, exc)
        try:
            _unlink_retry(temporary)
        except OSError as cleanup:
            if hasattr(exc, "add_note"):
                exc.add_note(f"staging cleanup also failed: {cleanup!r}")
        if isinstance(exc, BaselineRunRefused):
            raise
        raise BaselineRunRefused(
            f"could not atomically publish baseline record {target}") from exc
    finally:
        try:
            _unlink_retry(temporary)
        except OSError:
            # A dot-prefixed staging name is never authoritative.  The raised
            # error (if any) already records cleanup detail; do not replace it.
            pass


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-hashes", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--bt-engine-url", required=True)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--timeout-seconds", type=float, default=14400.0)
    args = parser.parse_args(list(argv if argv is not None else sys.argv[1:]))
    exact_argv = [sys.executable, "-m", "tools.wealth_core_baseline_run",
                  *(list(argv) if argv is not None else sys.argv[1:])]
    try:
        if not math.isfinite(args.timeout_seconds) or args.timeout_seconds <= 0:
            raise BaselineRunRefused("timeout must be positive")
        record = invoke(
            expected_path=args.expected_hashes, manifest_path=args.manifest,
            output_path=args.output,
            base_url=args.bt_engine_url, argv=exact_argv,
            timeout_seconds=args.timeout_seconds)
        write_record_atomic(args.output, record)
        print(f"baseline authority run {record['run_id']} -> {args.output}")
        return 0
    except BaselineRunRefused as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2


__all__ = [
    "BaselineRunRefused", "SCHEMA", "canonical_bytes", "canonical_request",
    "invoke", "main", "validate_record", "write_record_atomic",
]


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
