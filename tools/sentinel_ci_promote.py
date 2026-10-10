#!/usr/bin/env python3
"""Select completed PR qualification and promote only tested-image metadata."""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import io
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import zipfile

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import sentinel_ci_promotion as policy
from scripts.sentinel_ci_certification_verify import GitHubReadClient, _json_bytes
from tools import sentinel_ci_certification_manifest as cert


def read(path):
    return _json_bytes(Path(path).read_bytes(), "CERT_PROMOTION_INPUT_INVALID", "promotion input")


def write(path, value):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_bytes(cert.canonical_bytes(value) + b"\n")


def run(argv, root):
    result = subprocess.run(argv, cwd=str(root), check=False, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, timeout=600)
    policy.require(result.returncode == 0, "promotion command failed: " + argv[0])
    return result.stdout


def identity(root):
    return {"source_commit": policy.git(run(["git", "rev-parse", "HEAD"], root).decode().strip()),
            "source_tree": policy.git(run(["git", "rev-parse", "HEAD^{tree}"], root).decode().strip())}


def artifact(client, run_id, name):
    matches = [x for x in policy.rows(client, "/repos/%s/actions/runs/%d/artifacts" %
               (policy.REPOSITORY, run_id), "artifacts") if x.get("name") == name]
    policy.require(len(matches) <= 1, "ambiguous retained artifact")
    if not matches or matches[0].get("expired") is True:
        return None
    value = matches[0]
    return {"id": policy.positive(value.get("id")), "name": name,
            "digest": policy.digest(value.get("digest")), "run": run_id}


def checkout_proof(client, item):
    raw = client.bytes("https://api.github.com/repos/%s/actions/artifacts/%d/zip" %
                       (policy.REPOSITORY, item["id"]))
    policy.require(len(raw) <= 1024 * 1024 and
                   "sha256:" + hashlib.sha256(raw).hexdigest() == item["digest"],
                   "checkout artifact bytes differ")
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        policy.require(archive.namelist() == ["proof.json"] and
                       archive.getinfo("proof.json").file_size <= 65536, "checkout artifact schema differs")
        return _json_bytes(archive.read("proof.json"), "CERT_PROMOTION_INPUT_INVALID", "checkout proof")


def select(root, client, event, ref):
    source = identity(root)
    full = {"schema": policy.PLAN_SCHEMA, "mode": "full", **source}
    if event != "push" or ref != "refs/heads/main":
        return {**full, "reason": "not-main-push"}
    associated = client.array("/repos/%s/commits/%s/pulls?per_page=100" %
                              (policy.REPOSITORY, source["source_commit"]))
    policy.require(len(associated) < 100 and all(isinstance(x, dict) for x in associated),
                   "unbounded or malformed PR association")
    merged = [x for x in associated if x.get("merge_commit_sha") == source["source_commit"]
              and x.get("merged_at") is not None]
    if not merged:
        return {**full, "reason": "no-merged-pr"}
    policy.require(len(merged) == 1, "ambiguous merged PR")
    pr = client.json("/repos/%s/pulls/%d" % (policy.REPOSITORY, policy.positive(merged[0]["number"])))
    policy.require(isinstance(pr.get("head"), dict), "PR head is malformed")
    tested = policy.git(pr["head"].get("sha"))
    tested_tree = policy.tree(client, tested)
    if tested_tree != source["source_tree"]:
        return {**full, "reason": "merged-tree-changed"}
    plan = {"schema": policy.PLAN_SCHEMA, "mode": "promote", **source, "pr": pr["number"],
            "tested_commit": tested, "tested_tree": tested_tree, "workflows": [], "checkout_proofs": []}
    for path in policy.WORKFLOWS:
        runs = policy.rows(client, "/repos/%s/actions/workflows/%s/runs?head_sha=%s&event=pull_request" %
                           (policy.REPOSITORY, path.rsplit("/", 1)[-1], tested), "workflow_runs")
        if not runs:
            return {**full, "reason": "missing-pr-workflow"}
        latest = max(runs, key=lambda x: policy.positive(x.get("id")))
        if latest.get("status") != "completed" or latest.get("conclusion") != "success":
            return {**full, "reason": "pr-workflow-not-successful"}
        plan["workflows"].append({"path": path, "run": policy.positive(latest["id"]),
                                  "attempt": policy.positive(latest.get("run_attempt"))})
    safety = plan["workflows"][0]
    plan["artifact"] = artifact(client, safety["run"], "sentinel-tested-image-" + tested)
    if plan["artifact"] is None:
        return {**full, "reason": "missing-tested-image"}
    for index, role in ((1, "composition"), (2, "browser")):
        row = plan["workflows"][index]
        item = artifact(client, row["run"], "ci-checkout-proof-%s-%d" % (role, row["attempt"]))
        if item is None:
            return {**full, "reason": "missing-checkout-proof"}
        proof = checkout_proof(client, item)
        if proof.get("tree") != source["source_tree"]:
            return {**full, "reason": "harness-tested-different-tree"}
        plan["checkout_proofs"].append({"artifact": item, "proof": proof})
    policy.verify_plan(client, plan)
    return plan


