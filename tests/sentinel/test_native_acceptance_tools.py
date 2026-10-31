from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import hashlib
import inspect
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
import xml.etree.ElementTree as ET

import httpx
import pytest

from sentinel.execution.native_readonly import ReadOnlyLimits
from tests.support.native_activity_recording import ACCOUNT_UUID, account_payload
from tools import sentinel_live_diagnostics as diagnostic
from tools import sentinel_native_acceptance as acceptance


SECRET = "private-value-must-never-be-printed"
NOW = datetime(2026, 10, 17, 0, 0, tzinfo=timezone.utc)


def expected_results(recorded=False):
    values = {"test_mandatory_native_history_scenario[" + name + "]" for name in acceptance.MANDATORY_SCENARIOS}
    values.update(acceptance.FUNDING_RESULTS)
    values.add("test_offline_history_never_promotes_native_guarantees")
    if recorded:
        values.add("test_recorded_native_history_input")
    return values


def fake_repository(tmp_path):
    root = tmp_path / "repo"
    for name in acceptance.FIXED_SOURCE_FILES:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        # Runtime Python stays under /app; /work/sentinel has only lock metadata
        # and the standalone host diagnostic companion, not the runtime package.
        source_root = (Path(os.environ.get("SENTINEL_REPO_ROOT") or acceptance.ROOT)
                       if name.startswith("sentinel/") else acceptance.ROOT)
        path.write_bytes(acceptance._source_path(source_root, name).read_bytes())
    return root


def split_repository(tmp_path, monkeypatch):
    root = fake_repository(tmp_path)
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    (root / "sentinel").rename(runtime / "sentinel")
    (runtime / "sentinel/__init__.py").write_text("")
    mirror = root / "repo/sentinel/execution"
    mirror.mkdir(parents=True)
    (mirror / "native_readonly.py").write_text("UNUSED_SOURCE_MIRROR")
    monkeypatch.setattr(acceptance, "ROOT", root)
    monkeypatch.setitem(sys.modules, "sentinel", SimpleNamespace(__file__=str(runtime / "sentinel/__init__.py")))
    return root, runtime


def test_split_runtime_source_and_child_imports_are_bound(tmp_path, monkeypatch):
    root, runtime = split_repository(tmp_path, monkeypatch)
    assert not (root / "sentinel").exists()
    source = acceptance._source_path(root, "sentinel/execution/native_readonly.py")
    assert source == runtime / "sentinel/execution/native_readonly.py"
    hashes = acceptance._source_hashes(root)
    assert hashes["sentinel/execution/native_readonly.py"] == hashlib.sha256(source.read_bytes()).hexdigest()
    def check(_command, kwargs):
        imports = kwargs["env"]["PYTHONPATH"].split(os.pathsep)
        assert imports[0] == str(runtime)
        assert str(runtime / "shared") in imports and str(root) in imports
        assert str(root / "tests") in imports and str(root / "tools") in imports
        assert str(root / "shared") in imports
    receipt = acceptance.qualify(root=root, output=tmp_path / "split.json", runner=fake_runner(callback=check))
    assert receipt["status"] == "PASS_OFFLINE_QUALIFICATION"
    monkeypatch.setattr(sys, "path", list(sys.path))
    diagnostic._configure_import_paths(root)
    assert sys.path[0] == str(runtime)


def test_custom_fixture_cannot_fall_back_to_imported_runtime(tmp_path):
    root = tmp_path / "incomplete-fixture"
    root.mkdir()
    with pytest.raises(ValueError, match="CUSTOM_SENTINEL_SOURCE_REQUIRED"):
        acceptance._sentinel_root(root)


def test_local_repository_source_has_precedence(tmp_path):
    root = fake_repository(tmp_path)
    assert acceptance._sentinel_root(root) == root / "sentinel"


def test_split_runtime_change_cannot_pass(tmp_path, monkeypatch):
    root, runtime = split_repository(tmp_path, monkeypatch)
    def change(_command, _kwargs):
        (runtime / "sentinel/execution/broker_cash.py").write_text("CHANGED_RUNTIME")
    receipt = acceptance.qualify(root=root, output=tmp_path / "changed.json", runner=fake_runner(callback=change))
    assert receipt["status"] == "FAIL_OFFLINE_QUALIFICATION" and receipt["reason"] == "SOURCE_CHANGED"


