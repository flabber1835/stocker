from copy import deepcopy
import hashlib
import io
import json
from pathlib import Path
import zipfile

import pytest

from scripts import sentinel_ci_promotion as policy
from scripts import sentinel_ci_certification_verify as verifier
from tools import sentinel_ci_promote as promote
from tools import sentinel_ci_certification_manifest as cert
from tests.scripts.test_sentinel_ci_certification_manifest import _input, _jobs

MERGED, TESTED, TREE = "a" * 40, "c" * 40, "b" * 40


def image(commit, image_id):
    return {"Id": image_id, "Architecture": "amd64", "Os": "linux",
            "RootFS": {"Type": "layers", "Layers": ["sha256:" + "7" * 64]},
            "Config": {"User": "sentinel", "Entrypoint": ["python"], "Cmd": ["-m", "sentinel"],
                       "Env": ["PATH=/usr/bin", "SENTINEL_IMAGE_SOURCE_REVISION=" + commit],
                       "Labels": {"org.opencontainers.image.revision": commit, "other": "retained"}}}


@pytest.fixture
def authority():
    repo = {"id": policy.REPOSITORY_ID, "full_name": policy.REPOSITORY}
    runs, plan = {}, {"schema": policy.PLAN_SCHEMA, "mode": "promote", "source_commit": MERGED,
        "source_tree": TREE, "pr": 501, "tested_commit": TESTED, "tested_tree": TREE,
        "workflows": [], "checkout_proofs": []}
    artifacts, archives = {}, {}
    for i, path in enumerate(policy.WORKFLOWS):
        run_id = 100 + i
        plan["workflows"].append({"path": path, "run": run_id, "attempt": 1})
        runs[run_id] = {"id": run_id, "workflow_id": 333697638 if i == 0 else 900 + i,
            "path": path, "head_sha": TESTED, "event": "pull_request", "status": "completed",
            "conclusion": "success", "run_attempt": 1, "repository": repo, "head_repository": repo}
    for i, role in ((0, None), (1, "composition"), (2, "browser")):
        name = "sentinel-tested-image-" + TESTED if role is None else "ci-checkout-proof-%s-1" % role
        digest = "sha256:" + "8" * 64
        if role:
            proof = {"repository": policy.REPOSITORY, "path": policy.WORKFLOWS[i], "commit": TESTED,
                     "tree": TREE, "run": 100 + i, "attempt": 1}
            stream = io.BytesIO()
            with zipfile.ZipFile(stream, "w") as archive:
                archive.writestr("proof.json", json.dumps(proof))
            archives[200 + i] = stream.getvalue()
            digest = "sha256:" + hashlib.sha256(stream.getvalue()).hexdigest()
        item = {"id": 200 + i, "digest": digest, "name": name, "run": 100 + i}
        artifacts[200 + i] = {**item, "expired": False, "workflow_run": {"id": 100 + i}}
        if role:
            plan["checkout_proofs"].append({"artifact": item, "proof": proof})
        else:
            plan["artifact"] = item
    pr = {"number": 501, "merged": True, "merged_at": "2026-10-10T00:00:00Z", "merge_commit_sha": MERGED,
          "base": {"ref": "main", "repo": repo}, "head": {"sha": TESTED, "repo": repo}}
    checks = [{"name": name, "head_sha": TESTED, "status": "completed", "conclusion": "success"}
              for name in ("host-python-38-exact-head", "sentinel-exact-head", "iPhone WebKit and PWA",
                           "composition-synthetic-merge")]

    class Client:
        commit_trees = {MERGED: TREE, TESTED: TREE}
        def json(self, path):
            tail = path.split("?")[0].split("/")
            if "/git/commits/" in path:
                return {"sha": tail[-1], "tree": {"sha": self.commit_trees[tail[-1]]}}
            if "/pulls/" in path:
                return pr
            if "/check-runs" in path:
                return {"check_runs": checks}
            if "/actions/workflows/" in path:
                return {"workflow_runs": [x for x in runs.values() if x["path"].endswith(tail[-2])]}
            if "/actions/artifacts/" in path:
                return artifacts[int(tail[-1])]
            if tail[-1] == "jobs":
                return {"jobs": [{"name": "qualified", "conclusion": "success"}]}
            if tail[-1] == "artifacts":
                return {"artifacts": [x for x in artifacts.values() if x["run"] == int(tail[-2])]}
            return runs[int(tail[-1])]

        def array(self, path):
            return [pr]

        def bytes(self, path):
            return archives[int(path.split("/")[-2])]

    return plan, Client(), pr, checks, runs, artifacts


