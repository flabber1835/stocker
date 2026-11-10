"""DATA-only transport and launcher for the fixed-decision hosted pilot."""
from __future__ import annotations

import argparse
import base64
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile
import time
import zipfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
LEGACY = "0bc38753ac1f85b31eb95f560720e6b037e892c5"
BASE = "1e7f4b181fbcb998b3086833ab813c21b1c2ca8e"
BRANCH = "refs/heads/codex/core-sentinel-reconciliation"
SECRET = "CAPITAL_RISK_RESEARCH_KEY_20261027"
ARCHIVE_IMAGE = "sha256:97b69cf2f8487785e55a4ecafe2497829d021a9d58b5e4af001e8dcc6a981309"
IMAGE = "sha256:1b449754a48473e4737fc34f3f51ae0b4226d5e84540dea54115d4693142ed9d"
DOC = "docs/core-sentinel-reconciliation-20261109.md"
WORKFLOW = ".github/workflows/core-sentinel-reconciliation.yml"
REQUEST = HERE / "request.json"
FORBIDDEN = {"ALPACA_API_KEY", "ALPACA_SECRET_KEY", "APCA_API_KEY_ID",
             "APCA_API_SECRET_KEY", "DATABASE_URL", "PGPASSWORD",
             "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "OPENAI_API_KEY"}


def need(value, code):
    if not value:
        raise ValueError(code)


def sha(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        while block := stream.read(1024**2):
            h.update(block)
    return h.hexdigest()


def expected_request():
    files = [p for directory in (ROOT / "sentinel", ROOT / "shared", HERE)
             for p in directory.rglob("*.py") if "__pycache__" not in p.parts]
    files += [ROOT / DOC, ROOT / WORKFLOW, HERE / "input-transfer.json"]
    return dict(schema="research.fixed-account-reconciliation-request/1",
                verified_main=BASE, legacy_commit=LEGACY, generation=3,
                prior_stopped_unadmitted_runs=[42727061316, 42727738185],
                harness_correction="SEPARATE_RESEARCH_SIZING_METADATA_AND_CANONICALIZE_UNFUNDED_BIL_ANCHOR",
                start="2018-01-02", end="2019-02-05", closes=275,
                arms=["S", "A", "Q", "P"], core_recomputed=False,
                production_contacted=False, source_files={
                    p.relative_to(ROOT).as_posix(): sha(p) for p in sorted(set(files))})


def context(env):
    required = dict(GITHUB_ACTIONS="true", GITHUB_REPOSITORY="flabber1835/stocker",
                    GITHUB_REPOSITORY_OWNER="flabber1835", GITHUB_ACTOR="flabber1835",
                    GITHUB_REF=BRANCH, GITHUB_REF_TYPE="branch", GITHUB_EVENT_NAME="push",
                    GITHUB_RUN_ATTEMPT="1", RUNNER_ENVIRONMENT="github-hosted",
                    RUNNER_OS="Linux", RUNNER_ARCH="X64", ImageOS="ubuntu24")
    need(all(env.get(k) == v for k, v in required.items()), "EXACT_HOSTED_CONTEXT")
    need(not any(env.get(k) for k in FORBIDDEN), "NO_PRODUCTION_CREDENTIALS")
    need(re.fullmatch("[a-f0-9]{40}", env.get("GITHUB_SHA", "")), "HEAD_IDENTITY")
    need(re.fullmatch("[1-9][0-9]*", env.get("GITHUB_RUN_ID", "")), "RUN_IDENTITY")
    need(os.name == "posix" and Path(env["RUNNER_TEMP"]).resolve() == Path("/home/runner/work/_temp"),
         "HOSTED_PATH")


def legacy_imports(path):
    path = path.resolve()
    result = subprocess.run(["git", "-C", str(path), "rev-parse", "HEAD"],
                            capture_output=True, text=True, check=True, timeout=20)
    need(result.stdout.strip() == LEGACY, "EXACT_LEGACY_COMMIT")
    result = subprocess.run(["git", "-C", str(path), "status", "--porcelain", "--untracked-files=no"],
                            capture_output=True, text=True, check=True, timeout=20)
    need(not result.stdout.strip(), "UNCHANGED_LEGACY_TREE")
    sys.path.insert(0, str(path / "research/capital_risk"))


def probe(legacy):
    need(json.loads(REQUEST.read_bytes()) == expected_request(), "EXACT_SOURCE_REQUEST")
    legacy_imports(legacy)
    import stage
    import system_campaign_financial_partial as partial
    from p00_recovery_watch_job import old_inspector
    from system_campaign_variants import build
    from alpaca_fit_job import stopped_run
    from runtime_identity import EXECUTION_IMAGE
    need(stage.IMAGE == ARCHIVE_IMAGE and EXECUTION_IMAGE == IMAGE
         and partial.completed_result("P00")["completed"] == 2156,
         "ORIGINAL_COMPLETED_AUTHORITY")
    return dict(status="DATA_IMPORT_AND_SOURCE_PROBE_PASSED", financial_execution=False)


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_bytes((json.dumps(value, sort_keys=True, indent=2) + "\n").encode())
    os.replace(temporary, path)


def stage_inputs(legacy, output):
    context(os.environ)
    probe(legacy)
    import stage
    from seal import decrypt, extract_verified
    key = base64.b64decode(os.environ.pop(SECRET, ""), validate=True)
    need(len(key) == 32, "TRANSFER_KEY")
    temp = Path(os.environ["RUNNER_TEMP"]) / "capital-risk-stage-001"
    temp.mkdir(mode=0o700, exist_ok=False)
    need(shutil.disk_usage(temp).free >= 12 * 1024**3, "STAGING_DISK_RESERVE")
    request = json.loads((legacy / "research/capital_risk/stage-request.json").read_bytes())
    stage.validate_request(request)
    for name, spec in request["assets"].items():
        asset = stage.acquire(name, spec, temp)
        decrypt(asset, temp / name.removesuffix(".crseal"), key, spec["sha256"])
    manifest = extract_verified(temp / "data.tar", temp / "inputs", request["manifest_sha256"])
    need(manifest["source_files"] == 514 and manifest["expected_image"] == ARCHIVE_IMAGE
         and manifest["protocol_sha256"] == stage.PROTOCOL, "FROZEN_INPUT_LINEAGE")
    portable = stage.verify_runtime(temp, manifest)
    transfer = json.loads((HERE / "input-transfer.json").read_bytes())
    need(set(transfer) == {"release", "name", "sha256", "bytes", "manifest_sha256"}
         and transfer["release"] == "research-capital-risk-inputs-20261027"
         and transfer["name"] == "persistent-share-bil-20261109-v2.tar.crseal"
         and 36 < transfer["bytes"] < 64 * 1024**2, "BIL_TRANSFER_SCOPE")
    cipher = temp / transfer["name"]
    with cipher.open("xb") as stream:
        subprocess.run(["gh", "release", "download", transfer["release"], "--repo",
                        "flabber1835/stocker", "--pattern", transfer["name"], "--output", "-"],
                       stdout=stream, check=True, timeout=120)
    need(cipher.stat().st_size == transfer["bytes"], "BIL_CIPHER_SIZE")
    plain = temp / "bil.tar"
    decrypt(cipher, plain, key, transfer["sha256"])
    key = None
    bil = extract_verified(plain, temp / "bil", transfer["manifest_sha256"])
    # pack_data uses this exact encoding; retain the authenticated first member
    # for the offline worker/reviewer, outside its own member inventory.
    manifest_raw = (json.dumps(bil, sort_keys=True, separators=(",", ":")) + "\n").encode()
    need(hashlib.sha256(manifest_raw).hexdigest() == transfer["manifest_sha256"], "BIL_CANONICAL_MANIFEST_ENCODING")
    (temp / "bil/manifest.json").write_bytes(manifest_raw)
    save(output, dict(status="STAGING_PASSED", head=os.environ["GITHUB_SHA"],
                      run_id=os.environ["GITHUB_RUN_ID"], request_sha256=sha(REQUEST),
                      authenticated_before_parsing=True, replay_started=False,
                      runtime_image=IMAGE, runtime_archive_sha256=portable["archive_sha256"],
                      frozen_manifest_sha256=request["manifest_sha256"],
                      bil_manifest_sha256=transfer["manifest_sha256"], bil_members=len(bil["members"]),
                      production_contacted=False))


def admit_p00(legacy, temp, key):
    """New-context transport reader; existing old-branch guards remain unchanged."""
    import system_campaign_financial_partial as partial
    from p00_recovery_watch_job import old_inspector
    from seal import decrypt, safe_name
    entry = json.loads((legacy / "research/capital_risk" / partial.ROOTS).read_bytes())["completed_financial_roots"]["P00"]
    need(entry["admission_sha256"] == "65637d23029e0817822c169e7d424e00cd75a01703cb22a6aeb1b3f69b390f83",
         "P00_COMPLETED_ROOT")
    partial.authorized_completion(entry, "P00")
    spec = entry["transport"]
    archive = temp / "p00.zip"
    with archive.open("xb") as stream:
        subprocess.run(["gh", "api", f"repos/flabber1835/stocker/actions/artifacts/{spec['artifact_id']}/zip"],
                       stdout=stream, check=True, timeout=180)
    need(archive.stat().st_size == spec["zip_bytes"] and sha(archive) == spec["zip_sha256"], "P00_EXACT_ZIP")
    asset = spec["encrypted_output"]
    cipher = temp / "p00.crseal"
    with zipfile.ZipFile(archive) as z:
        need(hashlib.sha256(z.read(spec["receipt_name"])).hexdigest() == spec["receipt_sha256"], "P00_RECEIPT")
        need(z.getinfo(asset["name"]).file_size == asset["bytes"], "P00_CIPHER_SIZE")
        with z.open(asset["name"]) as src, cipher.open("xb") as dst:
            shutil.copyfileobj(src, dst)
    plain = temp / "p00.tar.gz"
    decrypt(cipher, plain, key, asset["sha256"])
    dest = temp / "p00"
    dest.mkdir(mode=0o700)
    with tarfile.open(plain, "r:gz") as tar:
        first = tar.next()
        need(first.name == "manifest.json" and first.isfile() and first.size < 2 * 1024**2, "P00_MANIFEST")
        raw = tar.extractfile(first).read()
        need(hashlib.sha256(raw).hexdigest() == asset["manifest_sha256"], "P00_MANIFEST_HASH")
        manifest = json.loads(raw)
        need(manifest["head"] == spec["head"] and int(manifest["run_id"]) == spec["run_id"]
             and manifest["request_sha256"] == spec["request_sha256"] and manifest["arm"] == "P00", "P00_MANIFEST_BINDING")
        inventory = manifest["members"]
        need(len(inventory) == spec["manifest"]["member_count"]
             and sum(v["bytes"] for v in inventory.values()) == spec["manifest"]["raw_member_bytes"] < 1024**3,
             "P00_INVENTORY_BOUND")
        seen = set()
        while item := tar.next():
            safe_name(item.name)
            need(item.isfile() and item.name in inventory and item.name not in seen, "P00_MEMBER")
            seen.add(item.name)
            expected = inventory[item.name]
            need(item.size == expected["bytes"], "P00_MEMBER_SIZE")
            target = dest / item.name
            need(target.resolve().is_relative_to(dest.resolve()), "P00_MEMBER_PATH")
            target.parent.mkdir(parents=True, exist_ok=True)
            with tar.extractfile(item) as src, target.open("xb") as dst:
                shutil.copyfileobj(src, dst)
            need(sha(target) == expected["sha256"], "P00_MEMBER_HASH")
        need(seen == set(inventory), "P00_COMPLETE_INVENTORY")
    for name, expected in spec["inspections"].items():
        partial.archived_inspection(spec, expected, json.loads((dest / name).read_bytes()), old_inspector())
    need(sha(dest / spec["selected_checkpoint"]) == spec["selected_file"]["sha256"], "P00_CHECKPOINT_HASH")
    checkpoint = json.loads(gzip.decompress((dest / spec["selected_checkpoint"]).read_bytes()))
    need(checkpoint["sha256"] == spec["outer_sha256"] and checkpoint["journals"] == spec["journals"]
         and checkpoint["run"]["state_sha256"] == spec["state_sha256"], "P00_CHECKPOINT_BINDING")
    for name, commitment in checkpoint["journals"].items():
        with (dest / f"book/{name}.jsonl").open("rb") as stream:
            raw = stream.read(commitment["bytes"])
        need(len(raw) == commitment["bytes"] and hashlib.sha256(raw).hexdigest() == commitment["prefix_sha256"], "P00_JOURNAL_PREFIX")
    need(sha(dest / "source-bindings.json") == spec["source_binding_sha256"], "P00_SOURCE_BINDING")
    return dest


def command(name, role, source, legacy, frozen, p00, inputs, output, work=None):
    argv = ["docker", "run", "-d", "--name", name, "--pull", "never", "--network", "none",
            "--read-only", "--memory", "8g", "--memory-swap", "8g", "--cpus", "2", "--pids-limit", "64",
            "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
            "--tmpfs", "/tmp:rw,noexec,nosuid,size=128m", "--user", f"{os.getuid()}:{os.getgid()}",
            "--label", "research.study=fixed-account-reconciliation-20261109", "--label", "research.role=" + role,
            "-w", "/current", "-e", "PERSISTENT_RECONCILIATION_HOSTED=1", "-e", "FULL_SYSTEM_HOSTED=1",
            "-e", "OWNED_GRID_HOSTED=1", "-e", "HOLDING_QUAL_HOSTED=1", "-e", "OPENBLAS_NUM_THREADS=1", "-e", "OMP_NUM_THREADS=1",
            "-e", "PYTHONPATH=/current:/current/shared:/legacy/research/capital_risk:/variant:/variant/shared"]
    mounts = {"/variant": source, "/legacy": legacy, "/current": ROOT, "/frozen": frozen, "/p00": p00, "/input": inputs}
    if work is not None:
        mounts["/work"] = work
    for target, origin in mounts.items():
        argv += ["--mount", f"type=bind,source={origin},target={target},readonly"]
    argv += ["--mount", f"type=bind,source={output},target=/out", "--entrypoint", "python", IMAGE,
             "-B", "-u", f"/current/research/persistent_share_reconciliation/{role}.py",
             "--source", "/variant", "--legacy", "/legacy", "--current", "/current",
             "--p00", "/p00", "--input", "/input", "--output", "/out/book" if role == "worker" else "/out/review"]
    if work is not None:
        argv += ["--work", "/work/book"]
    return argv


def inspect(name, identity=None):
    need(re.fullmatch(r"persistent-reconciliation-(worker|review)-[1-9][0-9]*-1", name), "CONTAINER_NAME")
    value = json.loads(subprocess.run(["docker", "inspect", name], capture_output=True, check=True, timeout=20).stdout)[0]
    h, c = value["HostConfig"], value["Config"]
    role = "review" if "-review-" in name else "worker"
    mounts = {m["Destination"]: m for m in value["Mounts"] if m["Type"] == "bind"}
    expected = {"/variant", "/legacy", "/current", "/frozen", "/p00", "/input", "/out"} | ({"/work"} if role == "review" else set())
    need(value["Name"] == "/" + name and value["Image"] == IMAGE
         and (identity is None or value["Id"] == identity), "ACTUAL_CONTAINER_IDENTITY")
    need(h["NetworkMode"] == "none" and h["ReadonlyRootfs"] and h["Memory"] == h["MemorySwap"] == 8 * 1024**3
         and h["NanoCpus"] == 2_000_000_000 and h["PidsLimit"] == 64 and h["CapDrop"] == ["ALL"]
         and any(s.startswith("no-new-privileges") for s in h["SecurityOpt"]), "ACTUAL_CONTAINER_FENCES")
    need(set(mounts) == expected and mounts["/out"]["RW"]
         and all(not m["RW"] for k, m in mounts.items() if k != "/out")
         and c["WorkingDir"] == "/current" and c["User"] == f"{os.getuid()}:{os.getgid()}"
         and c["Labels"].get("research.study") == "fixed-account-reconciliation-20261109"
         and c["Labels"].get("research.role") == role, "ACTUAL_CONTAINER_MOUNTS")
    need(not any(k in FORBIDDEN | {SECRET, "GH_TOKEN", "GITHUB_TOKEN"} and v
                 for k, _, v in (s.partition("=") for s in c["Env"])), "ACTUAL_CONTAINER_CREDENTIALS")
    expected_cmd = ["-B", "-u", f"/current/research/persistent_share_reconciliation/{role}.py",
                    "--source", "/variant", "--legacy", "/legacy", "--current", "/current", "--p00", "/p00",
                    "--input", "/input", "--output", "/out/book" if role == "worker" else "/out/review"]
    if role == "review":
        expected_cmd += ["--work", "/work/book"]
    need(c["Entrypoint"] == ["python"] and c["Cmd"] == expected_cmd, "ACTUAL_EXACT_ENTRYPOINT")
    return value


def run(legacy, staging, output):
    context(os.environ)
    probe(legacy)
    from alpaca_fit_job import stopped_run, StopUnknown
    from system_campaign_variants import build
    from full_system_trials_job import seal
    proof = json.loads(staging.read_bytes())
    need(proof["status"] == "STAGING_PASSED" and proof["head"] == os.environ["GITHUB_SHA"]
         and proof["run_id"] == os.environ["GITHUB_RUN_ID"] and proof["request_sha256"] == sha(REQUEST)
         and proof["authenticated_before_parsing"] and not proof["replay_started"], "SAME_RUN_STAGING")
    key = base64.b64decode(os.environ.pop(SECRET, ""), validate=True)
    need(len(key) == 32, "OUTPUT_KEY")
    temp = Path(os.environ["RUNNER_TEMP"]) / "persistent-reconciliation-001"
    temp.mkdir(mode=0o700)
    account_output = temp / "output"
    account_output.mkdir()
    receipt = dict(schema="research.fixed-account-reconciliation-receipt/1", status="INPUT_ADMISSION_PENDING",
                   head=os.environ["GITHUB_SHA"], run_id=os.environ["GITHUB_RUN_ID"], request_sha256=sha(REQUEST),
                   production_contacted=False, core_recomputed=False, performance_admitted=False)
    save(output, receipt)
    known, launched, started = False, False, time.monotonic()
    try:
        p00 = admit_p00(legacy, temp, key)
        os.environ.pop("GH_TOKEN", None)
        frozen = Path(os.environ["RUNNER_TEMP"]) / "capital-risk-stage-001/inputs"
        binding = json.loads((p00 / "source-bindings.json").read_bytes())
        source = temp / "source"
        need(build(frozen / "source-fixed", source, binding["parameters"]) == binding, "EXACT_ORIGINAL_SOURCE")
        (account_output / "request.json").write_bytes(REQUEST.read_bytes())
        name = "persistent-reconciliation-worker-" + os.environ["GITHUB_RUN_ID"] + "-1"
        receipt["status"] = "OFFLINE_WORKER_RUNNING"
        save(output, receipt)
        launched = True
        receipt["worker"] = stopped_run(command(name, "worker", source, legacy, frozen, p00,
                                               frozen.parent / "bil", account_output), name,
                                        account_output, deadline=900, inspector=inspect)
        known = True
        receipt["status"] = "STOPPED_WORKER_REVIEW_PENDING"
        save(output, receipt)
        if receipt["worker"]["exit_code"] == 0 and not receipt["worker"]["oom_killed"]:
            audit = temp / "review"
            audit.mkdir()
            name = "persistent-reconciliation-review-" + os.environ["GITHUB_RUN_ID"] + "-1"
            receipt["reviewer"] = stopped_run(command(name, "review", source, legacy, frozen, p00,
                                                     frozen.parent / "bil", audit, account_output),
                                              name, audit, deadline=900, inspector=inspect)
            shutil.copytree(audit, account_output / "independent-review-stop")
            if receipt["reviewer"]["exit_code"] == 0 and not receipt["reviewer"]["oom_killed"]:
                review = json.loads((audit / "review/independent-review.json").read_bytes())
                need(review["status"] == "FIXED_ACCOUNT_RECONCILIATION_REVIEW_PASSED", "ACTUAL_REVIEW_VERDICT")
                receipt["status"] = "REVIEWED_PENDING_INDEPENDENT_ARTIFACT_ADMISSION"
    except StopUnknown:
        receipt["status"] = "STOP_UNKNOWN_NO_PERFORMANCE_ADMISSION"
    except Exception as exc:
        receipt["status"] = "REFUSED_NO_PERFORMANCE_ADMISSION"
        receipt["error_type"] = type(exc).__name__
        receipt["failure_code"] = str(exc) if re.fullmatch(r"[A-Z][A-Z0-9_]{0,100}", str(exc)) else "PRIVATE_DIAGNOSTIC"
        # No launch attempt is also a known absence of a financial writer.
        known = known or not launched
        (account_output / "driver-failure.json").write_text(json.dumps(dict(type=type(exc).__name__, message=str(exc))) + "\n")
    finally:
        if known:
            receipt["encrypted_output"] = seal(account_output, output.parent / "persistent-reconciliation.tar.crseal",
                key, REQUEST, "P00", stage="multiyear-controller", protocol_sha256=sha(ROOT / DOC))
        key = None
        receipt["elapsed_seconds"] = time.monotonic() - started
        save(output, receipt)
    print(json.dumps(receipt))
    need(receipt["status"] == "REVIEWED_PENDING_INDEPENDENT_ARTIFACT_ADMISSION", "POSITIVE_STOP_AND_REVIEW_REQUIRED")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--legacy", type=Path, required=True)
    p.add_argument("--mode", choices=("prepare", "probe", "stage", "run"), required=True)
    p.add_argument("--output", type=Path)
    p.add_argument("--staging", type=Path)
    a = p.parse_args()
    if a.mode == "prepare":
        need(not REQUEST.exists(), "REQUEST_EXISTS")
        save(REQUEST, expected_request())
    elif a.mode == "probe":
        print(json.dumps(probe(a.legacy)))
    elif a.mode == "stage":
        stage_inputs(a.legacy, a.output)
    else:
        run(a.legacy, a.staging, a.output)


if __name__ == "__main__":
    main()
