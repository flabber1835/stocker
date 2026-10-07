from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import shutil
import os
import subprocess
import sys
import xml.etree.ElementTree as ET

import pytest
import yaml

from tools import sentinel_ci_parallel_evidence as evidence
from tools import sentinel_ci_shards as shards


@pytest.mark.parametrize("failed_lane", [None, "sentinel-general-0", "sentinel-rolling-2",
                                          "sentinel-contention", "sentinel-status"])
def test_main_workers_cover_each_module_once_and_propagate_failure(tmp_path, failed_lane):
    root = Path(__file__).resolve().parents[2]
    workflow = yaml.safe_load((root / ".github/workflows/sentinel-safety.yml").read_text(encoding="utf-8"))
    steps = workflow["jobs"]["parallel-certification"]["steps"]
    modules = {p.name for p in (root / "tests/sentinel").glob("test_*.py")}
    modules |= {"test_future_ordinary.py", "test_rolling_future.py"}
    tests = tmp_path / "tests/sentinel"
    tests.mkdir(parents=True)
    for name in modules:
        (tests / name).touch()
    tools = tmp_path / "tools"
    tools.mkdir()
    shutil.copyfile(root / "tools/sentinel_ci_shards.py", tools / "sentinel_ci_shards.py")
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "add", "tests/sentinel"], cwd=tmp_path, check=True)
    output = tmp_path / "evidence"
    output.mkdir()
    binaries = tmp_path / "bin"
    binaries.mkdir()
    docker = binaries / "docker"
    docker.write_text(f"#!{sys.executable}\n" + '''import os, sys
from pathlib import Path
import xml.etree.ElementTree as ET
args = sys.argv[1:]
if os.environ.get('FAILED_LANE') == os.environ['CI_LANE']:
    raise SystemExit(7)
selected = [Path(a) for a in args if a.startswith('tests/sentinel/test_')]
suite = ET.Element('testsuite')
for p in selected:
    ET.SubElement(suite, 'testcase', classname=p.stem, name='owned_case')
target = next(a.split('=', 1)[1] for a in args if a.startswith('--junitxml='))
ET.ElementTree(suite).write(target)
''', encoding="utf-8")
    docker.chmod(0o755)
    lanes = (*evidence.MAIN_LANES,)
    for lane in lanes:
        condition = ("${{ startsWith(matrix.lane, 'sentinel-general-') }}"
                     if lane.startswith("sentinel-general-") else
                     "${{ startsWith(matrix.lane, 'sentinel-rolling-') }}"
                     if lane.startswith("sentinel-rolling-") else
                     "${{ matrix.lane == '" + lane + "' }}")
        step = next(s for s in steps if s.get("if") == condition)
        command = step["run"].replace("/evidence/", str(output) + "/")
        command = command.replace("/tmp/sentinel-lane-evidence", str(output))
        result = subprocess.run(["bash", "-c", command], cwd=tmp_path,
            capture_output=True, text=True, env={**os.environ,
                "PATH": str(binaries) + os.pathsep + os.environ["PATH"],
                "CI_LANE": lane, "FAILED_LANE": failed_lane or ""})
        assert result.returncode == (7 if lane == failed_lane else 0), result.stdout + result.stderr
    cases = [case for lane in lanes if lane != failed_lane
             for case in ET.parse(output / f"{lane}.xml").iter("testcase")]
    expected = modules - shards.AUTOMATION - {"test_source_seed_warmup.py"}
    if failed_lane:
        expected -= set(Path(path).name for path in
                        shards.plan([f"tests/sentinel/{name}" for name in modules]).get(failed_lane, ()))
        if failed_lane == "sentinel-contention":
            expected.remove("test_runtime_contention.py")
        if failed_lane == "sentinel-status":
            expected.remove("test_status_memory.py")
    assert {case.get("classname") + ".py" for case in cases} == expected
    assert len(cases) == len(expected)


def test_minimum_host_lane_reserves_checkout_margin_without_weakening_evidence():
    workflow = yaml.safe_load((Path(__file__).resolve().parents[2] /
                              '.github/workflows/sentinel-safety.yml').read_text(encoding='utf-8'))
    job = workflow['jobs']['host-python-38-compatibility']
    budget = job['timeout-minutes']
    assert type(budget) is int
    # The former ten-minute job was exhausted inside checkout. Keep its
    # execution/evidence allowance after a bounded fifteen-minute setup margin.
    assert 15 + 10 <= budget <= 30
    assert job['strategy']['fail-fast'] is False
    assert 'exact-head' in job['strategy']['matrix']['scope']
    assert 'synthetic-merge' in job['strategy']['matrix']['scope']
    proof = next(step for step in job['steps']
                 if step.get('name') == 'Prove exact execution or synthetic-tree equivalence')
    assert 'python tools/verify_ci_scope.py' in proof['run']
    retained = next(step for step in job['steps']
                    if step.get('name') == 'Retain host Python 3.8 execution evidence')
    assert retained['if'] == 'always()'
    assert retained['with']['if-no-files-found'] == 'error'


