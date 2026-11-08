"""Resumable transport of the exact owner-approved ciphertext; no new payload."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import time

from seal import BLOCK, sha256_file
from stage import RELEASE, validate_request

CHUNK=64*1024**2
REPO="flabber1835/stocker"


def remote_assets():
    result=subprocess.run(["gh","api",f"repos/{REPO}/releases/tags/{RELEASE}"],
                          capture_output=True,text=True,check=True,timeout=30)
    value=json.loads(result.stdout)
    if value["tag_name"]!=RELEASE or not value["prerelease"]:
        raise ValueError("REFUSED_RELEASE_IDENTITY")
    return {a["name"]:a for a in value["assets"]}


def matches(asset, part):
    return (asset["state"]=="uploaded" and asset["size"]==part["bytes"]
            and asset["digest"]=="sha256:"+part["sha256"])


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--directory",required=True,type=Path)
    args=parser.parse_args()
    root=args.directory.resolve()
    request=json.loads((root/"stage-request.json").read_bytes())
    validate_request(request)
    source=root/"data.tar.crseal"
    spec=request["assets"][source.name]
    if sha256_file(source)!=spec["sha256"] or source.stat().st_size!=spec["bytes"]:
        raise ValueError("REFUSED_CHANGED_APPROVED_CIPHERTEXT")
    parts=[]
    with source.open("rb") as stream:
        remaining=spec["bytes"]
        while remaining:
            size=min(CHUNK,remaining);left=size;digest=hashlib.sha256()
            while left:
                value=stream.read(min(BLOCK,left))
                if not value: raise ValueError("REFUSED_TRUNCATED_CIPHERTEXT")
                digest.update(value);left-=len(value)
            parts.append(dict(name=f"{source.name}.part-{len(parts):04d}",bytes=size,sha256=digest.hexdigest()))
            remaining-=size
    spec["parts"]=parts;validate_request(request)
    (root/"stage-request-parts.json").write_text(json.dumps(request,indent=2)+"\n")
    folder=root/"transfer-parts";folder.mkdir(exist_ok=True)
    known=remote_assets()
    runtime=request["assets"]["runtime.tar.crseal"]
    if not matches(known["runtime.tar.crseal"],runtime): raise ValueError("REFUSED_RUNTIME_ASSET")
    with source.open("rb") as stream:
        for index,part in enumerate(parts):
            if part["name"] in known:
                if not matches(known[part["name"]],part): raise ValueError("REFUSED_REMOTE_PART_COLLISION")
                stream.seek(part["bytes"],1)
                print(f"PART_VERIFIED {index+1}/{len(parts)} reused",flush=True)
                continue
            local=folder/part["name"]
            if local.parent.resolve()!=folder.resolve(): raise ValueError("REFUSED_TEMP_PATH")
            if local.exists():
                if local.stat().st_size!=part["bytes"] or sha256_file(local)!=part["sha256"]:
                    raise ValueError("REFUSED_LOCAL_PART_COLLISION")
                stream.seek(part["bytes"],1)
            else:
                left=part["bytes"]
                with local.open("xb") as output:
                    while left:
                        value=stream.read(min(BLOCK,left));output.write(value);left-=len(value)
            for attempt in range(2):
                uploaded=subprocess.run(["gh","release","upload",RELEASE,str(local),"--repo",REPO],
                                        capture_output=True,text=True,timeout=300)
                known=remote_assets()
                if part["name"] in known:
                    if not matches(known[part["name"]],part): raise ValueError("REFUSED_REMOTE_PART_COLLISION")
                    break
                if attempt or not any(s in uploaded.stderr for s in ["bad record MAC","EOF","timeout"]):
                    raise ValueError("REFUSED_PART_UPLOAD_"+str(index))
                time.sleep(5)
            else:
                raise ValueError("REFUSED_PART_NOT_RETAINED")
            # Only this task's one exact temporary ciphertext chunk is removed.
            local.unlink()
            print(f"PART_VERIFIED {index+1}/{len(parts)}",flush=True)
    final=remote_assets()
    if not all(matches(final[p["name"]],p) for p in parts): raise ValueError("REFUSED_FINAL_PARTS")
    (root/"remote-upload-verification.json").write_text(json.dumps(dict(status="REMOTE_ASSETS_VERIFIED",
        original_ciphertext_sha256=spec["sha256"],original_ciphertext_bytes=spec["bytes"],
        parts=parts,runtime_verified=True),indent=2)+"\n")
    print("REMOTE_ASSETS_VERIFIED",flush=True)


if __name__=="__main__": main()
