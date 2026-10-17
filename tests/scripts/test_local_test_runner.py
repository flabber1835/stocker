"""Falsify omitted tests, silent skips and stale local execution evidence."""
from types import SimpleNamespace
import xml.etree.ElementTree as ET

import pytest

from tools import local_test_runner as runner


def sample(tmp_path, body="def test_one(): assert True\n"):
    root = tmp_path / "repo"
    tests = root / "tests/sample"
    tests.mkdir(parents=True)
    (root / "pytest.ini").write_text("[pytest]\naddopts = --import-mode=importlib\n")
    (tests / "test_cases.py").write_text(body)
    authority = {"owners": {"sample.owner": {
        "paths": ["tests/sample"], "execution": {"kind": "pytest-junit"}}}}
    return root, authority


def run_sample(tmp_path, body, *, pytest_args=None):
    root, authority = sample(tmp_path, body)
    modules = runner.owner_inventory(authority, root)["sample.owner"]
    return runner.run_owner("sample.owner", modules, authority=authority, root=root,
                            evidence=tmp_path / "evidence", pytest_args=pytest_args or [])


def test_complete_owner_executes_in_a_fresh_interpreter_and_retains_evidence(tmp_path):
    result = run_sample(tmp_path, "def test_one(): assert True\ndef test_two(): assert True\n")
    assert result["executed_nodes"] == result["passing_nodes"] == 2
    assert (tmp_path / "evidence/sample.owner/junit.xml").is_file()


@pytest.mark.parametrize("body,args,reason", [
    ("def test_one(): assert True\ndef test_two(): assert True\n", ["-k", "one"], "complete authorized collection"),
    ("import pytest\ndef test_one(): assert True\ndef test_two(): pytest.skip('missing runtime')\n", [], "unauthorized_nonpasses"),
    ("import pytest\ndef test_one(): assert True\n@pytest.mark.xfail(strict=True)\ndef test_two(): assert False\n", [], "unexpected_xfails"),
    ("def test_one(): assert False\n", [], "pytest exited"),
])
def test_partial_or_nonpassing_execution_cannot_pass(tmp_path, body, args, reason):
    with pytest.raises((AssertionError, ValueError), match=reason):
        run_sample(tmp_path, body, pytest_args=args)


def test_new_unowned_module_is_not_silently_omitted(tmp_path):
    root, authority = sample(tmp_path)
    (root / "tests/test_unowned.py").write_text("def test_new(): pass\n")
    with pytest.raises(ValueError, match="no permanent execution owner"):
        runner.owner_inventory(authority, root)


def test_empty_or_overlapping_owner_is_refused(tmp_path):
    root, authority = sample(tmp_path)
    authority["owners"]["duplicate"] = authority["owners"]["sample.owner"]
    with pytest.raises(ValueError, match="duplicate test ownership"):
        runner.owner_inventory(authority, root)
    (root / "tests/sample/test_cases.py").unlink()
    with pytest.raises(ValueError, match="no test modules"):
        runner.owner_inventory(authority, root)


def test_owner_inventory_includes_declared_test_roots_outside_tests(tmp_path):
    root, authority = sample(tmp_path)
    outside = root / "qualification/tests"
    outside.mkdir(parents=True)
    (outside / "test_future.py").write_text("def test_future(): pass\n")
    authority["owners"]["future"] = {"paths": ["qualification/tests"],
                                          "execution": {"kind": "pytest-junit"}}
    assert runner.owner_inventory(authority, root)["future"] == ["qualification/tests/test_future.py"]


def test_collection_cannot_credit_zero_test_modules(tmp_path):
    root, _authority = sample(tmp_path, "VALUE = 1\n")
    with pytest.raises(ValueError, match="collection failed|omitted test modules"):
        runner.collect_owner("sample.owner", ["tests/sample/test_cases.py"],
                             root, runner.execution_environment())


@pytest.mark.parametrize("outcome", ["passed", "skipped"])
def test_only_the_exact_settled_expected_failure_is_accepted(tmp_path, outcome):
    authority = runner.load_authority()
    expected = runner._expected_xfails(authority, "wealth-core.prospective")
    modules = sorted({node.split("::", 1)[0] for node in expected})
    doc = ET.Element("testsuite")
    collected = set(expected)
    for node in sorted(expected):
        path, *names = node.split("::")
        classname = path[:-3].replace("/", ".")
        if len(names) > 1:
            classname += "." + ".".join(names[:-1])
        case = ET.SubElement(doc, "testcase", classname=classname, name=names[-1])
        if outcome == "skipped":
            ET.SubElement(case, "skipped", type="pytest.xfail")
    for module in modules:
        ET.SubElement(doc, "testcase", classname=module[:-3].replace("/", "."), name="test_other_passes")
        collected.add(module + "::test_other_passes")
    junit = tmp_path / "junit.xml"
    ET.ElementTree(doc).write(junit)
    if outcome == "passed":
        with pytest.raises(AssertionError, match="missing_expected_xfails"):
            runner.verify_owner("wealth-core.prospective", modules, collected,
                                junit, authority, tmp_path)
    else:
        assert runner.verify_owner("wealth-core.prospective", modules, collected,
                                   junit, authority, tmp_path)["passing_nodes"] == len(modules)


def test_independent_collection_cannot_be_measured_as_execution(monkeypatch, tmp_path):
    env = {"COVERAGE_PROCESS_START": "startup.ini", "COVERAGE_PROCESS_CONFIG": "legacy.ini"}
    seen = []
    def command(argv, **kwargs):
        seen.append(kwargs["env"])
        return SimpleNamespace(returncode=0, stdout="tests/test_one.py::test_one\n")
    monkeypatch.setattr(runner.subprocess, "run", command)
    assert runner.collect_owner("sample", ["tests/test_one.py"], tmp_path, env)
    assert not any(key.startswith("COVERAGE_PROCESS_") for key in seen[0])
    assert env["COVERAGE_PROCESS_START"] == "startup.ini"


def test_collection_environment_discards_inherited_pytest_selection(monkeypatch):
    monkeypatch.setenv("PYTEST_ADDOPTS", "-k silently_omit_others")
    assert "PYTEST_ADDOPTS" not in runner.execution_environment()


def test_coverage_command_keeps_owner_inventory_and_unique_junit(tmp_path):
    config = tmp_path / "coverage.ini"
    junit = tmp_path / "owner.xml"
    command = runner.pytest_command(["tests/test_one.py"], junit, ["-vv"], config)
    assert "--branch" in command and "--parallel-mode" in command
    assert command[-1] == f"--junitxml={junit}"
    assert command.count("tests/test_one.py") == 1


def test_execution_removes_stale_junit_before_starting_owner(tmp_path, monkeypatch):
    root, authority = sample(tmp_path)
    evidence = tmp_path / "evidence"
    owner = evidence / "sample.owner"
    owner.mkdir(parents=True)
    (owner / "junit.xml").write_text("<testsuite/>")
    monkeypatch.setattr(runner, "collect_owner", lambda *args: {"tests/sample/test_cases.py::test_one"})
    def no_junit(*args, **kwargs):
        assert not (owner / "junit.xml").exists()
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(runner.subprocess, "run", no_junit)
    with pytest.raises(ValueError, match="did not produce JUnit"):
        runner.run_owner("sample.owner", ["tests/sample/test_cases.py"],
                         authority=authority, root=root, evidence=evidence, pytest_args=[])
