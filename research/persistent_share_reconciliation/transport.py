"""Local DATA-only authenticated input packaging and stopped-output admission."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import sys
import tarfile

from job import IMAGE, LEGACY, REQUEST, ROOT, DOC, expected_request, need, save, sha


def dependencies(legacy):
    sys.path.insert(0, str(legacy / "research/capital_risk"))
    from local_stage import dpapi, pack_data
    from seal import decrypt, safe_name
    return dpapi, pack_data, decrypt, safe_name


def pack(a):
    dpapi, pack_data, _, _ = dependencies(a.legacy)
    paths = {p.relative_to(a.input).as_posix(): p for p in sorted(a.input.rglob("*")) if p.is_file()}
    need(paths and not any(p.is_symlink() for p in a.input.rglob("*")), "INPUT_REGULAR_FILES")
    members = {name: dict(bytes=p.stat().st_size, sha256=sha(p)) for name, p in paths.items()}
    need(len(members) < 1000 and sum(v["bytes"] for v in members.values()) < 64 * 1024**2, "INPUT_BOUND")
    manifest = dict(schema="research.capital-risk-inputs/1", purpose="FIXED_ACCOUNT_RECONCILIATION_BIL",
                    protocol_sha256=sha(ROOT / DOC), legacy_commit=LEGACY, members=members)
    a.output.mkdir(parents=True, exist_ok=True)
    key = dpapi(a.key.read_bytes(), unprotect=True)
    cipher = a.output / "persistent-share-bil-20261109-v2.tar.crseal"
    manifest_sha = pack_data(cipher, key, paths, manifest)
    key = None
    transfer = dict(release="research-capital-risk-inputs-20261027", name=cipher.name,
                    bytes=cipher.stat().st_size, sha256=sha(cipher), manifest_sha256=manifest_sha)
    save(ROOT / "research/persistent_share_reconciliation/input-transfer.json", transfer)
    save(a.output / "input-inventory.json", manifest)
    print(json.dumps(dict(status="ENCRYPTED_DATA_INPUT_PACKAGED", **transfer)))


def stopped(value, role, run_id):
    h, c, state = value["HostConfig"], value["Config"], value["State"]
    need(value["Name"] == f"/persistent-reconciliation-{role}-{run_id}-1"
         and value["Image"] == IMAGE and state["Running"] is False and state["OOMKilled"] is False
         and state["ExitCode"] == 0 and re.fullmatch("[a-f0-9]{64}", value["Id"]), "POSITIVE_STOPPED_IDENTITY")
    need(h["NetworkMode"] == "none" and h["ReadonlyRootfs"] and h["Memory"] == h["MemorySwap"] == 8 * 1024**3
         and h["NanoCpus"] == 2_000_000_000 and h["PidsLimit"] == 64 and h["CapDrop"] == ["ALL"]
         and any(s.startswith("no-new-privileges") for s in h["SecurityOpt"]), "ARCHIVED_FENCES")
    mounts = {m["Destination"]: m for m in value["Mounts"] if m["Type"] == "bind"}
    need(set(mounts) == ({"/variant", "/legacy", "/current", "/frozen", "/p00", "/input", "/out"}
                         | ({"/work"} if role == "review" else set()))
         and mounts["/out"]["RW"] and all(not m["RW"] for k, m in mounts.items() if k != "/out"), "ARCHIVED_MOUNTS")
    command = ["-B", "-u", f"/current/research/persistent_share_reconciliation/{role}.py",
               "--source", "/variant", "--legacy", "/legacy", "--current", "/current", "--p00", "/p00",
               "--input", "/input", "--output", "/out/book" if role == "worker" else "/out/review"]
    if role == "review":
        command += ["--work", "/work/book"]
    need(c["Labels"].get("research.study") == "fixed-account-reconciliation-20261109"
         and c["Labels"].get("research.role") == role and c["Entrypoint"] == ["python"]
         and c["Cmd"] == command and c["WorkingDir"] == "/current"
         and re.fullmatch(r"[1-9][0-9]*:[1-9][0-9]*", c["User"]), "ARCHIVED_ENTRYPOINT")
    from job import FORBIDDEN, SECRET
    need(not any(k in FORBIDDEN | {SECRET, "GH_TOKEN", "GITHUB_TOKEN"} and v
                 for k, _, v in (s.partition("=") for s in c["Env"])), "ARCHIVED_CREDENTIALS")


def admit(a):
    dpapi, _, decrypt, safe_name = dependencies(a.legacy)
    need(json.loads(REQUEST.read_bytes()) == expected_request(), "UNCHANGED_REVIEWED_SOURCE_REQUEST")
    receipt = json.loads(a.receipt.read_bytes())
    need(receipt["status"] == "REVIEWED_PENDING_INDEPENDENT_ARTIFACT_ADMISSION"
         and receipt["head"] == a.head and receipt["run_id"] == a.run_id
         and receipt["request_sha256"] == sha(REQUEST) and not receipt["production_contacted"]
         and not receipt["core_recomputed"], "EXACT_OUTPUT_RECEIPT")
    asset = receipt["encrypted_output"]
    need(a.cipher.name == asset["name"] and a.cipher.stat().st_size == asset["bytes"], "OUTPUT_CIPHER_SCOPE")
    key = dpapi(a.key.read_bytes(), unprotect=True)
    plain = a.output.parent / "authenticated-output.tar.gz"
    decrypt(a.cipher, plain, key, asset["sha256"])
    key = None
    a.output.mkdir(mode=0o700, exist_ok=False)
    with tarfile.open(plain, "r:gz") as tar:
        first = tar.next()
        need(first.name == "manifest.json" and first.isfile() and first.size < 2 * 1024**2, "OUTPUT_MANIFEST")
        raw = tar.extractfile(first).read()
        need(hashlib.sha256(raw).hexdigest() == asset["manifest_sha256"], "OUTPUT_MANIFEST_HASH")
        manifest = json.loads(raw)
        need(manifest["schema"] == "research.full-system-output/1"
             and manifest["stage"] == "multiyear-controller" and manifest["arm"] == "P00"
             and manifest["compression"] == "TAR_GZIP_V1"
             and manifest["head"] == a.head and manifest["run_id"] == a.run_id
             and manifest["request_sha256"] == sha(REQUEST) and manifest["protocol_sha256"] == sha(ROOT / DOC), "OUTPUT_MANIFEST_BINDING")
        members = manifest["members"]
        need(len(members) < 5000 and sum(v["bytes"] for v in members.values()) <= 1024**3, "OUTPUT_INVENTORY_BOUND")
        seen = set()
        while item := tar.next():
            safe_name(item.name)
            need(item.isfile() and item.name in members and item.name not in seen, "OUTPUT_MEMBER")
            seen.add(item.name)
            spec = members[item.name]
            need(item.size == spec["bytes"], "OUTPUT_MEMBER_SIZE")
            path = a.output / item.name
            need(path.resolve().is_relative_to(a.output.resolve()), "OUTPUT_CONFINED_PATH")
            path.parent.mkdir(parents=True, exist_ok=True)
            with tar.extractfile(item) as src, path.open("xb") as dst:
                shutil.copyfileobj(src, dst)
            need(sha(path) == spec["sha256"], "OUTPUT_MEMBER_HASH")
        need(seen == set(members), "OUTPUT_FULL_INVENTORY")
    need(sha(a.output / "request.json") == sha(REQUEST), "PRESERVED_EXACT_REQUEST")
    stopped(json.loads((a.output / "worker-inspect.json").read_bytes()), "worker", a.run_id)
    stopped(json.loads((a.output / "independent-review-stop/worker-inspect.json").read_bytes()), "review", a.run_id)
    review = json.loads((a.output / "independent-review-stop/review/independent-review.json").read_bytes())
    need(review["status"] == "FIXED_ACCOUNT_RECONCILIATION_REVIEW_PASSED", "INDEPENDENT_REVIEW_VERDICT")
    save(a.output.parent / "verification.json", dict(status="FIXED_PILOT_AUTHENTICATED_AND_INDEPENDENTLY_REVIEWED",
        performance_admitted=True, head=a.head, run_id=a.run_id, request_sha256=sha(REQUEST),
        output_manifest_sha256=asset["manifest_sha256"], members_verified=len(members),
        production_contacted=False, core_recomputed=False))
    print("FIXED_PILOT_AUTHENTICATED_AND_INDEPENDENTLY_REVIEWED")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--mode", choices=("pack", "admit"), required=True)
    for name in ("legacy", "key", "input", "output", "receipt", "cipher"):
        p.add_argument("--" + name, type=Path, required=name in ("legacy", "key", "output"))
    p.add_argument("--head")
    p.add_argument("--run-id")
    args = p.parse_args()
    pack(args) if args.mode == "pack" else admit(args)
