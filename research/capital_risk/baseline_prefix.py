"""Hosted orchestration of one fresh, bounded canonical prefix, never PAPER."""
from __future__ import annotations

import argparse
import base64
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tarfile

from probe import check_context, admitted_output, FORBIDDEN_CREDENTIALS, memory_bytes
from seal import EncryptWriter, sha256_file
from stage import IMAGE, PROTOCOL, SECRET

POLICY="wealth-core-v5-zero-share-fixed-2008-v1"


class UnprovenStopped(RuntimeError):
    pass


def validate_request(request):
    expected=dict(schema="research.capital-risk-baseline-prefix-request/1",request_id="baseline-prefix-001",
                  stage="baseline-prefix",arm="B",protocol_sha256=PROTOCOL,transitions=32)
    if request != expected: raise ValueError("REFUSED_BASELINE_PREFIX_REQUEST")


def launch_arguments(name, frozen, output, driver, *, review=False):
    if not re.fullmatch(r"capital-risk-b-prefix-[0-9]+-[0-9]+(?:-review)?",name):
        raise ValueError("REFUSED_PRIVATE_WORKER_NAME")
    args=["docker","run","--name",name,"--network","none","--memory","2g",
          "--memory-swap","2g","--cpus","1","--pids-limit","64","--read-only",
          "--cap-drop","ALL","--security-opt","no-new-privileges",
          "--tmpfs","/tmp:rw,noexec,nosuid,size=64m","--user",f"{os.getuid()}:{os.getgid()}",
          "--label","research.experiment=capital-risk-20261027","--label","research.arm=B",
          "--label","research.stage=baseline-prefix","-w","/fixed",
          "-e","PYTHONPATH=/fixed:/fixed/shared","-e","OPENBLAS_NUM_THREADS=1",
          "-e","OMP_NUM_THREADS=1","--mount",f"type=bind,source={frozen},target=/frozen,readonly",
          "--mount",f"type=bind,source={output},target=/out",
          "--mount",f"type=bind,source={driver},target=/driver,readonly",
          "--entrypoint","python",IMAGE,"-B","-u"]
    if review:
        args += ["/driver/verify_prefix.py","--actual","/out/run-001",
                 "--expected","/frozen/baseline-comparison","--output","/out/prefix-review.json"]
    else:
        args += ["-m","research.pooled_vacancy_funding.backtest","--policy",POLICY,
                 "--bundle","/frozen/bundle","--archive","/frozen/archive/corpus.zip",
                 "--previous","/frozen/references/owned55",
                 "--compact","/frozen/references/compact/champion-daily.csv",
                 "--output","/out/run-001","--max-transitions","32"]
    return args


def identity_inspect(name, identity=None):
    value=subprocess.run(["docker","inspect",name],capture_output=True,check=True,timeout=20)
    item=json.loads(value.stdout)[0]
    labels=item["Config"]["Labels"]
    if (item["Name"]!="/"+name or item["Image"]!=IMAGE or identity is not None and item["Id"]!=identity
            or labels.get("research.experiment")!="capital-risk-20261027"
            or labels.get("research.arm")!="B" or labels.get("research.stage")!="baseline-prefix"):
        raise ValueError("REFUSED_WORKER_IDENTITY")
    return item


def fenced_inspect(name):
    item=identity_inspect(name)
    if (item["HostConfig"]["NetworkMode"]!="none"
            or not item["HostConfig"]["ReadonlyRootfs"]
            or item["HostConfig"]["Memory"]!=2*1024**3
            or item["HostConfig"]["MemorySwap"]!=2*1024**3
            or item["HostConfig"]["NanoCpus"]!=1000000000
            or item["HostConfig"]["PidsLimit"]!=64
            or item["HostConfig"]["CapDrop"]!=["ALL"]
            or not any(s.startswith("no-new-privileges") for s in item["HostConfig"]["SecurityOpt"])):
        raise ValueError("REFUSED_WORKER_FENCE")
    mounts={m["Destination"]:m for m in item["Mounts"] if m["Type"]=="bind"}
    if (set(mounts)!={"/frozen","/out","/driver"} or mounts["/frozen"]["RW"]
            or mounts["/driver"]["RW"] or not mounts["/out"]["RW"]
            or item["Config"]["User"]!=f"{os.getuid()}:{os.getgid()}"):
        raise ValueError("REFUSED_WORKER_MOUNTS_OR_USER")
    forbidden=set(FORBIDDEN_CREDENTIALS)|{SECRET,"GITHUB_TOKEN","GH_TOKEN"}
    if any(v.partition("=")[0] in forbidden and v.partition("=")[2]
           for v in item["Config"].get("Env",[])):
        raise ValueError("REFUSED_WORKER_CREDENTIAL")
    return item


