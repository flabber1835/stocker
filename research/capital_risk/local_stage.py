"""Local read-only export and encryption. Never launches a container or replay."""
from __future__ import annotations

import argparse
import base64
import ctypes
from ctypes import wintypes
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import tarfile
import threading

from seal import BLOCK, EncryptWriter, sha256_file, safe_name

IMAGE = "sha256:97b69cf2f8487785e55a4ecafe2497829d021a9d58b5e4af001e8dcc6a981309"
PROTOCOL = "a4591ac1a8ca6d927d4a5452c8bfce766e910fc75d33dbbd48d3f0fd8adb1e52"
SECRET = "CAPITAL_RISK_RESEARCH_KEY_20261027"
RELEASE = "research-capital-risk-inputs-20261027"


class Blob(ctypes.Structure):
    _fields_ = [("size", wintypes.DWORD), ("data", ctypes.POINTER(ctypes.c_ubyte))]


def dpapi(value: bytes, *, unprotect=False) -> bytes:
    if os.name != "nt":
        raise ValueError("REFUSED_NON_WINDOWS_RECOVERY_KEY")
    buffer = ctypes.create_string_buffer(value)
    source = Blob(len(value), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    output = Blob()
    crypt = ctypes.WinDLL("crypt32", use_last_error=True)
    arguments = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.POINTER(Blob),
                 ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
    crypt.CryptUnprotectData.argtypes = arguments
    crypt.CryptProtectData.argtypes = [ctypes.POINTER(Blob), wintypes.LPCWSTR, *arguments[2:]]
    crypt.CryptUnprotectData.restype = crypt.CryptProtectData.restype = wintypes.BOOL
    if unprotect:
        ok = crypt.CryptUnprotectData(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(output))
    else:
        ok = crypt.CryptProtectData(ctypes.byref(source), "Capital risk research only", None, None,
                                   None, 1, ctypes.byref(output))
    if not ok:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        return ctypes.string_at(output.data, output.size)
    finally:
        free = ctypes.WinDLL("kernel32").LocalFree
        free.argtypes, free.restype = [ctypes.c_void_p], ctypes.c_void_p
        free(output.data)


def inventory(staging: dict, case: Path, protocol: Path) -> tuple[dict, dict]:
    paths, members = {}, {}

    def add(name, source, expected=None, size=None):
        safe_name(name)
        source = Path(source)
        if name in paths or source.is_symlink() or not source.is_file():
            raise ValueError("REFUSED_INVENTORY_SOURCE")
        actual_size = source.stat().st_size
        if size is not None and size != actual_size:
            raise ValueError("REFUSED_SOURCE_SIZE_" + name)
        paths[name] = source
        members[name] = dict(bytes=actual_size, sha256=expected or sha256_file(source))

    source = staging["fixed_source"]
    if len(source["files"]) != 514 or staging["protocol_sha256"] != PROTOCOL:
        raise ValueError("REFUSED_STAGING_IDENTITY")
    for name, digest in source["files"].items():
        add("source-fixed/" + name, Path(source["root"]) / name, digest)
    archive = staging["archive"]
    add("archive/corpus.zip", archive["source"], archive["recorded_sha256"], archive["bytes"])
    bundle = staging["bundle"]
    add("bundle/manifest.json", Path(bundle["root"]) / "manifest.json", bundle["manifest_sha256"])
    for name, member in bundle["members"].items():
        add("bundle/" + name, Path(bundle["root"]) / name, member["sha256"], member["bytes"])
    for name, member in staging["references"].items():
        add("references/" + name, member["source"], member["recorded_sha256"], member["bytes"])
    for repair in staging["repairs"]["cases"]:
        for name in ("DESIGN.md", "primary-source-extraction.json", "preparation.json", "prepare.py",
                     "fixed/overlay.json", "post-replay-verification.json"):
            add("historical-repair-evidence/" + repair + "/" + name,
                Path(staging["repairs"]["root"]) / repair / name)
    for name in ("formation.jsonl", "daily.jsonl", "monthly.jsonl", "result.json", "identity.json",
                 "checkpoint.json.gz"):
        add("baseline-comparison/" + name, case / "output/fixed/run-001" / name)
    add("baseline-comparison/fixed-review.json", staging["baseline_completion_review"]["source"],
        staging["baseline_completion_review"]["sha256"])
    add("protocol.json", protocol, PROTOCOL)
    manifest = dict(schema="research.capital-risk-inputs/1", protocol_sha256=PROTOCOL,
                    expected_image=IMAGE, bundle_commitment=bundle["commitment"],
                    source_files=514, repair_evidence_is_historical_not_resume_authority=True,
                    members=dict(sorted(members.items())))
    return paths, manifest


class VerifiedReader:
    def __init__(self, stream):
        self.stream, self.digest = stream, hashlib.sha256()
        self.count = 0

    def read(self, size=-1):
        value = self.stream.read(size)
        self.digest.update(value)
        self.count += len(value)
        return value


def pack_data(output: Path, key: bytes, paths: dict, manifest: dict) -> str:
    payload = (json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n").encode()
    with output.open("xb") as destination:
        writer = EncryptWriter(destination, key)
        with tarfile.open(fileobj=writer, mode="w|") as tar:
            info = tarfile.TarInfo("manifest.json"); info.size = len(payload); info.mode = 0o600
            tar.addfile(info, io.BytesIO(payload))
            for name, spec in manifest["members"].items():
                info = tarfile.TarInfo(name); info.size = spec["bytes"]; info.mode = 0o600
                with paths[name].open("rb") as source:
                    reader = VerifiedReader(source)
                    tar.addfile(info, reader)
                    if (reader.count != spec["bytes"] or reader.digest.hexdigest() != spec["sha256"]
                            or source.read(1)):
                        raise ValueError("REFUSED_CHANGED_SOURCE_" + name)
        writer.finish()
    return hashlib.sha256(payload).hexdigest()


def export_runtime(output: Path, key: bytes) -> None:
    # Read-only Docker export of this exact retained research image. No docker run.
    process = subprocess.Popen(["docker", "image", "save", IMAGE], stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE)
    timer = threading.Timer(180, process.kill)
    timer.start()
    try:
        with output.open("xb") as destination:
            writer = EncryptWriter(destination, key)
            while part := process.stdout.read(BLOCK):
                writer.write(part)
            if process.wait(timeout=10):
                raise ValueError("REFUSED_RUNTIME_EXPORT")
            writer.finish()
    finally:
        timer.cancel()
        if process.poll() is None:
            process.kill()
        process.stdout.close(); process.stderr.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--staging-manifest", type=Path)
    parser.add_argument("--case", type=Path)
    parser.add_argument("--protocol", type=Path)
    parser.add_argument("--destination", required=True, type=Path)
    parser.add_argument("--publish-key", action="store_true")
    args = parser.parse_args()
    if args.publish_key:
        key = dpapi((args.destination / "key.dpapi").read_bytes(), unprotect=True)
        subprocess.run(["gh", "secret", "set", SECRET, "--repo", "flabber1835/stocker"],
                       input=base64.b64encode(key), timeout=30, check=True, capture_output=True)
        print("Research-only Actions secret registered; value withheld.")
        return
    paths, manifest = inventory(json.loads(args.staging_manifest.read_bytes()), args.case, args.protocol)
    args.destination.mkdir(mode=0o700, parents=True, exist_ok=False)
    key = os.urandom(32)
    (args.destination / "key.dpapi").write_bytes(dpapi(key))
    data = args.destination / "data.tar.crseal"
    manifest_sha256 = pack_data(data, key, paths, manifest)
    print("Frozen data encrypted; source inventory verified while streaming.", flush=True)
    runtime = args.destination / "runtime.tar.crseal"
    export_runtime(runtime, key)
    request = dict(schema="research.capital-risk-stage-request/1", request_id="stage-001", stage="stage",
                   protocol_sha256=PROTOCOL, release=RELEASE, expected_image=IMAGE,
                   manifest_sha256=manifest_sha256,
                   assets={p.name:dict(sha256=sha256_file(p), bytes=p.stat().st_size) for p in (data,runtime)})
    (args.destination / "stage-request.json").write_text(json.dumps(request, indent=2)+"\n")
    print(json.dumps(dict(status="ENCRYPTED_FOR_TRANSFER", source_files=514,
                         member_count=len(paths), assets=request["assets"])))


if __name__ == "__main__":
    main()