def inspect(root, reference):
    raw = run(["docker", "image", "inspect", reference], root)
    value = _json_bytes(b'{"images":' + raw + b'}', "CERT_PROMOTION_INPUT_INVALID", "image inspection")["images"]
    policy.require(isinstance(value, list) and len(value) == 1, "image inspection is not singular")
    return policy.image_record(value[0])


def verify_archive(bundle, commit):
    expected = {"sentinel-runtime.tar", "COMMIT", "software-certification-input.json"}
    policy.require(set(x.name for x in bundle.iterdir()) == expected | {"SHA256SUMS"}
                   and all(x.is_file() and not x.is_symlink() for x in bundle.iterdir()),
                   "runtime artifact member inventory differs")
    lines = (bundle / "SHA256SUMS").read_text(encoding="ascii").splitlines()
    names = set()
    for line in lines:
        parts = line.split("  ")
        policy.require(len(parts) == 2 and parts[1] in expected and parts[1] not in names,
                       "runtime checksum inventory differs")
        policy.digest("sha256:" + parts[0])
        policy.require(cert.sha256_file(bundle / parts[1]) == parts[0], "runtime checksum differs")
        names.add(parts[1])
    policy.require(names == expected and (bundle / "COMMIT").read_bytes() == (commit + "\n").encode(),
                   "runtime artifact source differs")


def download_runtime(client, plan, output):
    policy.verify_plan(client, plan)
    item = plan["artifact"]
    raw = client.bytes("https://api.github.com/repos/%s/actions/artifacts/%d/zip" %
                       (policy.REPOSITORY, item["id"]))
    policy.require(len(raw) <= 1024 ** 3 and
                   "sha256:" + hashlib.sha256(raw).hexdigest() == item["digest"],
                   "tested runtime artifact bytes differ")
    expected = {"sentinel-runtime.tar", "COMMIT", "software-certification-input.json", "SHA256SUMS"}
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        entries = archive.infolist()
        policy.require(len(entries) == len(expected) and {x.filename for x in entries} == expected
                       and sum(x.file_size for x in entries) <= 2 * 1024 ** 3
                       and all(not x.is_dir() and not (x.flag_bits & 1) and
                               (x.external_attr >> 16) & 0o170000 != 0o120000 for x in entries),
                       "tested runtime ZIP member inventory differs")
        output.mkdir(parents=True, exist_ok=False)
        for entry in entries:
            with archive.open(entry) as source, (output / entry.filename).open("xb") as target:
                shutil.copyfileobj(source, target)
    verify_archive(output, plan["tested_commit"])


def promote_metadata(root, tested_ref, promoted_ref, tested_commit, merged_commit):
    policy.git(tested_commit)
    policy.git(merged_commit)
    # Caller-controlled references are Docker arguments, never shell fragments.
    policy.require(all(isinstance(x, str) and x and "\n" not in x and "\r" not in x and " " not in x
                       for x in (tested_ref, promoted_ref)), "promotion image reference differs")
    before = inspect(root, tested_ref)
    with tempfile.TemporaryDirectory(prefix="sentinel-metadata-promotion-") as temp:
        dockerfile = Path(temp) / "Dockerfile"
        dockerfile.write_text("FROM %s\nLABEL org.opencontainers.image.revision=%s\n"
                              "ENV SENTINEL_IMAGE_SOURCE_REVISION=%s\n" %
                              (tested_ref, merged_commit, merged_commit), encoding="ascii")
        run(["docker", "build", "--network", "none", "--pull=false", "-t", promoted_ref, temp], root)
    after = inspect(root, promoted_ref)
    policy.require(inspect(root, tested_ref) == before, "original image changed during promotion")
    policy.verify_images(before, after, tested_commit, merged_commit)
    run(["docker", "run", "--rm", "--network", "none", "--entrypoint", "python", promoted_ref,
         "-c", "import os,sentinel; assert os.environ['SENTINEL_IMAGE_SOURCE_REVISION']=='%s'" % merged_commit], root)
    return before, after


