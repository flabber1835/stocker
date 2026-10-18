"""A coverage artifact cannot invent source, owners or passing execution."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

import coverage
import pytest
import yaml

from tools import ci_coverage_campaign as campaign
from tools import repository_code_coverage as reporter


AUTHORITY = {"owners": {
    "one": {"execution": {"kind": "pytest-junit"}},
    "two": {"execution": {"kind": "pytest-junit"}},
    "alias": {"execution": {"kind": "delegated"}},
    "host": {"execution": {"kind": "unittest-discovery"}},
}}


def test_owner_plan_is_complete_unique_and_does_not_repeat_delegated_work():
    assert campaign.selected_owners(AUTHORITY) == ["one", "two"]
    assert campaign.selected_owners(AUTHORITY, "two,one") == ["one", "two"]


@pytest.mark.parametrize("names", ["one,one", "alias", "host", "missing", "one,", " one"])
def test_missing_unknown_or_duplicate_owners_refuse(names):
    with pytest.raises(ValueError, match="distinct explicit"):
        campaign.selected_owners(AUTHORITY, names)


def test_coverage_config_keeps_branches_children_and_exclusions_explicit(tmp_path):
    config = campaign.write_config(tmp_path)
    cov = coverage.Coverage(config_file=str(config))
    assert cov.get_option("run:branch") is True
    assert cov.get_option("run:parallel") is True
    assert cov.get_option("run:concurrency") == ["multiprocessing"]
    for option in ("exclude_lines", "exclude_also", "partial_branches", "partial_also"):
        assert cov.get_option("report:" + option) == []
    assert cov.get_option("run:data_file") == str(tmp_path / "raw/coverage")
    assert "/work/research" in cov.get_option("run:source")
    assert "/work/audit" in cov.get_option("run:source")
    assert "/work/scripts" in cov.get_option("run:source")
    assert "/app/tools" in cov.get_option("run:source")


def test_inventory_trusts_only_the_exact_read_only_checkout(tmp_path, monkeypatch):
    (tmp_path / "program.py").write_text("print('source')\n")
    calls = []

    def output(command, **kwargs):
        calls.append((command, kwargs))
        if command[-2:] == ["ls-files", "-z"]:
            return b"program.py\0"
        return "a" * 40 + "\n"

    monkeypatch.setattr(campaign.subprocess, "check_output", output)
    manifest = campaign.inventory(tmp_path)
    assert manifest["revision"] == "a" * 40
    assert len(calls) == 2
    assert all(command[:3] == ["git", "-c", "safe.directory=" + str(tmp_path.resolve())]
               and kwargs["cwd"] == tmp_path for command, kwargs in calls)


def test_subprocess_startup_does_not_modify_a_developer_interpreter(tmp_path, monkeypatch):
    monkeypatch.delenv("SENTINEL_IN_IMAGE", raising=False)
    before = set(tmp_path.iterdir())
    with pytest.raises(RuntimeError, match="disposable test lens"):
        campaign.install_child_startup(tmp_path)
    assert set(tmp_path.iterdir()) == before


def test_startup_hook_refuses_to_replace_another_hook(tmp_path, monkeypatch):
    monkeypatch.setenv("SENTINEL_IN_IMAGE", "1")
    path = tmp_path / "sentinel_advisory_coverage.pth"
    path.write_text("another startup hook\n")
    with pytest.raises(RuntimeError, match="another interpreter"):
        campaign.install_child_startup(tmp_path)
    assert path.read_text() == "another startup hook\n"


@pytest.mark.parametrize("requested", [False, True])
def test_startup_hook_imports_coverage_only_when_requested(tmp_path, monkeypatch, requested):
    monkeypatch.setenv("SENTINEL_IN_IMAGE", "1")
    hook = campaign.install_child_startup(tmp_path)
    script = """
import importlib.abc
import importlib.util
import os
from pathlib import Path
import sys

class CoverageProbe(importlib.abc.MetaPathFinder, importlib.abc.Loader):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == 'coverage':
            if not os.environ.get('COVERAGE_PROCESS_START'):
                raise RuntimeError('COVERAGE_IMPORT_WITHOUT_REQUEST')
            return importlib.util.spec_from_loader(fullname, self)

    def create_module(self, spec):
        return None

    def exec_module(self, module):
        module.process_startup = lambda: print('COVERAGE_STARTED')

