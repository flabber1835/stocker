from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from typing import Callable, Mapping
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]
SCENARIO_TEST = "tests/sentinel/test_native_activity_recording.py::test_mandatory_native_history_scenario"
MANDATORY_SCENARIOS = (
    "valid-native-fill", "dividend-fee-transfer", "tied-created-at",
    "duplicate-replay", "same-id-changed", "unknown-event",
    "correction-quarantine", "security-transfer-quarantine",
    "truncated-pagination", "cursor-cycle", "wrong-account",
    "malformed-decimal", "empty-history", "late-business-time",
    "exact-order-enrichment", "mismatched-exact-order",
)
FIXED_TESTS = (
    SCENARIO_TEST,
    "tests/sentinel/test_native_activity_recording.py::test_offline_history_never_promotes_native_guarantees",
    "tests/sentinel/test_live_funding.py::test_native_fields_cannot_self_qualify_settlement",
    "tests/sentinel/test_live_funding.py::test_funding_proof_guard_has_a_falsifier",
)
FUNDING_RESULTS = tuple("test_native_fields_cannot_self_qualify_settlement[" + name + "]"
                        for name in ("None", "cash", "buying_power", "native/settled-v1", "simulation/settled-v1")) + (
    "test_funding_proof_guard_has_a_falsifier",
)
FIXED_SOURCE_FILES = (
    "sentinel/trading_environment.py",
    "sentinel/execution/native_readonly.py",
    "sentinel/execution/native_activity.py",
    "sentinel/execution/alpaca_history.py",
    "sentinel/execution/live_funding.py",
    "sentinel/execution/broker_cash.py",
    "sentinel/execution/fill_integrity.py",
    "sentinel/execution/contract.py",
    "sentinel/execution/numeric.py",
    "sentinel/execution/states.py",
    "sentinel/execution/alpaca.py",
    "tests/support/native_activity_recording.py",
    "tests/sentinel/test_native_activity_recording.py",
    "tests/sentinel/test_live_funding.py",
    "tools/sentinel_native_acceptance.py",
    "tools/sentinel_live_diagnostics.py",
)
UNPROVEN_GUARANTEES = (
    "native_history_completeness", "late_publication_finality", "settlement",
    "close_cash_finality", "restore_grade_order_recovery", "live_authority",
)
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")


def _digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sentinel_root(root: Path) -> Path:
    resolved = root.resolve()
    local = resolved / "sentinel"
    if local.exists():
        source = local.resolve(strict=True)
        if local.is_symlink() or not source.is_relative_to(resolved) or not source.is_dir():
            raise ValueError("SOURCE_PATH_REFUSED")
        return source
    if resolved != ROOT.resolve():
        raise ValueError("CUSTOM_SENTINEL_SOURCE_REQUIRED")
    package = importlib.import_module("sentinel")
    source_file = Path(package.__file__).resolve(strict=True)
    if source_file.name != "__init__.py" or not source_file.is_file():
        raise ValueError("IMPORTED_SENTINEL_SOURCE_REQUIRED")
    return source_file.parent


def _source_path(root: Path, name: str) -> Path:
    logical = Path(name)
    if logical.is_absolute() or ".." in logical.parts or "\\" in name:
        raise ValueError("SOURCE_PATH_REFUSED")
    resolved = root.resolve()
    if logical.parts and logical.parts[0] == "sentinel":
        owner = _sentinel_root(root)
        path = owner.joinpath(*logical.parts[1:]).resolve(strict=True)
    else:
        owner = resolved
        path = (resolved / logical).resolve(strict=True)
    if not path.is_relative_to(owner) or not path.is_file():
        raise ValueError("SOURCE_PATH_REFUSED")
    return path


def _child_pythonpath(root: Path) -> str:
    runtime = _sentinel_root(root).parent
    paths = (runtime, runtime / "shared", root, root / "tests", root / "tools", root / "shared", root / "scripts")
    return os.pathsep.join(dict.fromkeys(str(path.resolve()) for path in paths))


def _source_hashes(root: Path) -> dict[str, str]:
    sentinel = _sentinel_root(root)
    result = {}
    for name in FIXED_SOURCE_FILES:
        path = _source_path(root, name)
        result[name] = _digest(path.read_bytes())
    tree = {}
    for path in sorted(sentinel.rglob("*")):
        if path.is_symlink():
            raise ValueError("SOURCE_PATH_REFUSED")
        if path.suffix == ".py" and path.is_file():
            relative = "sentinel/" + path.relative_to(sentinel).as_posix()
            tree[relative] = _digest(path.read_bytes())
    result["sentinel_python_tree_sha256"] = _digest(json.dumps(tree, sort_keys=True, separators=(",", ":")).encode())
    return result


def _write_receipt(path: Path, receipt: Mapping) -> None:
    payload = (json.dumps(receipt, sort_keys=True, indent=2) + "\n").encode()
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(payload)


def _test_inventory(xml_path: Path) -> tuple[set[str], int, int, int]:
    document = ET.parse(xml_path)
    cases = document.findall(".//testcase")
    names = [case.attrib.get("name", "") for case in cases]
    if len(set(names)) != len(names):
        raise ValueError("DUPLICATE_TEST_RESULT")
    for case in cases:
        name = case.attrib.get("name", "")
        funding = name in FUNDING_RESULTS
        module = "tests.sentinel.test_live_funding" if funding else "tests.sentinel.test_native_activity_recording"
        if case.attrib.get("classname") != module:
            raise ValueError("TEST_OWNER_MISMATCH")
        if "file" in case.attrib and case.attrib["file"] != module.replace(".", "/") + ".py":
            raise ValueError("TEST_OWNER_MISMATCH")
    failures = sum(case.find("failure") is not None for case in cases)
    errors = sum(case.find("error") is not None for case in cases)
    skipped = sum(case.find("skipped") is not None for case in cases)
    return set(names), failures, errors, skipped