def promote(root, client, plan, bundle, output, run_id, attempt):
    policy.verify_plan(client, plan)
    policy.require(identity(root) == {x: plan[x] for x in ("source_commit", "source_tree")},
                   "promotion checkout differs")
    verify_archive(bundle, plan["tested_commit"])
    original = read(bundle / "software-certification-input.json")
    cert._validate_input(original)
    policy.require(original["source_commit"] == plan["tested_commit"]
                   and original["source_tree"] == plan["source_tree"]
                   and original["dependency_lock_hashes"] == cert._dependency_hashes(root)
                   and original["test_manifest_sha256"] == cert._test_manifest_hash(root)
                   and original["runtime_capability_sha256"] == cert.sha256_file(root / "deploy/sentinel-authorized-runtime-v1"),
                   "original qualification differs from exact checkout")
    run(["docker", "load", "--input", str(bundle / "sentinel-runtime.tar")], root)
    before = inspect(root, "sentinel:ci")
    policy.require(before["Id"] == original["runtime_image_id"], "loaded image was not qualified")
    _, after = promote_metadata(root, "sentinel:ci", "sentinel:promoted", plan["tested_commit"], plan["source_commit"])
    evidence = deepcopy(original)
    evidence.update(schema="sentinel.software-certification-input/3", source_commit=plan["source_commit"],
                    test_workflow_run=policy.positive(run_id), test_workflow_attempt=policy.positive(attempt),
                    runtime_image_id=after["Id"], qualification_reuse={"schema": policy.PROMOTION_SCHEMA,
                    "plan": plan, "original_input": original, "tested_image": before, "promoted_image": after})
    cert._validate_input(evidence)
    output.mkdir(parents=True, exist_ok=False)
    run(["docker", "tag", "sentinel:promoted", "sentinel:ci"], root)
    run(["docker", "save", "--output", str(output / "sentinel-runtime.tar"), "sentinel:ci"], root)
    (output / "COMMIT").write_bytes((plan["source_commit"] + "\n").encode())
    write(output / "software-certification-input.json", evidence)
    (output / "SHA256SUMS").write_text("".join(cert.sha256_file(output / name) + "  " + name + "\n"
                                      for name in sorted({"sentinel-runtime.tar", "COMMIT", "software-certification-input.json"})), encoding="ascii")
    return evidence


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("select", "verify", "download", "promote", "scope"))
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--plan", type=Path)
    parser.add_argument("--bundle", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--role", choices=("composition", "browser"))
    args = parser.parse_args(argv)
    client = GitHubReadClient(token=os.environ.get("GITHUB_TOKEN"))
    try:
        root = args.root.resolve()
        if args.command == "select":
            value = select(root, client, os.environ.get("GITHUB_EVENT_NAME"), os.environ.get("GITHUB_REF"))
            write(args.output, value)
            if os.environ.get("GITHUB_OUTPUT"):
                with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as stream:
                    stream.write("mode=%s\nrun=%s\nartifact=%s\n" % (value["mode"],
                                 value.get("artifact", {}).get("run", ""), value.get("artifact", {}).get("name", "")))
        elif args.command == "scope":
            policy.require(args.role is not None and os.environ.get("GITHUB_REPOSITORY") == policy.REPOSITORY,
                           "checkout scope authority differs")
            source = identity(root)
            write(args.output, {"repository": policy.REPOSITORY,
                "path": policy.WORKFLOWS[1 if args.role == "composition" else 2],
                "commit": source["source_commit"], "tree": source["source_tree"],
                "run": policy.positive(int(os.environ["GITHUB_RUN_ID"])),
                "attempt": policy.positive(int(os.environ["GITHUB_RUN_ATTEMPT"]))})
        elif args.command == "verify":
            plan = read(args.plan)
            policy.verify_plan(client, plan)
            policy.require(identity(root) == {x: plan[x] for x in ("source_commit", "source_tree")},
                           "reuse checkout differs")
            if os.environ.get("CI_NEEDS"):
                needs = _json_bytes(os.environ["CI_NEEDS"].encode(), "CERT_PROMOTION_INPUT_INVALID", "main dependencies")
                policy.verify_promotion_dependencies(needs)
            write(args.output, {"status": "REUSED", "plan": plan})
        elif args.command == "download":
            download_runtime(client, read(args.plan), args.output.resolve())
        else:
            promote(root, client, read(args.plan), args.bundle.resolve(), args.output.resolve(),
                    int(os.environ["GITHUB_RUN_ID"]), int(os.environ["GITHUB_RUN_ATTEMPT"]))
        return 0
    except (policy.PromotionRefused, cert.CertificationManifestRefused, OSError, ValueError,
            KeyError, TypeError, subprocess.TimeoutExpired, zipfile.BadZipFile) as exc:
        print("REFUSED: promotion [%s]" % type(exc).__name__, file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