def test_warmup_lane_has_bounded_setup_margin_and_streams_all_test_evidence():
    workflow = yaml.safe_load((Path(__file__).resolve().parents[2] /
                              ".github/workflows/sentinel-safety.yml").read_text(encoding="utf-8"))
    job = workflow["jobs"]["parallel-certification"]
    assert job["timeout-minutes"] == (
        "${{ (matrix.lane == 'sentinel-warmup' || "
        "startsWith(matrix.lane, 'sentinel-rolling-')) && 60 || 45 }}"
    )
    step = next(step for step in job["steps"]
                if step.get("if") == "${{ matrix.lane == 'sentinel-warmup' }}")
    command = step["run"]
    assert "tests/sentinel/test_source_seed_warmup.py -vv -ra" in command
    assert "--capture=tee-sys --durations=10" in command
    assert "--junitxml=/evidence/sentinel-warmup.xml" in command
    assert "set -euo pipefail" in command
    assert "2>&1 | tee /tmp/sentinel-lane-evidence/summary.txt" in command


@pytest.fixture
def campaign(tmp_path, monkeypatch):
    source = {"commit": "a" * 40, "tree": "b" * 40,
              "workflow_run": 123, "workflow_attempt": 1}
    images = {"sentinel:ci": "sha256:" + "c" * 64,
              "sentinel-test:ci": "sha256:" + "d" * 64}
    calls = []
    monkeypatch.setattr(evidence, "_source_identity", lambda root: deepcopy(source))
    monkeypatch.setattr(evidence, "_docker_image_identity",
                        lambda root, ref: (images[ref], "a" * 40))

    def docker(argv, **kwargs):
        calls.append(argv)
        if argv[1] == "save":
            Path(argv[3]).write_bytes(" ".join(argv[4:]).encode())

    monkeypatch.setattr(evidence.subprocess, "run", docker)
    bundle = tmp_path / "bundle"
    evidence.build_bundle(tmp_path, bundle)
    workers = tmp_path / "workers"
    workers.mkdir()
    for lane in evidence.LANES:
        directory = workers / lane
        directory.mkdir()
        for name in evidence.REQUIRED_FILES[lane]:
            path = directory / name
            if name.endswith(".xml"):
                path.write_text('<testsuite><testcase classname="' + lane +
                                '" name="test_pass"/></testsuite>', encoding="utf-8")
            elif name == "summary.txt":
                path.write_text("1 passed\n", encoding="utf-8")
            else:
                path.write_text("{}\n", encoding="utf-8")
        evidence.complete_lane(tmp_path, bundle, directory, lane)
    needs = {key: {"result": "success"} for key in evidence.DEPENDENCIES}
    return tmp_path, bundle, workers, needs, source, images, calls


def test_loads_once_built_archives_and_reobserves_both_image_ids(campaign):
    root, bundle, _, _, _, _, calls = campaign
    result = evidence.verify_bundle(root, bundle, load=True)
    assert set(result["files"]) == {"images.tar"}
    assert [argv[1] for argv in calls] == ["save", "load"]
    assert calls[0][-2:] == ["sentinel:ci", "sentinel-test:ci"]


@pytest.mark.parametrize("field", ["commit", "tree", "workflow_run", "workflow_attempt"])
def test_bundle_refuses_stale_source_or_attempt_before_loading(campaign, field):
    root, bundle, _, _, source, _, calls = campaign
    source[field] = source[field] + 1 if isinstance(source[field], int) else "e" * 40
    with pytest.raises(ValueError, match=field):
        evidence.verify_bundle(root, bundle, load=True)
    assert len(calls) == 1


@pytest.mark.parametrize("reference", ["sentinel:ci", "sentinel-test:ci"])
def test_refuses_different_loaded_image_id(campaign, reference):
    root, bundle, _, _, _, images, _ = campaign
    images[reference] = "sha256:" + "e" * 64
    with pytest.raises(ValueError, match="image IDs differ"):
        evidence.verify_bundle(root, bundle)


def test_refuses_wrong_image_source_label(campaign, monkeypatch):
    root, bundle, _, _, _, images, _ = campaign
    monkeypatch.setattr(evidence, "_docker_image_identity",
                        lambda root, ref: (images[ref], "f" * 40))
    with pytest.raises(ValueError, match="revision differs"):
        evidence.verify_bundle(root, bundle)


@pytest.mark.parametrize("fault", ["changed", "missing", "extra"])
def test_bundle_checks_exact_archive_inventory_and_bytes(campaign, fault):
    root, bundle, _, _, _, _, calls = campaign
    if fault == "changed":
        (bundle / "images.tar").write_bytes(b"different image archive")
    elif fault == "missing":
        (bundle / "images.tar").unlink()
    else:
        (bundle / "unverified.tar").write_bytes(b"extra")
    with pytest.raises(ValueError, match="inventory/hash"):
        evidence.verify_bundle(root, bundle, load=True)
    assert len(calls) == 1