def test_exact_tree_selection_and_independent_authority_reobservation(authority, monkeypatch, tmp_path):
    plan, client, *_ = authority
    monkeypatch.setattr(promote, "identity", lambda root: {"source_commit": MERGED, "source_tree": TREE})
    assert promote.select(tmp_path, client, "push", "refs/heads/main") == plan
    policy.verify_plan(client, plan)


def test_pr_always_runs_full_qualification_without_reading_github(monkeypatch, tmp_path):
    monkeypatch.setattr(promote, "identity", lambda root: {"source_commit": TESTED, "source_tree": TREE})
    assert promote.select(tmp_path, None, "pull_request", "refs/pull/501/merge")["mode"] == "full"


@pytest.mark.parametrize("change", ["tree", "missing", "expired", "workflow-failed"])
def test_unqualified_reuse_selects_full_suite(authority, monkeypatch, tmp_path, change):
    _, client, _, _, runs, artifacts = authority
    monkeypatch.setattr(promote, "identity", lambda root: {"source_commit": MERGED, "source_tree": "f" * 40 if change == "tree" else TREE})
    if change == "missing":
        del artifacts[200]
    elif change == "expired":
        artifacts[200]["expired"] = True
    elif change == "workflow-failed":
        runs[100]["conclusion"] = "failure"
    assert promote.select(tmp_path, client, "push", "refs/heads/main")["mode"] == "full"


@pytest.mark.parametrize("change", ["fork", "pr-head", "unmerged", "run-head", "run-event", "attempt", "run-path",
                                     "artifact-digest", "artifact-run", "artifact-expired", "nonpass-check", "bool-id",
                                     "synthetic-tree", "merged-tree", "missing-workflow", "duplicate-proof"])
def test_changed_or_spoofed_authority_refuses(authority, change):
    plan, client, pr, checks, runs, artifacts = authority
    if change == "fork": pr["head"]["repo"] = {"id": 1, "full_name": "other/stocker"}
    elif change == "pr-head": pr["head"]["sha"] = "f" * 40
    elif change == "unmerged": pr["merged"] = False
    elif change == "run-head": runs[100]["head_sha"] = "f" * 40
    elif change == "run-event": runs[100]["event"] = "workflow_dispatch"
    elif change == "attempt": runs[100]["run_attempt"] = 2
    elif change == "run-path": runs[100]["path"] = ".github/workflows/other.yml"
    elif change == "artifact-digest": artifacts[200]["digest"] = "sha256:" + "f" * 64
    elif change == "artifact-run": artifacts[200]["workflow_run"]["id"] = 999
    elif change == "artifact-expired": artifacts[200]["expired"] = True
    elif change == "nonpass-check": checks[0]["conclusion"] = "skipped"
    elif change == "bool-id": plan["pr"] = True
    elif change == "synthetic-tree": plan["checkout_proofs"][0]["proof"]["tree"] = "f" * 40
    elif change == "merged-tree": client.commit_trees[MERGED] = "f" * 40
    elif change == "missing-workflow": plan["workflows"].pop()
    elif change == "duplicate-proof": plan["checkout_proofs"][1] = plan["checkout_proofs"][0]
    with pytest.raises(policy.PromotionRefused): policy.verify_plan(client, plan)


@pytest.mark.parametrize("change", ["layer", "user", "command", "entrypoint", "env", "label", "arch", "duplicate-env", "missing-revision"])
def test_only_source_metadata_can_change(change):
    before, after = image(TESTED, "sha256:" + "d" * 64), image(MERGED, "sha256:" + "e" * 64)
    policy.verify_images(before, after, TESTED, MERGED)
    if change == "layer": after["RootFS"]["Layers"] = ["sha256:" + "f" * 64]
    elif change == "arch": after["Architecture"] = "arm64"
    elif change == "user": after["Config"]["User"] = "root"
    elif change == "command": after["Config"]["Cmd"] = ["other"]
    elif change == "entrypoint": after["Config"]["Entrypoint"] = ["other"]
    elif change == "env": after["Config"]["Env"].append("ADDED=unsafe")
    elif change == "label": after["Config"]["Labels"]["other"] = "changed"
    elif change == "duplicate-env": after["Config"]["Env"].append(after["Config"]["Env"][1])
    elif change == "missing-revision": del after["Config"]["Labels"]["org.opencontainers.image.revision"]
    with pytest.raises(policy.PromotionRefused): policy.verify_images(before, after, TESTED, MERGED)


def reused_input(plan):
    original = _input()
    original.update(source_commit=TESTED, test_workflow_run=100)
    before = image(TESTED, original["runtime_image_id"])
    after = image(MERGED, "sha256:" + "e" * 64)
    result = deepcopy(original)
    result.update(schema=cert.PROMOTED_INPUT_SCHEMA, source_commit=MERGED, runtime_image_id=after["Id"], test_workflow_run=800)
    result["qualification_reuse"] = {"schema": policy.PROMOTION_SCHEMA, "plan": plan,
                                    "original_input": original, "tested_image": before, "promoted_image": after}
    return result


