"""Mutation evidence must distinguish invariant failures from broken execution."""
from copy import deepcopy
import json
import os
from pathlib import Path
import py_compile
from types import SimpleNamespace
import xml.etree.ElementTree as ET

import pytest

from tools import sentinel_mutation_certify as mutation


CASE = "tests/test_guard.py::test_guard"


def probe(*, exception="builtins.AssertionError", message="guard failed"):
    return {"collected": [CASE], "reports": [
        {"nodeid": CASE, "phase": phase,
         "exception": exception if phase == "call" else None,
         "message": message if phase == "call" else ""}
        for phase in ("setup", "call", "teardown")]}


def junit(tmp_path, *, failures=1, errors=0, skipped=0, passed=0):
    root = ET.Element("testsuite")
    for tag, count in (("failure", failures), ("error", errors),
                       ("skipped", skipped), (None, passed)):
        for index in range(count):
            case = ET.SubElement(root, "testcase", name=f"case-{tag}-{index}")
            if tag:
                ET.SubElement(case, tag, message="synthetic outcome")
    path = tmp_path / "junit.xml"
    ET.ElementTree(root).write(path)
    return path


def verdict(tmp_path, evidence, **kwargs):
    return mutation._mutation_verdict(
        1, junit(tmp_path), probe=evidence, expected_cases=(CASE,), **kwargs)[0]


def test_complete_reviewed_assertion_kills_mutant(tmp_path):
    assert verdict(tmp_path, probe()) is True


@pytest.mark.parametrize("exception", [
    "builtins.RuntimeError", "psycopg.OperationalError", "builtins.ImportError",
    "_pytest.outcomes.Skipped", "_pytest.outcomes.XFailed",
])
def test_operational_and_nonpass_exceptions_are_not_invariant_failures(tmp_path, exception):
    assert verdict(tmp_path, probe(exception=exception)) is False


def test_raises_falsifier_remains_a_reviewed_failure(tmp_path):
    assert verdict(tmp_path, probe(
        exception="builtins.Failed", message="DID NOT RAISE <class 'ValueError'>"))


def test_operational_pytest_fail_is_not_a_missing_exception_assertion(tmp_path):
    assert not verdict(tmp_path, probe(exception="builtins.Failed", message="database disconnected"))


def test_domain_exception_allowance_is_exact_and_message_bound(tmp_path):
    signals = (mutation.FailureSignal("sentinel.guard.DomainRefused", "^known invariant$"),)
    assert verdict(tmp_path, probe(exception=signals[0].exception, message="known invariant"),
                   failure_signals=signals)
    for exception, message in (("builtins.RuntimeError", "known invariant"),
                               (signals[0].exception, "database disconnected")):
        assert not verdict(tmp_path, probe(exception=exception, message=message),
                           failure_signals=signals)


@pytest.mark.parametrize("damage", [
    "missing-case", "extra-case", "duplicate-case", "missing-phase", "duplicate-phase",
    "foreign-report", "setup-error", "teardown-error", "probe-error", "no-probe",
])
def test_incomplete_or_unrelated_execution_cannot_kill_mutant(tmp_path, damage):
    evidence = probe()
    if damage == "missing-case":
        evidence["collected"] = []
    elif damage == "extra-case":
        evidence["collected"].append(CASE + "[extra]")
    elif damage == "duplicate-case":
        evidence["collected"].append(CASE)
    elif damage == "missing-phase":
        evidence["reports"].pop()
    elif damage == "duplicate-phase":
        evidence["reports"][-1] = deepcopy(evidence["reports"][0])
    elif damage == "foreign-report":
        evidence["reports"][1]["nodeid"] = CASE + "[foreign]"
    elif damage in {"setup-error", "teardown-error"}:
        evidence["reports"][0 if damage == "setup-error" else -1]["exception"] = "builtins.RuntimeError"
    elif damage == "probe-error":
        evidence["probe_error"] = "wrong source import"
    else:
        evidence = None
    assert verdict(tmp_path, evidence) is False


@pytest.mark.parametrize("outcomes", [
    {"failures": 1, "skipped": 1}, {"failures": 1, "errors": 1},
    {"failures": 1, "passed": 1}, {"failures": 0, "passed": 1},
])
def test_junit_must_agree_with_exact_probe_execution(tmp_path, outcomes):
    killed, _ = mutation._mutation_verdict(
        1, junit(tmp_path, **outcomes), probe=probe(), expected_cases=(CASE,))
    assert not killed


def test_one_assertion_cannot_hide_an_operational_failure(tmp_path):
    evidence = probe()
    other = CASE + "[other]"
    evidence["collected"].append(other)
    for report in probe(exception="builtins.RuntimeError")["reports"]:
        evidence["reports"].append({**report, "nodeid": other})
    killed, _ = mutation._mutation_verdict(
        1, junit(tmp_path, failures=2), probe=evidence, expected_cases=(CASE, other))
    assert not killed


@pytest.fixture
def source_tree(tmp_path, monkeypatch):
    monkeypatch.setattr(mutation.tempfile, "tempdir", str(tmp_path))
    root = tmp_path / "source"
    (root / "sentinel").mkdir(parents=True)
    (root / "tests").mkdir()
    (root / "sentinel" / "__init__.py").write_text("")
    (root / "sentinel" / "guard.py").write_text("ENABLED = True\n")
    (root / "tests" / "test_guard.py").write_text(
        "from sentinel.guard import ENABLED\n"
        "def test_guard():\n    assert ENABLED\n")
    (root / "pytest.ini").write_text("[pytest]\n")
    for name in ("RUNTIME", "TEST_SOURCE", "REPO"):
        monkeypatch.setattr(mutation, name, root)
    return root