def test_split_runtime_import_guard_has_a_falsifier(tmp_path, monkeypatch):
    _replace_function(acceptance, "_child_pythonpath", "runtime = _sentinel_root(root).parent", "runtime = root", monkeypatch)
    with pytest.raises(AssertionError):
        test_split_runtime_source_and_child_imports_are_bound(tmp_path, monkeypatch)


def fake_runner(names=None, *, skipped=False, callback=None):
    def run(command, **kwargs):
        if callback is not None:
            callback(command, kwargs)
        path = Path(next(item.split("=", 1)[1] for item in command if item.startswith("--junitxml=")))
        root = ET.Element("testsuites")
        suite = ET.SubElement(root, "testsuite")
        for index, name in enumerate(sorted(expected_results() if names is None else names)):
            module = "tests.sentinel.test_live_funding" if name in acceptance.FUNDING_RESULTS else "tests.sentinel.test_native_activity_recording"
            case = ET.SubElement(suite, "testcase", name=name, classname=module)
            if skipped and index == 0:
                ET.SubElement(case, "skipped", message=SECRET)
        ET.ElementTree(root).write(path)
        return SimpleNamespace(returncode=0, stdout=SECRET, stderr=SECRET)
    return run


def test_complete_offline_inventory_has_no_native_authority(tmp_path, monkeypatch):
    root = fake_repository(tmp_path)
    monkeypatch.setenv("ALPACA_API_KEY", SECRET)
    monkeypatch.setenv("UNRELATED_ACCOUNT_SECRET", SECRET)
    observed = []
    def check(_command, kwargs):
        assert "ALPACA_API_KEY" not in kwargs["env"]
        assert "UNRELATED_ACCOUNT_SECRET" not in kwargs["env"]
        assert kwargs["timeout"] == 300
        observed.append(True)
    output = tmp_path / "receipt.json"
    receipt = acceptance.qualify(root=root, output=output, runner=fake_runner(callback=check))
    assert observed and receipt["status"] == "PASS_OFFLINE_QUALIFICATION"
    assert receipt["provenance"] == "SIMULATION_ONLY" and receipt["execution_authority"] == "NONE"
    assert set(receipt["native_guarantees"].values()) == {"NOT_PROVEN"}
    assert receipt["capabilities_promoted"] == []
    assert SECRET not in output.read_text()


@pytest.mark.parametrize("fault", ["missing", "extra", "skip", "source-change", "cash-source-change", "fill-source-change"])
def test_incomplete_or_changed_evidence_cannot_pass(tmp_path, fault):
    root = fake_repository(tmp_path)
    names = expected_results()
    if fault == "missing":
        names.pop()
    elif fault == "extra":
        names.add("unreviewed-test")
    def callback(_command, _kwargs):
        if fault == "source-change":
            (root / acceptance.FIXED_SOURCE_FILES[0]).write_text("changed")
        elif fault == "cash-source-change":
            (root / "sentinel/execution/broker_cash.py").write_text("changed")
        elif fault == "fill-source-change":
            (root / "sentinel/execution/fill_integrity.py").write_text("changed")
    receipt = acceptance.qualify(root=root, output=tmp_path / "receipt.json",
                                 runner=fake_runner(names, skipped=fault == "skip", callback=callback))
    assert receipt["status"] == "FAIL_OFFLINE_QUALIFICATION"


def test_identical_test_names_from_wrong_owner_cannot_pass(tmp_path):
    root = fake_repository(tmp_path)
    valid_runner = fake_runner()
    def wrong_owner(command, **kwargs):
        result = valid_runner(command, **kwargs)
        path = Path(next(item.split("=", 1)[1] for item in command if item.startswith("--junitxml=")))
        document = ET.parse(path)
        document.find(".//testcase").set("classname", "foreign.tests")
        document.write(path)
        return result
    receipt = acceptance.qualify(root=root, output=tmp_path / "receipt.json", runner=wrong_owner)
    assert receipt["status"] == "FAIL_OFFLINE_QUALIFICATION"