def test_v3_manifest_preserves_original_counts_attempt_and_validates_independently(authority):
    evidence = reused_input(authority[0])
    value = cert.finalize_manifest(input_evidence=evidence, jobs_payload=_jobs(), subject_name=cert.RUNTIME_SUBJECT,
            image_digest="sha256:" + "9" * 64, publication_run=900, publication_attempt=1,
            certified_at="2026-10-10T00:00:00Z")
    cert.verify_manifest(value)
    verifier._verify_manifest(value, MERGED, TREE, {"id": 900, "run_attempt": 1})
    assert value["ci"]["test_workflow_run"] == 800
    assert value["qualification_reuse"]["original_input"]["test_workflow_run"] == 100
    assert value["tests"]["required_counts"]["passed"] == 123


@pytest.mark.parametrize("change", ["counts", "locks", "manifest", "mutation", "test-attempt", "image-id", "missing-input", "extra-input"])
def test_reuse_cannot_rewrite_original_qualification(authority, change):
    evidence = reused_input(authority[0])
    original = evidence["qualification_reuse"]["original_input"]
    if change == "counts":
        original["test_counts"]["total"]["passed"] += 1
        original["test_counts"]["suite_counts"]["sentinel"]["passed"] += 1
    elif change == "locks": original["dependency_lock_hashes"]["tests/requirements.lock"] = "f" * 64
    elif change == "manifest": original["test_manifest_sha256"] = "f" * 64
    elif change == "mutation": original["mutation_evidence"]["sha256"] = "f" * 64
    elif change == "test-attempt": original["test_workflow_attempt"] = 2
    elif change == "image-id": original["runtime_image_id"] = "sha256:" + "f" * 64
    elif change == "missing-input": original.pop("test_counts")
    elif change == "extra-input": original["unreviewed"] = True
    with pytest.raises(cert.CertificationManifestRefused): cert._validate_input(evidence)


def test_publisher_reobserves_actual_promoted_configuration(authority, monkeypatch, tmp_path):
    from tools import sentinel_ci_certification_input_binding as binding
    evidence = reused_input(authority[0])
    monkeypatch.setattr(cert, "_run", lambda argv, cwd: TREE if argv[-1] == "HEAD^{tree}" else MERGED)
    monkeypatch.setattr(cert, "_docker_image_identity", lambda root, ref: (evidence["runtime_image_id"], MERGED))
    monkeypatch.setattr(cert, "_dependency_hashes", lambda root: evidence["dependency_lock_hashes"])
    monkeypatch.setattr(cert, "_test_manifest_hash", lambda root: evidence["test_manifest_sha256"])
    monkeypatch.setattr(cert, "sha256_file", lambda path: evidence["runtime_capability_sha256"])
    monkeypatch.setattr(policy, "verify_plan", lambda client, plan: None)
    changed = deepcopy(evidence["qualification_reuse"]["promoted_image"])
    changed["Config"]["User"] = "root"
    monkeypatch.setattr(promote, "inspect", lambda root, ref: changed)
    with pytest.raises(binding.InputBindingRefused, match="configuration"):
        binding.verify_binding(root=tmp_path, evidence=evidence, expected_commit=MERGED,
                               expected_workflow_run=800, expected_workflow_attempt=1, image_ref="sentinel:ci")


@pytest.mark.parametrize("change", ["tar", "commit", "missing", "extra", "duplicate-sum", "unsafe-path", "symlink"])
def test_runtime_archive_is_exact_and_checksums_are_enforced(tmp_path, change):
    # Other host fixtures own siblings (including source-cache); the artifact
    # verifier must receive only the directory actually downloaded by Actions.
    tmp_path = tmp_path / "artifact"
    tmp_path.mkdir()
    for name, raw in {"sentinel-runtime.tar": b"qualified image", "COMMIT": (TESTED + "\n").encode(),
                      "software-certification-input.json": b"{}"}.items():
        (tmp_path / name).write_bytes(raw)
    sums = "".join(hashlib.sha256((tmp_path / name).read_bytes()).hexdigest() + "  " + name + "\n"
                   for name in sorted(x.name for x in tmp_path.iterdir()))
    (tmp_path / "SHA256SUMS").write_text(sums)
    promote.verify_archive(tmp_path, TESTED)
    if change == "tar": (tmp_path / "sentinel-runtime.tar").write_bytes(b"different image")
    elif change == "commit": (tmp_path / "COMMIT").write_bytes((MERGED + "\n").encode())
    elif change == "missing": (tmp_path / "COMMIT").unlink()
    elif change == "extra": (tmp_path / "extra").write_bytes(b"extra")
    elif change == "duplicate-sum": (tmp_path / "SHA256SUMS").write_text(sums + sums.splitlines()[0] + "\n")
    elif change == "unsafe-path": (tmp_path / "SHA256SUMS").write_text(sums.replace("  COMMIT", "  ../COMMIT"))
    elif change == "symlink":
        (tmp_path / "COMMIT").unlink(); (tmp_path / "COMMIT").symlink_to("sentinel-runtime.tar")
    with pytest.raises(policy.PromotionRefused): promote.verify_archive(tmp_path, TESTED)