sys.meta_path.insert(0, CoverageProbe())
exec(Path(sys.argv[1]).read_text())
print('HOOK_COMPLETE')
"""
    env = {key: value for key, value in os.environ.items()
           if key not in {"COVERAGE_PROCESS_START", "COVERAGE_PROCESS_CONFIG"}}
    if requested:
        env["COVERAGE_PROCESS_START"] = "explicit-request.ini"
    result = subprocess.run(
        [sys.executable, "-S", "-c", script, str(hook)], env=env,
        capture_output=True, text=True, timeout=10, check=False)
    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    assert result.stdout.splitlines() == (["COVERAGE_STARTED"] if requested else []) + ["HOOK_COMPLETE"]


@pytest.fixture
def measured(tmp_path, monkeypatch):
    source = tmp_path / "source"
    source.mkdir()
    path = source / "program.py"
    path.write_text("def choose(flag):\n    if flag:\n        return 1\n    return 0\n")
    # Unimported code must remain in the denominator.
    (source / "untouched.py").write_text("raise RuntimeError('not executed')\n")
    manifest = reporter.source_inventory(
        source, ["program.py", "untouched.py"], revision="a" * 40)
    monkeypatch.setattr(campaign, "inventory", lambda _root: manifest)
    data = tmp_path / "measurements"
    data.mkdir()
    counter = data / "coverage.host.123.random"
    cov = coverage.Coverage(data_file=str(counter), branch=True, include=[str(path)])
    cov.start()
    namespace = {}
    exec(compile(path.read_text(), str(path), "exec"), namespace)
    assert namespace["choose"](True) == 1
    cov.stop()
    cov.save()
    receipt = {"schema": "sentinel.advisory-coverage-execution/1",
               "owner": "one", "exit_code": 0, "revision": "a" * 40}
    (data / "coverage-execution.json").write_text(json.dumps(receipt))
    return source, data, tmp_path / "report"


def test_real_branch_report_preserves_missing_paths_and_has_no_release_authority(measured):
    source, data, output = measured
    report = campaign.write_report(source, output, data, ["one"])
    assert report["claims_release_authority"] is False
    assert report["status"] == "INCOMPLETE"
    assert report["python"]["missing_branches"] > 0
    untouched = next(item for item in report["files"] if item["path"] == "untouched.py")
    assert untouched["missing_statements"] == untouched["statements"] > 0
    summary = (output / "coverage-summary.md").read_text()
    assert "Selected pytest owners: `one`" in summary


@pytest.mark.parametrize("owners", [["one", "two"], [], ["two"]])
def test_partial_or_unexpected_owner_receipts_cannot_make_a_complete_campaign(measured, owners):
    source, data, output = measured
    with pytest.raises(ValueError, match="selected owner union"):
        campaign.write_report(source, output, data, owners)


def test_stale_source_execution_receipt_refuses(measured):
    source, data, output = measured
    path = data / "coverage-execution.json"
    receipt = json.loads(path.read_text())
    receipt["revision"] = "b" * 40
    path.write_text(json.dumps(receipt))
    with pytest.raises(ValueError, match="bound to this source"):
        campaign.write_report(source, output, data, ["one"])


def test_empty_counter_set_cannot_be_reported_as_a_baseline(tmp_path, monkeypatch):
    monkeypatch.setattr(campaign, "inventory", lambda _root: {})
    with pytest.raises(ValueError, match="no coverage counters"):
        campaign.write_report(tmp_path, tmp_path / "out", tmp_path / "data", ["one"])


@pytest.mark.parametrize("name", ["coverage.host.pid123.random", "coverage.host.123.random"])
def test_only_proven_empty_child_bytes_admit_pinned_coverage_naming(tmp_path, name):
    path = tmp_path / name
    path.write_bytes(b"")
    assert reporter._empty_unflushed_child(path)
    path.write_bytes(b"corrupt recorded data")
    assert not reporter._empty_unflushed_child(path)


def test_workflow_is_manual_advisory_and_keeps_current_attempt_and_failed_execution():
    root = Path(__file__).resolve().parents[2]
    text = (root / ".github/workflows/repository-coverage.yml").read_text()
    workflow = yaml.safe_load(text)
    trigger = workflow.get("on", workflow.get(True))
    assert set(trigger) == {"workflow_dispatch"}
    assert workflow["permissions"] == {"contents": "read"}
    assert workflow["jobs"]["measure"]["strategy"]["fail-fast"] is False
    assert "github.run_attempt" in text
    assert "--network none" in text
    assert "--owners \"$COVERAGE_OWNERS\"" in text
    assert "test \"$MEASUREMENT_RESULT\" = success" in text
    assert "packages: write" not in text