def test_recording_provenance_is_replay_without_capture_authenticity(tmp_path):
    root = fake_repository(tmp_path)
    recording = tmp_path / "private-recording.json"
    recording.write_text(json.dumps({"private_account_payload": SECRET}))
    payload = recording.read_bytes()
    def check(_command, kwargs):
        copied = Path(kwargs["env"]["SENTINEL_NATIVE_RECORDING"])
        assert copied != recording and copied.read_bytes() == payload
        assert kwargs["env"]["SENTINEL_NATIVE_RECORDING_SHA256"] == hashlib.sha256(payload).hexdigest()
    output = tmp_path / "receipt.json"
    receipt = acceptance.qualify(root=root, output=output, recording=recording,
                                 recording_sha256=hashlib.sha256(payload).hexdigest(),
                                 runner=fake_runner(expected_results(True), callback=check))
    assert receipt["status"] == "PASS_OFFLINE_QUALIFICATION"
    assert receipt["provenance"] == "RECORDED_REPLAY"
    assert receipt["recording_capture_authenticity"] == "NOT_PROVEN"
    assert SECRET not in output.read_text()


def test_tampered_recording_refuses_before_execution(tmp_path):
    root = fake_repository(tmp_path)
    recording = tmp_path / "private.json"
    recording.write_text(SECRET)
    def forbidden(*_args, **_kwargs):
        pytest.fail("TEST_EXECUTION_SHOULD_NOT_START")
    with pytest.raises(ValueError, match="RECORDING_HASH_MISMATCH"):
        acceptance.qualify(root=root, output=tmp_path / "receipt.json", recording=recording,
                           recording_sha256="0" * 64, runner=forbidden)


@pytest.mark.parametrize("failure", [RuntimeError(SECRET), subprocess.TimeoutExpired(SECRET, 1)])
def test_offline_errors_are_sanitized(tmp_path, failure):
    root = fake_repository(tmp_path)
    def failed(*_args, **_kwargs):
        raise failure
    output = tmp_path / "receipt.json"
    receipt = acceptance.qualify(root=root, output=output, runner=failed)
    assert receipt["status"] == "FAIL_OFFLINE_QUALIFICATION"
    assert SECRET not in output.read_text()


def test_receipt_is_no_clobber(tmp_path):
    root = fake_repository(tmp_path)
    output = tmp_path / "receipt.json"
    output.write_text("existing")
    with pytest.raises(ValueError, match="OUTPUT_ALREADY_EXISTS"):
        acceptance.qualify(root=root, output=output, runner=lambda *_args, **_kwargs: pytest.fail("UNEXPECTED_EXECUTION"))
    assert output.read_text() == "existing"


def diagnostic_inputs(**changes):
    return diagnostic.DiagnosticInputs(**dict(base_url="https://api.alpaca.markets", expected_account=ACCOUNT_UUID,
        deployment_id="isolated-native-diagnostic", takeover_epoch=1,
        api_key_env="EXPLICIT_KEY", secret_key_env="EXPLICIT_SECRET",
        after="2026-10-16T00:00:00+00:00", through=NOW, **changes))


def run_diagnostic(*, account=None, failed=False, env=None, limits=None):
    requests = []
    def respond(request):
        assert request.method == "GET"
        requests.append((request.method, request.url.path))
        if failed:
            raise RuntimeError(SECRET)
        if request.url.path == "/v2/account":
            return httpx.Response(200, json=account_payload() if account is None else account)
        if request.url.path == "/v2/account/activities":
            return httpx.Response(200, json=[])
        raise AssertionError("UNEXPECTED_DIAGNOSTIC_ROUTE")
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
            return await diagnostic.diagnose(diagnostic_inputs(), http_client=http,
                environ=env if env is not None else {"EXPLICIT_KEY": "fixture-key", "EXPLICIT_SECRET": SECRET},
                limits=limits, now=lambda: NOW)
    return asyncio.run(run()), requests


def test_zero_account_diagnostic_proves_only_read_shape_and_defers_funding():
    report, requests = run_diagnostic()
    assert report["status"] == "PASS_READ_ONLY_DIAGNOSTIC"
    assert report["funding_status"] == "DEFERRED" and report["order_authority"] == "NONE"
    assert set(report["native_guarantees"].values()) == {"NOT_PROVEN"}
    assert report["capabilities_promoted"] == [] and report["broker_mutation_attempts"] == 0
    assert report["account_identity_bracketed"] and report["observed_event_count"] == 0
    assert requests == [("GET", "/v2/account"), ("GET", "/v2/account"),
                        ("GET", "/v2/account/activities"), ("GET", "/v2/account")]
    output = json.dumps(report)
    assert SECRET not in output and ACCOUNT_UUID not in output and "buying_power" not in output