@pytest.mark.parametrize("change", [None, "digest", "extra", "duplicate", "path", "symlink", "inner-checksum"])
def test_actual_runtime_zip_digest_and_members_are_bound_before_loading(authority, tmp_path, change):
    plan, client, _, _, _, artifacts = authority
    values = {"sentinel-runtime.tar": b"qualified image", "COMMIT": (TESTED + "\n").encode(),
              "software-certification-input.json": b"{}"}
    values["SHA256SUMS"] = "".join(hashlib.sha256(raw).hexdigest() + "  " + name + "\n"
                                      for name, raw in sorted(values.items())).encode()
    if change == "extra": values["extra"] = b"unreviewed"
    elif change == "path": values["../COMMIT"] = values.pop("COMMIT")
    elif change == "inner-checksum": values["sentinel-runtime.tar"] = b"changed image"
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        for name, raw in values.items():
            entry = zipfile.ZipInfo(name)
            if change == "symlink" and name == "COMMIT":
                entry.create_system = 3
                entry.external_attr = 0o120777 << 16
            archive.writestr(entry, raw)
        if change == "duplicate": archive.writestr("COMMIT", values["COMMIT"])
    raw = stream.getvalue()
    digest = "sha256:" + hashlib.sha256(raw).hexdigest()
    plan["artifact"]["digest"] = artifacts[200]["digest"] = digest
    class DownloadClient:
        json = client.json
        def bytes(self, path):
            return raw + (b"tamper" if change == "digest" else b"")
    output = tmp_path / "retained-runtime"
    if change is None:
        promote.download_runtime(DownloadClient(), plan, output)
        assert (output / "sentinel-runtime.tar").read_bytes() == b"qualified image"
    else:
        with pytest.raises(policy.PromotionRefused): promote.download_runtime(DownloadClient(), plan, output)
        if change != "inner-checksum": assert not output.exists()


@pytest.mark.parametrize("change", ["selection-failed", "runtime-cancelled", "worker-failed", "missing", "extra"])
def test_main_dependency_receipt_never_calls_failed_work_reused(change):
    value = {key: {"result": result} for key, result in {"qualification-source": "success", "runtime-build": "success",
             "parallel-certification": "skipped"}.items()}
    policy.verify_promotion_dependencies(value)
    if change == "selection-failed": value["qualification-source"]["result"] = "failure"
    elif change == "runtime-cancelled": value["runtime-build"]["result"] = "cancelled"
    elif change == "worker-failed": value["parallel-certification"]["result"] = "failure"
    elif change == "missing": value.pop("runtime-build")
    elif change == "extra": value["unreviewed"] = {"result": "success"}
    with pytest.raises(policy.PromotionRefused): policy.verify_promotion_dependencies(value)


@pytest.mark.parametrize("raw", [b'{"x":1,"x":2}', b'{"x":NaN}', b'{"x":1e999}', b'[]', b'null'])
def test_strict_json_input(tmp_path, raw):
    path = tmp_path / "input.json"; path.write_bytes(raw)
    with pytest.raises(verifier.CertificationVerificationRefused): promote.read(path)
    with pytest.raises(cert.CertificationManifestRefused): cert._read_json(path, label="input")


@pytest.mark.parametrize("raw", [b'{"x":1,"x":2}', b'{"x":NaN}', b'{"x":1e999}', b'[]', b'null'])
def test_cli_preserves_typed_json_refusal_without_creating_a_receipt(tmp_path, capsys, raw):
    path = tmp_path / "plan.json"; path.write_bytes(raw)
    receipt = tmp_path / "receipt.json"
    assert promote.main(["verify", "--plan", str(path), "--output", str(receipt)]) == 2
    assert not receipt.exists()
    assert capsys.readouterr().err == "REFUSED: promotion [CertificationVerificationRefused]\n"


