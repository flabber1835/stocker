from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import shutil

import pytest
import yaml

from tools import sentinel_ci_parallel_evidence as evidence


def test_warmup_lane_streams_progress_without_raising_its_deadline():
    workflow = yaml.safe_load((Path(__file__).resolve().parents[2] /
                              ".github/workflows/sentinel-safety.yml").read_text(encoding="utf-8"))
    job = workflow["jobs"]["parallel-certification"]
    assert job["timeout-minutes"] == 45
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
        receipt["lane"] = "sentinel-main"
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
    assert result["sentinel_tests"] == 3
    assert result["lanes"] == list(evidence.LANES)
    assert "3 passed (complete disjoint Sentinel JUnit union)" in (
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
        body = (workers / "sentinel-main/sentinel-main.xml").read_text()
    else:
        body = ('<testsuite><testcase classname="sentinel-warmup" name="test_pass">'
                f'<{fault}/></testcase></testsuite>')
    (directory / "sentinel-warmup.xml").write_text(body, encoding="utf-8")
    (directory / "receipt.json").unlink()
    evidence.complete_lane(root, bundle, directory, "sentinel-warmup")
    with pytest.raises(ValueError, match="duplicate|non-passing"):
        evidence.assemble(root, bundle, workers, needs, root / "output")