def test_diagnostic_never_falls_back_to_installed_credentials():
    report, requests = run_diagnostic(env={"ALPACA_API_KEY": SECRET, "ALPACA_SECRET_KEY": SECRET})
    assert report["status"] == "NOT_PROVEN" and not requests
    assert report["reason"] == "NATIVE_READ_CREDENTIALS_REQUIRED"


@pytest.mark.parametrize("kind", ["transport", "wrong-account", "budget", "malformed-money"])
def test_diagnostic_refusal_is_bounded_and_sanitized(kind):
    account = account_payload("00000000-0000-4000-8000-000000000099") if kind == "wrong-account" else None
    if kind == "malformed-money":
        account = account_payload() | {"cash": SECRET}
    report, requests = run_diagnostic(account=account, failed=kind == "transport",
                                     limits=ReadOnlyLimits(max_requests=1) if kind == "budget" else None)
    assert report["status"] == "NOT_PROVEN"
    assert SECRET not in json.dumps(report) and ACCOUNT_UUID not in json.dumps(report)
    assert all(method == "GET" for method, _path in requests)


def test_diagnostic_cli_missing_explicit_inputs_makes_no_calls(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(diagnostic, "diagnose", lambda *_args, **_kwargs: pytest.fail("UNEXPECTED_ACCOUNT_ACCESS"))
    code = diagnostic.main(["--base-url", "https://api.alpaca.markets", "--expected-account", SECRET,
        "--deployment-id", "isolated", "--takeover-epoch", "1", "--api-key-env", "EXPLICIT_KEY",
        "--secret-key-env", "EXPLICIT_SECRET", "--after", "2026-10-16T00:00:00Z",
        "--through", "2026-10-17T00:00:00Z", "--output", str(tmp_path / "report.json")])
    assert code == 2 and SECRET not in capsys.readouterr().out


def _replace_function(module, name, old, new, monkeypatch):
    function = getattr(module, name)
    source = inspect.getsource(function)
    assert source.count(old) == 1
    namespace = {}
    exec(compile(source.replace(old, new), "native-tool-falsifier", "exec"), function.__globals__, namespace)
    monkeypatch.setattr(module, name, namespace[name])


@pytest.mark.parametrize("fault", ["inventory", "credentials", "guarantee-promotion"])
def test_offline_tool_guards_have_falsifiers(tmp_path, monkeypatch, fault):
    if fault == "inventory":
        _replace_function(acceptance, "qualify", "names == expected", "True", monkeypatch)
        with pytest.raises(AssertionError):
            test_incomplete_or_changed_evidence_cannot_pass(tmp_path, "missing")
    elif fault == "credentials":
        _replace_function(acceptance, "qualify", "env.update(PYTHONDONTWRITEBYTECODE=",
                          "env.update(ALPACA_API_KEY=os.environ.get('ALPACA_API_KEY', ''))\n        env.update(PYTHONDONTWRITEBYTECODE=", monkeypatch)
        with pytest.raises(AssertionError):
            test_complete_offline_inventory_has_no_native_authority(tmp_path, monkeypatch)
    else:
        _replace_function(acceptance, "qualify", '"native_guarantees": {name: "NOT_PROVEN"',
                          '"native_guarantees": {name: "PASS"', monkeypatch)
        with pytest.raises(AssertionError):
            test_complete_offline_inventory_has_no_native_authority(tmp_path, monkeypatch)


def test_recording_digest_guard_has_a_falsifier(tmp_path, monkeypatch):
    _replace_function(acceptance, "qualify", "if _digest(recording_payload) != recording_sha256:",
                      "if False:", monkeypatch)
    root = fake_repository(tmp_path)
    recording = tmp_path / "private.json"
    recording.write_text(SECRET)
    def assert_refusal():
        refused = False
        try:
            acceptance.qualify(root=root, output=tmp_path / "receipt.json", recording=recording,
                               recording_sha256="0" * 64, runner=fake_runner(expected_results(True)))
        except ValueError as exc:
            refused = str(exc) == "RECORDING_HASH_MISMATCH"
        assert refused
    with pytest.raises(AssertionError):
        assert_refusal()


def test_diagnostic_error_redaction_has_a_falsifier(monkeypatch):
    _replace_function(diagnostic, "diagnose",
                      'except Exception:\n        report["reason"] = "READ_ONLY_DIAGNOSTIC_REFUSED"',
                      'except Exception as exc:\n        report["reason"] = str(exc)', monkeypatch)
    with pytest.raises(AssertionError):
        test_diagnostic_refusal_is_bounded_and_sanitized("malformed-money")