def test_workflow_keeps_pr_full_execution_and_single_guarded_publisher():
    import yaml
    root = Path(__file__).resolve().parents[2]
    safety = yaml.safe_load((root / ".github/workflows/sentinel-safety.yml").read_text())
    jobs = safety["jobs"]
    for name in ("parallel-certification",):
        assert "needs.qualification-source.outputs.mode == 'full'" in jobs[name]["if"]
        assert "qualification-source" in jobs[name]["needs"]
    carrier = jobs["certification-and-durability"]
    retained = next(x for x in carrier["steps"] if x.get("name") == "Retain the exact tested runtime")
    assert retained["if"] == "${{ matrix.scope == 'exact-head' }}"
    assert "pull_request.head.sha" in retained["with"]["name"]
    publisher = (root / ".github/workflows/sentinel-publish.yml").read_text()
    assert "github.event.workflow_run.event == 'push'" in publisher
    assert "github.event.workflow_run.workflow_id == 333697638" in publisher
    assert publisher.index("Create durable Sigstore") < publisher.index("oras login")


@pytest.mark.parametrize("change", ["selector-disabled", "selector-masked", "selector-ref", "output", "detached", "extra-step"])
def test_pr_projection_cannot_hide_a_weakened_selector(change):
    from tools.validate_test_responsibility import _promotion_pr_view
    root = Path(__file__).resolve().parents[2]
    text = (root / ".github/workflows/sentinel-safety.yml").read_text()
    assert "python tools/sentinel_ci_parallel_evidence.py assemble" in _promotion_pr_view(text)
    if change == "selector-disabled": text = text.replace("    name: safety-qualification-source", "    if: false\n    name: safety-qualification-source", 1)
    elif change == "selector-masked": text = text.replace("select --output /tmp/promotion-plan.json", "select --output /tmp/promotion-plan.json || true", 1)
    elif change == "selector-ref": text = text.replace("ref: ${{ github.event.pull_request.head.sha || github.sha }}", "ref: main", 1)
    elif change == "output": text = text.replace("mode: ${{ steps.select.outputs.mode }}", "mode: promote", 1)
    elif change == "detached": text = text.replace("needs: [qualification-source, runtime-build, parallel-certification]", "needs: [runtime-build, parallel-certification]", 1)
    else: text = text.replace("  host-python-38-compatibility:", "      - run: echo mode=promote\n\n  host-python-38-compatibility:", 1)
    with pytest.raises(AssertionError): _promotion_pr_view(text)


def test_raw_owner_execution_entrypoint_audits_the_same_full_pr_branch():
    from tools import validate_test_responsibility as responsibility
    from tools import verify_test_owner_execution as execution
    root = Path(__file__).resolve().parents[2]
    raw = (root / ".github/workflows/sentinel-safety.yml").read_text()
    direct = responsibility._require_parallel_certification(raw)
    projected = responsibility._require_parallel_certification(responsibility._promotion_pr_view(raw))
    assert direct == projected
    assert execution._require_global_authority(execution.load_authority())["owner_jobs_checked"] > 0


def test_standalone_verifier_import_does_not_expose_inspection_runtime():
    import subprocess
    import sys
    scripts = Path(verifier.__file__).resolve().parent
    program = (
        "import sys; from pathlib import Path; "
        "scripts=Path(sys.argv[1]); repo=str(scripts.parent); "
        "sys.path[:]=[str(scripts)]+[p for p in sys.path if p!=repo]; "
        "before=list(sys.path); "
        "import sentinel_ci_certification_verify as reader; "
        "policy=reader._promotion_policy(); "
        "assert policy.REPOSITORY=='flabber1835/stocker'; "
        "assert sys.path==before; assert repo not in sys.path; "
        "print('STANDALONE_POLICY_IMPORT_RUNTIME_BOUNDARY_PASS')")
    done = subprocess.run([sys.executable, '-I', '-c', program, str(scripts)],
                          text=True, capture_output=True)
    assert done.returncode == 0, done.stdout + done.stderr
    assert 'STANDALONE_POLICY_IMPORT_RUNTIME_BOUNDARY_PASS' in done.stdout