def run_worker(command, name, output):
    # Detached launch returns its exact ID. Bounded wait never leaves an admitted
    # container running after timeout; only this exact private identity may stop.
    command=command[:2]+["-d"]+command[2:]
    started=subprocess.run(command,capture_output=True,check=True,timeout=30)
    identity=started.stdout.decode().strip()
    if not re.fullmatch(r"[a-f0-9]{64}",identity): raise ValueError("REFUSED_CONTAINER_ID")
    try:
        item=fenced_inspect(name)
        if item["Id"]!=identity: raise ValueError("REFUSED_CONTAINER_REPLACEMENT")
        subprocess.run(["docker","wait",identity],capture_output=True,check=True,timeout=1800)
    except subprocess.TimeoutExpired:
        raise ValueError("REFUSED_PREFIX_DEADLINE")
    finally:
        # On every error, first prove this exact private identity and stop it if
        # necessary. Never read financial output while its writer is unknown.
        try:
            item=identity_inspect(name,identity)
            if item["State"]["Running"]:
                subprocess.run(["docker","stop","--time","120",identity],capture_output=True,
                               check=True,timeout=140)
                item=identity_inspect(name,identity)
            if item["State"]["Running"]: raise ValueError("PRIVATE_WRITER_STILL_RUNNING")
        except Exception as exc:
            raise UnprovenStopped("PRIVATE_WRITER_STOP_UNKNOWN") from exc
        with (output/(name+".log")).open("wb") as log:
            subprocess.run(["docker","logs",identity],stdout=log,stderr=subprocess.STDOUT,timeout=20)
    item=fenced_inspect(name)
    (output/(name+"-inspect.json")).write_text(json.dumps(item,indent=2)+"\n")
    if item["State"]["Running"] or item["State"]["ExitCode"]!=0 or item["State"]["OOMKilled"]:
        raise ValueError("REFUSED_WORKER_OUTCOME")