def qualify(*, output: Path, root: Path = ROOT,
            recording: Path | None = None, recording_sha256: str | None = None,
            timeout_seconds: float = 300,
            runner: Callable = subprocess.run) -> dict:
    if not 0 < timeout_seconds <= 3600:
        raise ValueError("INVALID_TIMEOUT")
    if output.exists():
        raise ValueError("OUTPUT_ALREADY_EXISTS")
    if (recording is None) != (recording_sha256 is None):
        raise ValueError("RECORDING_HASH_REQUIRED")
    before = _source_hashes(root)
    expected = {"test_mandatory_native_history_scenario[" + name + "]"
                for name in MANDATORY_SCENARIOS}
    expected.add("test_offline_history_never_promotes_native_guarantees")
    expected.update(FUNDING_RESULTS)
    selectors = list(FIXED_TESTS)
    recording_payload = None
    if recording is not None:
        if not _DIGEST.fullmatch(recording_sha256 or ""):
            raise ValueError("INVALID_RECORDING_HASH")
        with recording.open("rb") as handle:
            recording_payload = handle.read(16 * 1024 * 1024 + 1)
        if len(recording_payload) > 16 * 1024 * 1024:
            raise ValueError("RECORDING_RESOURCE_LIMIT")
        if _digest(recording_payload) != recording_sha256:
            raise ValueError("RECORDING_HASH_MISMATCH")
        expected.add("test_recorded_native_history_input")
        selectors.append("tests/sentinel/test_native_activity_recording.py::test_recorded_native_history_input")
    receipt = {
        "schema": "sentinel.native-offline-acceptance/1",
        "status": "FAIL_OFFLINE_QUALIFICATION",
        "provenance": "RECORDED_REPLAY" if recording is not None else "SIMULATION_ONLY",
        "recording_sha256": recording_sha256,
        "recording_capture_authenticity": "NOT_PROVEN",
        "execution_authority": "NONE",
        "native_guarantees": {name: "NOT_PROVEN" for name in UNPROVEN_GUARANTEES},
        "capabilities_promoted": [],
        "source_sha256": before,
        "mandatory_scenarios": list(MANDATORY_SCENARIOS),
        "expected_test_results": sorted(expected),
        "test_results": [],
        "reason": "TEST_EXECUTION_NOT_PROVEN",
    }
    with tempfile.TemporaryDirectory(prefix="sentinel-native-offline-") as directory:
        temporary = Path(directory)
        junit = temporary / "results.xml"
        env = {name: os.environ[name] for name in (
            "PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "HOME",
        ) if name in os.environ}
        env.update(PYTHONDONTWRITEBYTECODE="1", PYTEST_DISABLE_PLUGIN_AUTOLOAD="1",
                   PYTHONPATH=_child_pythonpath(root))
        if recording_payload is not None:
            private_input = temporary / "recording.json"
            descriptor = os.open(private_input, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(recording_payload)
            env["SENTINEL_NATIVE_RECORDING"] = str(private_input)
            env["SENTINEL_NATIVE_RECORDING_SHA256"] = recording_sha256
        command = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
                   "--tb=short", "-o", "junit_family=legacy", "--junitxml=" + str(junit), *selectors]
        try:
            result = runner(command, cwd=root, env=env, capture_output=True,
                            text=True, timeout=timeout_seconds, check=False)
            receipt["pytest_exit_code"] = result.returncode
            receipt["test_output_sha256"] = _digest((result.stdout + result.stderr).encode())
            names, failures, errors, skipped = _test_inventory(junit)
            receipt.update(test_results=sorted(names), failures=failures, errors=errors, skipped=skipped)
            stable = _source_hashes(root) == before
            receipt["source_stable"] = stable
            passed = result.returncode == 0 and names == expected and not (failures or errors or skipped) and stable
            if passed:
                receipt.update(status="PASS_OFFLINE_QUALIFICATION", reason="FIXED_INVENTORY_PASSED")
            elif not stable:
                receipt["reason"] = "SOURCE_CHANGED"
            elif names != expected:
                receipt["reason"] = "INCOMPLETE_OR_UNEXPECTED_TEST_INVENTORY"
            else:
                receipt["reason"] = "TEST_FAILURE_OR_SKIP"
        except subprocess.TimeoutExpired:
            receipt["reason"] = "OFFLINE_TEST_DEADLINE"
        except Exception:
            receipt["reason"] = "OFFLINE_EVIDENCE_INVALID"
    _write_receipt(output, receipt)
    return receipt


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--recording", type=Path)
    parser.add_argument("--recording-sha256")
    parser.add_argument("--timeout-seconds", type=float, default=300)
    args = parser.parse_args(argv)
    try:
        receipt = qualify(output=args.output, recording=args.recording,
                          recording_sha256=args.recording_sha256,
                          timeout_seconds=args.timeout_seconds)
    except (OSError, ValueError):
        print(json.dumps({"status": "FAIL_OFFLINE_QUALIFICATION", "reason": "INPUT_OR_OUTPUT_REFUSED"}))
        return 2
    print(json.dumps({key: receipt[key] for key in ("status", "provenance", "reason")}))
    return 0 if receipt["status"] == "PASS_OFFLINE_QUALIFICATION" else 1


if __name__ == "__main__":
    raise SystemExit(main())
