"""Hosted authentication, inventory and runtime admission only; no replay."""
from __future__ import annotations

import argparse
import base64
import hashlib
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import subprocess
import urllib.request

from probe import check_context, admitted_output
from seal import decrypt, extract_verified, MAX_ASSET

PROTOCOL = "a4591ac1a8ca6d927d4a5452c8bfce766e910fc75d33dbbd48d3f0fd8adb1e52"
IMAGE = "sha256:97b69cf2f8487785e55a4ecafe2497829d021a9d58b5e4af001e8dcc6a981309"
RELEASE = "research-capital-risk-inputs-20261027"
SECRET = "CAPITAL_RISK_RESEARCH_KEY_20261027"


def validate_request(request):
    if (set(request) != {"schema", "request_id", "stage", "protocol_sha256", "release",
                         "expected_image", "manifest_sha256", "assets"}
            or request["schema"] != "research.capital-risk-stage-request/1"
            or request["stage"] != "stage" or request["request_id"] != "stage-001"
            or request["protocol_sha256"] != PROTOCOL or request["expected_image"] != IMAGE
            or request["release"] != RELEASE
            or not re.fullmatch(r"[a-f0-9]{64}", request["manifest_sha256"])
            or set(request["assets"]) != {"data.tar.crseal", "runtime.tar.crseal"}):
        raise ValueError("REFUSED_STAGE_REQUEST")
    for name,value in request["assets"].items():
        if (set(value) not in ({"sha256", "bytes"}, {"sha256", "bytes", "parts"})
                or not isinstance(value["bytes"], int)
                or not 36 < value["bytes"] <= MAX_ASSET
                or not re.fullmatch(r"[a-f0-9]{64}", value["sha256"])):
            raise ValueError("REFUSED_ASSET_COMMITMENT")
        if "parts" in value:
            parts=value["parts"]
            if not isinstance(parts,list) or not 1<=len(parts)<=32:
                raise ValueError("REFUSED_PART_COUNT")
            for index,part in enumerate(parts):
                if (set(part)!={"name","sha256","bytes"}
                        or part["name"]!=f"{name}.part-{index:04d}"
                        or not isinstance(part["bytes"],int) or not 0<part["bytes"]<=64*1024**2
                        or not re.fullmatch(r"[a-f0-9]{64}",part["sha256"])):
                    raise ValueError("REFUSED_PART_COMMITMENT")
            if sum(p["bytes"] for p in parts)!=value["bytes"]:
                raise ValueError("REFUSED_PART_TOTAL")


def acquire(name, spec, root):
    path = root / name
    parts=spec.get("parts",[dict(name=name,**spec)])
    with path.open("xb") as output:
        for part in parts:
            url = f"https://github.com/flabber1835/stocker/releases/download/{RELEASE}/{part['name']}"
            with urllib.request.urlopen(url, timeout=60) as response:
                if response.headers.get("Content-Length") and int(response.headers["Content-Length"]) != part["bytes"]:
                    raise ValueError("REFUSED_DOWNLOAD_LENGTH")
                total,digest = 0,hashlib.sha256()
                while block := response.read(1024*1024):
                    total += len(block)
                    if total > part["bytes"]: raise ValueError("REFUSED_DOWNLOAD_SIZE")
                    output.write(block);digest.update(block)
                if total != part["bytes"] or digest.hexdigest()!=part["sha256"]:
                    raise ValueError("REFUSED_DOWNLOAD_PART_OR_LENGTH")
    return path


def verify_runtime(root, manifest):
    runtime = root / "runtime.tar"
    with runtime.open("rb") as stream:
        loaded = subprocess.run(["docker", "load", "--quiet"], stdin=stream,
                                capture_output=True, timeout=120, check=True)
    inspected = subprocess.run(["docker", "image", "inspect", IMAGE],
                               capture_output=True, timeout=20, check=True)
    image = json.loads(inspected.stdout)[0]
    if image["Id"] != IMAGE or image["Os"] != "linux" or image["Architecture"] != "amd64":
        raise ValueError("REFUSED_RUNTIME_IDENTITY")
    # Only immutable source verification. No module with strategy entrypoints is invoked.
    program = """import hashlib,json,pathlib
m=json.loads(pathlib.Path('/transfer-manifest.json').read_bytes())
expected={n[len('source-fixed/'):]:v for n,v in m['members'].items() if n.startswith('source-fixed/')}
assert len(expected)==514
actual={p.relative_to('/fixed').as_posix() for p in pathlib.Path('/fixed').rglob('*') if p.is_file()}
assert actual==set(expected)
for n,s in expected.items():
 p=pathlib.Path('/fixed')/n
 assert p.stat().st_size==s['bytes'] and hashlib.sha256(p.read_bytes()).hexdigest()==s['sha256']
print('VERIFIED_FROZEN_SOURCE_514')
"""
    report = root / "transfer-manifest.json"
    report.write_text(json.dumps(manifest))
    command = ["docker", "run", "--rm", "--network", "none", "--memory", "512m",
               "--memory-swap", "512m", "--cpus", "1", "--pids-limit", "32",
               "--read-only", "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
               "--mount", f"type=bind,source={report},target=/transfer-manifest.json,readonly",
               "--entrypoint", "python", IMAGE, "-B", "-c", program]
    verified = subprocess.run(command, capture_output=True, timeout=60, check=True)
    if verified.stdout.strip() != b"VERIFIED_FROZEN_SOURCE_514":
        raise ValueError("REFUSED_SOURCE_PROOF")


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--request",required=True,type=Path)
    parser.add_argument("--output",required=True,type=Path)
    args=parser.parse_args()
    check_context(os.environ)
    request=json.loads(args.request.read_bytes());validate_request(request)
    output=admitted_output(Path(os.environ["GITHUB_WORKSPACE"]),args.output)
    root=Path(os.environ["RUNNER_TEMP"])/"capital-risk-stage-001"
    root.mkdir(mode=0o700,exist_ok=False)
    encoded=os.environ.pop(SECRET,"")
    key=base64.b64decode(encoded,validate=True)
    if len(key)!=32: raise ValueError("REFUSED_RESEARCH_KEY")
    encoded=None
    for name,spec in request["assets"].items():
        asset=acquire(name,spec,root)
        decrypt(asset,root/name.removesuffix(".crseal"),key,spec["sha256"])
    key=None
    manifest=extract_verified(root/"data.tar",root/"inputs",request["manifest_sha256"])
    if (manifest["protocol_sha256"]!=PROTOCOL or manifest["expected_image"]!=IMAGE
            or manifest["source_files"]!=514):
        raise ValueError("REFUSED_TRANSFER_LINEAGE")
    verify_runtime(root,manifest)
    receipt=dict(schema="research.capital-risk-staging/1",status="STAGING_PASSED",
                 utc=datetime.now(timezone.utc).isoformat(),source_commit=os.environ["GITHUB_SHA"],
                 run_id=os.environ["GITHUB_RUN_ID"],protocol_sha256=PROTOCOL,
                 manifest_sha256=request["manifest_sha256"],runtime_image=IMAGE,
                 source_files_verified=514,members_verified=len(manifest["members"]),
                 bytes_verified=sum(v["bytes"] for v in manifest["members"].values()),
                 authenticated_before_parsing=True,offline_image_source_verified=True,
                 replay_started=False,production_contacted=False)
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(receipt,indent=2)+"\n")
    print(json.dumps(receipt))


if __name__=="__main__":
    main()