def encrypt_output(root, asset, key):
    members={p.relative_to(root).as_posix():dict(bytes=p.stat().st_size,sha256=sha256_file(p))
             for p in sorted(root.rglob('*')) if p.is_file()}
    raw=(json.dumps(dict(schema="research.capital-risk-output/1",arm="B",stage="baseline-prefix",
                         protocol_sha256=PROTOCOL,members=members),sort_keys=True)+"\n").encode()
    with asset.open("xb") as stream:
        writer=EncryptWriter(stream,key)
        with tarfile.open(fileobj=writer,mode="w|") as tar:
            info=tarfile.TarInfo("manifest.json");info.size=len(raw);tar.addfile(info,io.BytesIO(raw))
            for name in members:
                path=root/name
                if path.is_symlink(): raise ValueError("REFUSED_OUTPUT_LINK")
                info=tarfile.TarInfo(name);info.size=members[name]["bytes"];info.mode=0o600
                with path.open("rb") as source: tar.addfile(info,source)
        writer.finish()


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--request",required=True,type=Path)
    parser.add_argument("--staging-receipt",required=True,type=Path)
    parser.add_argument("--output",required=True,type=Path)
    args=parser.parse_args()
    check_context(os.environ)
    request=json.loads(args.request.read_bytes());validate_request(request)
    proof=json.loads(args.staging_receipt.read_bytes())
    if (proof["status"]!="STAGING_PASSED" or proof["source_commit"]!=os.environ["GITHUB_SHA"]
            or proof["runtime_image"]!=IMAGE or proof["protocol_sha256"]!=PROTOCOL
            or proof["run_id"]!=os.environ["GITHUB_RUN_ID"]
            or proof["manifest_sha256"]!="80cfdade1e2b78706af5881f89414cf1428cb08b364464275b606939c4d1fb4a"
            or proof["source_files_verified"]!=514 or proof["members_verified"]!=591
            or not proof["authenticated_before_parsing"] or not proof["offline_image_source_verified"]
            or proof["replay_started"]):
        raise ValueError("REFUSED_STAGING_ADMISSION")
    key=base64.b64decode(os.environ.pop(SECRET,""),validate=True)
    if len(key)!=32: raise ValueError("REFUSED_RESEARCH_KEY")
    if memory_bytes()["MemAvailable"]<4*1024**3 or shutil.disk_usage(Path(os.environ["RUNNER_TEMP"])).free<12*1024**3:
        raise ValueError("REFUSED_REPLAY_CAPACITY")
    frozen=Path(os.environ["RUNNER_TEMP"])/"capital-risk-stage-001/inputs"
    for p in frozen.rglob('*'): os.chmod(p,0o555 if p.is_dir() else 0o444)
    os.chmod(frozen,0o555)
    private=Path(os.environ["RUNNER_TEMP"])/"capital-risk-prefix-output"
    private.mkdir(mode=0o700,exist_ok=False)
    output=admitted_output(Path(os.environ["GITHUB_WORKSPACE"]),args.output)
    output.parent.mkdir(parents=True,exist_ok=True)
    name="capital-risk-b-prefix-"+os.environ["GITHUB_RUN_ID"]+"-"+os.environ["GITHUB_RUN_ATTEMPT"]
    status,error="PREFIX_PASSED",None
    try:
        run_worker(launch_arguments(name,frozen,private,Path(__file__).resolve().parent),name,private)
        run_worker(launch_arguments(name+"-review",frozen,private,Path(__file__).resolve().parent,review=True),
                   name+"-review",private)
        review=json.loads((private/"prefix-review.json").read_bytes())
        if review["status"]!="PREFIX_PASSED": raise ValueError("REFUSED_PREFIX_REVIEW")
    except UnprovenStopped:
        # The fresh GitHub VM will retire the job. Do not snapshot a potentially
        # active financial writer or mislabel an unknown outcome as stopped.
        receipt=dict(schema="research.capital-risk-prefix-receipt/1",status="WRITER_STOP_UNKNOWN",
                     source_commit=os.environ["GITHUB_SHA"],run_id=os.environ["GITHUB_RUN_ID"],
                     protocol_sha256=PROTOCOL,arm="B",production_contacted=False,
                     encrypted_output=None,full_baseline_gate_satisfied=False)
        output.write_text(json.dumps(receipt,indent=2)+"\n");print(json.dumps(receipt))
        raise SystemExit(2)
    except Exception as exc:
        status,error="PREFIX_REFUSED",type(exc).__name__
        # Error details and worker logs remain inside the encrypted output.
        (private/"orchestration-failure.json").write_text(json.dumps(dict(type=error,message=str(exc)))+"\n")
    asset=output.parent/"baseline-prefix.tar.crseal"
    encrypt_output(private,asset,key);key=None
    receipt=dict(schema="research.capital-risk-prefix-receipt/1",status=status,error_type=error,
                 utc=datetime.now(timezone.utc).isoformat(),source_commit=os.environ["GITHUB_SHA"],
                 run_id=os.environ["GITHUB_RUN_ID"],protocol_sha256=PROTOCOL,arm="B",
                 fresh_initialization_requested=True,requested_formation_transitions=32,
                 full_baseline_gate_satisfied=False,production_contacted=False,
                 encrypted_output=dict(name=asset.name,bytes=asset.stat().st_size,sha256=sha256_file(asset)))
    output.write_text(json.dumps(receipt,indent=2)+"\n");print(json.dumps(receipt))
    raise SystemExit(0 if status=="PREFIX_PASSED" else 2)


if __name__=="__main__": main()