@pytest.mark.parametrize("dependency", sorted(evidence.DEPENDENCIES))
@pytest.mark.parametrize("result", ["failure", "cancelled", "skipped", None])
def test_every_unsuccessful_dependency_refuses_certification(campaign, dependency, result):
    root, bundle, workers, needs, _, _, _ = campaign
    needs[dependency]["result"] = result
    with pytest.raises(ValueError, match="did not succeed"):
        evidence.assemble(root, bundle, workers, needs, root / "output")
    assert not (root / "output").exists()


@pytest.mark.parametrize("fault", ["missing", "extra"])
def test_exact_dependency_inventory_is_mandatory(campaign, fault):
    root, bundle, workers, needs, _, _, _ = campaign
    if fault == "missing":
        del needs["sharadar-replay"]
    else:
        needs["unreviewed-job"] = {"result": "success"}
    with pytest.raises(ValueError, match="dependency inventory"):
        evidence.verify_lanes(root, bundle, workers, needs)


@pytest.mark.parametrize("lane", evidence.LANES)
def test_each_lane_and_shard_is_required_even_when_github_needs_succeeded(campaign, lane):
    root, bundle, workers, needs, _, _, _ = campaign
    shutil.rmtree(workers / lane)
    with pytest.raises(ValueError, match="missing or extra"):
        evidence.verify_lanes(root, bundle, workers, needs)


@pytest.mark.parametrize("fault", ["duplicate", "undeclared", "stale-attempt", "attempt-bool", "wrong-image",
                                  "wrong-bundle", "missing-file", "changed-file", "extra-file"])
def test_receipts_refuse_mixed_or_incomplete_evidence(campaign, fault):
    root, bundle, workers, needs, _, _, _ = campaign
    directory = workers / "sentinel-warmup"
    receipt = json.loads((directory / "receipt.json").read_text())
    if fault == "duplicate":
        receipt["lane"] = "sentinel-general-0"
    elif fault == "undeclared":
        receipt["lane"] = "some-other-suite"
    elif fault == "stale-attempt":
        receipt["identity"]["workflow_attempt"] += 1
    elif fault == "attempt-bool":
        receipt["identity"]["workflow_attempt"] = True
    elif fault == "wrong-image":
        receipt["identity"]["images"]["sentinel-test:ci"] = "sha256:" + "e" * 64
    elif fault == "wrong-bundle":
        receipt["bundle_sha256"] = "f" * 64
    elif fault == "missing-file":
        (directory / "sentinel-warmup.xml").unlink()
    elif fault == "changed-file":
        (directory / "summary.txt").write_text("unverified result\n")
    else:
        (directory / "unverified.txt").write_text("extra\n")
    evidence._write_json(directory / "receipt.json", receipt)
    with pytest.raises(ValueError):
        evidence.verify_lanes(root, bundle, workers, needs)


def test_assembly_merges_all_sentinel_partitions_and_preserves_replay_and_mutants(campaign):
    root, bundle, workers, needs, _, _, _ = campaign
    output = root / "output"
    result = evidence.assemble(root, bundle, workers, needs, output)
    assert result["sentinel_tests"] == len(evidence.MAIN_LANES) + 2
    assert result["lanes"] == list(evidence.LANES)
    assert f"{len(evidence.MAIN_LANES) + 2} passed (complete disjoint Sentinel JUnit union)" in (
        output / "sentinel-complete.txt").read_text()
    assert sorted(path.name for path in (output / "sharadar-required-evidence").iterdir()) == [
        "0", "1", "2", "3"]
    assert (output / "sentinel-mutation-evidence/report.json").read_bytes() == (
        workers / "mutations/report.json").read_bytes()


@pytest.mark.parametrize("fault", ["duplicate", "failure", "error", "skipped"])
def test_valid_receipt_cannot_hide_duplicate_or_nonpassing_sentinel_junit(campaign, fault):
    root, bundle, workers, needs, _, _, _ = campaign
    directory = workers / "sentinel-warmup"
    if fault == "duplicate":
        body = (workers / "sentinel-general-0/sentinel-general-0.xml").read_text()
    else:
        body = ('<testsuite><testcase classname="sentinel-warmup" name="test_pass">'
                f'<{fault}/></testcase></testsuite>')
    (directory / "sentinel-warmup.xml").write_text(body, encoding="utf-8")
    (directory / "receipt.json").unlink()
    evidence.complete_lane(root, bundle, directory, "sentinel-warmup")
    with pytest.raises(ValueError, match="duplicate|non-passing"):
        evidence.assemble(root, bundle, workers, needs, root / "output")