def example(replacement="ENABLED = False\n", **kwargs):
    return mutation.Mutant("test-guard", "sentinel/guard.py", "ENABLED = True\n",
                           replacement, CASE, **kwargs)


def test_real_subprocess_requires_green_baseline_and_reviewed_mutant(source_tree):
    record = mutation._run(example())
    assert record["baseline_passed"] is True
    assert record["expected_cases"] == [CASE]
    assert record["mutant_killed"] is True
    assert record["baseline"]["pytest_exit_code"] == 0
    assert record["probe"]["reports"][1]["exception"] == "builtins.AssertionError"


def test_stale_bytecode_cannot_hide_an_equal_length_mutant(source_tree, monkeypatch):
    source = source_tree / "sentinel" / "guard.py"
    source.write_text("ENABLED = 1\n")
    stamp = 1_700_000_000
    os.utime(source, (stamp, stamp))
    py_compile.compile(str(source), doraise=True)
    original = mutation._apply_once

    def same_timestamp(path, before, after):
        original(path, before, after)
        os.utime(path, (stamp, stamp))

    monkeypatch.setattr(mutation, "_apply_once", same_timestamp)
    record = mutation._run(mutation.Mutant(
        "equal-length", "sentinel/guard.py", "ENABLED = 1\n", "ENABLED = 0\n", CASE))
    assert record["baseline_passed"] is True and record["mutant_killed"] is True


def test_real_call_phase_operational_crash_does_not_kill_mutant(source_tree):
    (source_tree / "tests" / "test_guard.py").write_text(
        "from sentinel.guard import ENABLED\n"
        "def test_guard():\n"
        "    if not ENABLED: raise RuntimeError('database disconnected')\n"
        "    assert ENABLED\n")
    record = mutation._run(example())
    assert record["baseline_passed"] is True
    assert record["pytest_counts"]["failures"] == 1
    assert record["pytest_counts"]["errors"] == 0
    assert record["probe"]["reports"][1]["exception"] == "builtins.RuntimeError"
    assert record["mutant_killed"] is False


def test_real_domain_exception_falsifier_preserves_its_reviewed_signal(source_tree):
    source = source_tree / "sentinel" / "guard.py"
    source.write_text("class DomainRefused(RuntimeError): pass\nENABLED = True\n")
    (source_tree / "tests" / "test_guard.py").write_text(
        "from sentinel.guard import ENABLED, DomainRefused\n"
        "def test_guard():\n"
        "    if not ENABLED: raise DomainRefused('known invariant')\n"
        "    assert ENABLED\n")
    record = mutation._run(example(failure_signals=(
        mutation.FailureSignal("sentinel.guard.DomainRefused", "^known invariant$"),)))
    assert record["baseline_passed"] is True and record["mutant_killed"] is True


def test_failed_unmodified_overlay_never_reaches_mutation(source_tree, monkeypatch):
    (source_tree / "tests" / "test_guard.py").write_text(
        "def test_guard(): raise RuntimeError('baseline broken')\n")
    monkeypatch.setattr(mutation, "_apply_once", lambda *_: pytest.fail("mutation ran"))
    record = mutation._run(example())
    assert record["baseline_passed"] is False and record["mutant_killed"] is False
    assert record["harness_error"] == "unmodified overlay baseline did not pass"


@pytest.mark.parametrize("damage", ["missing", "extra"])
def test_real_mutant_cannot_change_collected_parameter_cases(source_tree, damage):
    values = "[1, 2] if ENABLED else [1]" if damage == "missing" else "[1] if ENABLED else [1, 2]"
    (source_tree / "tests" / "test_guard.py").write_text(
        "import pytest\nfrom sentinel.guard import ENABLED\n"
        f"@pytest.mark.parametrize('value', {values})\n"
        "def test_guard(value): assert ENABLED\n")
    record = mutation._run(example())
    assert record["baseline_passed"] is True
    assert record["probe"]["collected"] != record["expected_cases"]
    assert record["mutant_killed"] is False


@pytest.mark.parametrize("damage", ["path", "hash"])
def test_probe_refuses_wrong_loaded_source(tmp_path, monkeypatch, damage):
    source = tmp_path / "sentinel" / "guard.py"
    source.parent.mkdir()
    source.write_text("ENABLED = True\n")
    loaded = source
    if damage == "path":
        loaded = tmp_path / "wrong.py"
        loaded.write_text(source.read_text())
    monkeypatch.setattr(mutation.importlib, "import_module",
                        lambda _: SimpleNamespace(__file__=str(loaded)))
    spec = tmp_path / "input.json"
    output = tmp_path / "probe.json"
    spec.write_text(json.dumps({
        "overlay": str(tmp_path), "source": "sentinel/guard.py",
        "sha256": "0" * 64 if damage == "hash" else mutation._hash(source),
        "test": CASE, "output": str(output), "junit": str(tmp_path / "junit.xml"),
    }))
    assert mutation._probe(spec) == 2
    assert "authenticated overlay source" in json.loads(output.read_text())["probe_error"]