@pytest.fixture
def producer_authority(authority, monkeypatch):
    plan, client, pr, checks, runs, artifacts = authority
    plan["schema"] = policy.PRODUCER_PLAN_SCHEMA
    for row in plan["workflows"]:
        row["evidence_attempt"] = 1
    original = _input()
    original.update(source_commit=TESTED, test_workflow_run=100)
    proof = {"schema": policy.PRODUCER_SCHEMA, "repository": policy.REPOSITORY,
             "commit": TESTED, "tree": TREE, "run": 100, "attempt": 1,
             "runtime_artifact": deepcopy(plan["artifact"]), "input_sha256": policy.input_digest(original)}
    raw = io.BytesIO()
    with zipfile.ZipFile(raw, "w") as archive:
        archive.writestr("proof.json", json.dumps(proof))
    item = {"id": 203, "run": 100, "name": "sentinel-qualification-producer-" + TESTED,
            "digest": "sha256:" + hashlib.sha256(raw.getvalue()).hexdigest()}
    artifacts[203] = {**item, "expired": False, "workflow_run": {"id": 100}}
    plan["producer_proof"] = {"artifact": item, "proof": proof}
    jobs = {}
    original_runs = {}
    for row in plan["workflows"]:
        names = ["sentinel-runtime-build", "sentinel-exact-head", "sentinel-suite-operator",
                 "sentinel-synthetic-merge", "host-python-38-synthetic-merge"] if row["run"] == 100 else ["qualified"]
        jobs[row["run"], 1] = [{"name": name, "run_id": row["run"], "head_sha": TESTED,
                                "status": "completed", "conclusion": "success"} for name in names]
        original_runs[row["run"], 1] = deepcopy(runs[row["run"]])
    old_json, old_bytes = client.json, client.bytes
    def query(url):
        parts = url.split("?")[0].split("/")
        if "attempts" in parts:
            i = parts.index("attempts")
            key = int(parts[i - 1]), int(parts[i + 1])
            return {"jobs": jobs[key]} if parts[-1] == "jobs" else original_runs[key]
        return old_json(url)
    monkeypatch.setattr(client, "json", query)
    monkeypatch.setattr(client, "bytes", lambda url: raw.getvalue() if "/203/zip" in url else old_bytes(url))
    monkeypatch.setattr(promote, "identity", lambda root: {"source_commit": MERGED, "source_tree": TREE})
    return plan, client, original, jobs, runs, original_runs, artifacts


def rerun_validation(value, index=0):
    plan, _, _, jobs, runs, originals, _ = value
    row = plan["workflows"][index]
    row["attempt"] = runs[row["run"]]["run_attempt"] = 2
    jobs[row["run"], 2] = deepcopy(jobs[row["run"], 1])
    originals[row["run"], 2] = deepcopy(runs[row["run"]])


@pytest.mark.parametrize("reporting", [None, "sentinel-synthetic-merge", "host-python-38-synthetic-merge"])
def test_partial_reporting_rerun_reuses_original_image_and_input(producer_authority, tmp_path, reporting):
    value = producer_authority
    plan, client, original, jobs, *_ = value
    rerun_validation(value)
    if reporting:
        next(j for j in jobs[100, 1] if j["name"] == reporting).update(status="in_progress", conclusion=None)
    selected = promote.select(tmp_path, client, "push", "refs/heads/main")
    assert selected == plan
    assert selected["workflows"][0] == {"path": policy.WORKFLOWS[0], "run": 100,
                                        "attempt": 2, "evidence_attempt": 1}
    evidence = reused_input(selected)
    cert._validate_input(evidence)
    assert evidence["qualification_reuse"]["original_input"] == original
    assert evidence["qualification_reuse"]["plan"]["artifact"]["id"] == 200


@pytest.mark.parametrize("index", [1, 2])
def test_partial_harness_rerun_retains_actual_checkout_producer(producer_authority, tmp_path, index):
    rerun_validation(producer_authority, index)
    plan, client, *_ = producer_authority
    assert promote.select(tmp_path, client, "push", "refs/heads/main") == plan
    policy.verify_plan(client, plan)


@pytest.mark.parametrize("change", ["failed-worker", "cancelled-worker", "skipped-worker", "missing-carrier",
                                     "failed-carrier", "runtime-failed", "duplicate-job", "foreign-job",
                                     "original-run-head", "original-run-repository", "original-attempt-type",
                                     "latest-failed", "latest-pending", "latest-job-failed", "future-producer"])
def test_partial_rerun_never_hides_unqualified_execution(producer_authority, change):
    value = producer_authority
    rerun_validation(value)
    plan, client, _, jobs, runs, originals, _ = value
    old = jobs[100, 1]
    if change in ("failed-worker", "cancelled-worker", "skipped-worker"):
        old[2]["conclusion"] = {"failed-worker": "failure", "cancelled-worker": "cancelled", "skipped-worker": "skipped"}[change]
    elif change == "missing-carrier": old.pop(1)
    elif change == "failed-carrier": old[1]["conclusion"] = "failure"
    elif change == "runtime-failed": old[0]["conclusion"] = "failure"
    elif change == "duplicate-job": old.append(deepcopy(old[0]))
    elif change == "foreign-job": old[2]["head_sha"] = "f" * 40
    elif change == "original-run-head": originals[100, 1]["head_sha"] = "f" * 40
    elif change == "original-run-repository": originals[100, 1]["repository"] = {"id": 1, "full_name": policy.REPOSITORY}
    elif change == "original-attempt-type": originals[100, 1]["run_attempt"] = True
    elif change == "latest-failed": runs[100]["conclusion"] = "failure"
    elif change == "latest-pending": runs[100]["status"] = "in_progress"
    elif change == "latest-job-failed": jobs[100, 2][2]["conclusion"] = "failure"
    elif change == "future-producer": plan["workflows"][0]["evidence_attempt"] = 3
    with pytest.raises(policy.PromotionRefused):
        policy.verify_plan(client, plan)


@pytest.mark.parametrize("change", ["artifact", "input", "producer-attempt", "producer-type", "source", "tree",
                                     "proof-run", "proof-digest", "expired-proof", "missing-proof", "unknown-field"])
def test_producer_proof_is_bound_to_retained_qualification(producer_authority, change):
    plan, client, _, _, _, _, artifacts = producer_authority
    proof = plan["producer_proof"]["proof"]
    if change == "artifact": proof["runtime_artifact"]["digest"] = "sha256:" + "f" * 64
    elif change == "input": proof["input_sha256"] = "sha256:" + "f" * 64
    elif change == "producer-attempt": proof["attempt"] = 2
    elif change == "producer-type": proof["attempt"] = True
    elif change == "source": proof["commit"] = "f" * 40
    elif change == "tree": proof["tree"] = "f" * 40
    elif change == "proof-run": proof["run"] = 999
    elif change == "proof-digest": artifacts[203]["digest"] = "sha256:" + "f" * 64
    elif change == "expired-proof": artifacts[203]["expired"] = True
    elif change == "missing-proof": plan.pop("producer_proof")
    elif change == "unknown-field": proof["unreviewed"] = True
    with pytest.raises((policy.PromotionRefused, cert.CertificationManifestRefused)):
        policy.verify_plan(client, plan)
        cert._validate_input(reused_input(plan))


def test_missing_legacy_provenance_is_classified_before_promoting(authority, monkeypatch, tmp_path):
    _, client, _, _, runs, _ = authority
    runs[100]["run_attempt"] = 2
    monkeypatch.setattr(promote, "identity", lambda root: {"source_commit": MERGED, "source_tree": TREE})
    result = promote.select(tmp_path, client, "push", "refs/heads/main")
    assert result["mode"] == "full"
    assert result["reason"] == "missing-producer-proof-after-rerun"


@pytest.mark.parametrize("change", ["current-attempt", "run", "source", "tree", "artifact-id", "artifact-digest"])
def test_producer_writer_cannot_rebind_current_qualification(authority, monkeypatch, tmp_path, change):
    original = _input()
    original.update(source_commit=TESTED, test_workflow_run=100)
    monkeypatch.setattr(promote, "identity", lambda root: {"source_commit": TESTED, "source_tree": TREE})
    kwargs = dict(run_id=100, attempt=1, artifact_id=200, artifact_digest="sha256:" + "8" * 64)
    if change == "current-attempt": kwargs["attempt"] = 2
    elif change == "run": kwargs["run_id"] = 999
    elif change == "source": original["source_commit"] = "f" * 40
    elif change == "tree": original["source_tree"] = "f" * 40
    elif change == "artifact-id": kwargs["artifact_id"] = True
    else: kwargs["artifact_digest"] = "bad"
    with pytest.raises(policy.PromotionRefused):
        promote.producer_proof(tmp_path, original, **kwargs)


def test_producer_writer_preserves_the_exact_input_digest(authority, monkeypatch, tmp_path):
    original = _input()
    original.update(source_commit=TESTED, test_workflow_run=100)
    monkeypatch.setattr(promote, "identity", lambda root: {"source_commit": TESTED, "source_tree": TREE})
    proof = promote.producer_proof(tmp_path, original, 100, 1, 200, "sha256:" + "8" * 64)
    assert proof["input_sha256"] == "sha256:" + cert.sha256_bytes(cert.canonical_bytes(original))
    assert proof["attempt"] == original["test_workflow_attempt"] == 1


def test_producer_check_failure_is_an_executed_falsifier(producer_authority, monkeypatch):
    rerun_validation(producer_authority)
    plan, client, _, jobs, *_ = producer_authority
    jobs[100, 1][2]["conclusion"] = "failure"
    def falsifier():
        with pytest.raises(policy.PromotionRefused):
            policy.verify_plan(client, plan)
    falsifier()
    monkeypatch.setattr(policy, "check_jobs", lambda *args: None)
    with pytest.raises(pytest.fail.Exception):
        falsifier()


def test_input_hash_failure_is_an_executed_falsifier(producer_authority, monkeypatch):
    plan = producer_authority[0]
    evidence = reused_input(plan)
    original = evidence["qualification_reuse"]["original_input"]
    original["test_counts"]["total"]["passed"] += 1
    original["test_counts"]["suite_counts"]["sentinel"]["passed"] += 1
    evidence["test_counts"] = deepcopy(original["test_counts"])
    def falsifier():
        with pytest.raises(cert.CertificationManifestRefused):
            cert._validate_input(evidence)
    falsifier()
    monkeypatch.setattr(policy, "input_digest", lambda value: plan["producer_proof"]["proof"]["input_sha256"])
    with pytest.raises(pytest.fail.Exception):
        falsifier()


def test_workflow_records_producer_only_after_runtime_upload():
    import yaml
    root = Path(__file__).resolve().parents[2]
    workflow = yaml.safe_load((root / ".github/workflows/sentinel-safety.yml").read_text())
    steps = workflow["jobs"]["certification-and-durability"]["steps"]
    runtime = next(i for i, step in enumerate(steps) if step.get("id") == "tested-runtime")
    writer = next(i for i, step in enumerate(steps) if "sentinel_ci_promote.py producer" in step.get("run", ""))
    retained = steps[writer + 1]
    assert runtime < writer
    assert "steps.tested-runtime.outputs.artifact-id" in steps[writer]["run"]
    assert "steps.tested-runtime.outputs.artifact-digest" in steps[writer]["run"]
    assert steps[writer]["if"] == retained["if"] == "${{ github.event_name == 'pull_request' && matrix.scope == 'exact-head' }}"
    assert retained["with"]["path"] == "/tmp/sentinel-qualification-producer/proof.json"
    assert retained["with"]["retention-days"] == 90


def test_partial_rerun_manifest_passes_independent_host_validation(producer_authority):
    rerun_validation(producer_authority)
    plan, client, *_ = producer_authority
    evidence = reused_input(plan)
    manifest = cert.finalize_manifest(input_evidence=evidence, jobs_payload=_jobs(),
            subject_name=cert.RUNTIME_SUBJECT, image_digest="sha256:" + "9" * 64,
            publication_run=900, publication_attempt=1, certified_at="2026-10-17T00:00:00Z")
    cert.verify_manifest(manifest)
    verifier._verify_manifest(manifest, MERGED, TREE, {"id": 900, "run_attempt": 1})
    policy.verify_plan(client, manifest["qualification_reuse"]["plan"])
    assert manifest["qualification_reuse"]["original_input"]["test_workflow_attempt"] == 1
    assert manifest["qualification_reuse"]["plan"]["workflows"][0]["attempt"] == 2


def test_embedded_proof_cannot_rewrite_the_actual_retained_input(producer_authority):
    plan, client, *_ = producer_authority
    evidence = reused_input(plan)
    original = evidence["qualification_reuse"]["original_input"]
    original["test_counts"]["total"]["passed"] += 1
    original["test_counts"]["suite_counts"]["sentinel"]["passed"] += 1
    evidence["test_counts"] = deepcopy(original["test_counts"])
    plan["producer_proof"]["proof"]["input_sha256"] = policy.input_digest(original)
    # Internal consistency cannot substitute for the original retained proof.
    cert._validate_input(evidence)
    with pytest.raises(policy.PromotionRefused, match="proof content"):
        policy.verify_plan(client, plan)


def test_producer_cli_writes_the_small_exact_proof(authority, tmp_path, monkeypatch):
    original = _input()
    original.update(source_commit=TESTED, test_workflow_run=100)
    monkeypatch.setattr(promote, "identity", lambda root: {"source_commit": TESTED, "source_tree": TREE})
    for key, value in {"GITHUB_REPOSITORY": policy.REPOSITORY, "GITHUB_RUN_ID": "100", "GITHUB_RUN_ATTEMPT": "1"}.items():
        monkeypatch.setenv(key, value)
    source, target = tmp_path / "input.json", tmp_path / "proof.json"
    source.write_text(json.dumps(original))
    assert promote.main(["producer", "--input", str(source), "--output", str(target),
                         "--artifact-id", "200", "--artifact-digest", "sha256:" + "8" * 64]) == 0
    proof = json.loads(target.read_text())
    assert proof["attempt"] == 1 and proof["runtime_artifact"]["id"] == 200
    assert proof["input_sha256"] == policy.input_digest(original)
    assert target.stat().st_size < 1024


@pytest.mark.parametrize("raw", [b'{"run":1,"run":2}', b'{"x":NaN}', b'{"x":1e999}', b'{"x":1.5}', b'[]', b'null'])
def test_producer_proof_parser_rejects_ambiguous_json(raw):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr("proof.json", raw)
    data = stream.getvalue()
    class Client:
        def bytes(self, url):
            return data
    item = {"id": 203, "digest": "sha256:" + hashlib.sha256(data).hexdigest()}
    with pytest.raises(policy.PromotionRefused):
        policy.read_proof(Client(), item)
