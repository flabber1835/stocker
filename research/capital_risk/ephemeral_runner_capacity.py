"""Prepare only an unused Android tree on a dedicated hosted research runner."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import platform
import re
import shutil
import stat
import subprocess
from typing import Mapping


SCHEMA = "research.ephemeral-runner-capacity/1"
AUTHORITY = "NONFINANCIAL_HOST_PREPARATION"
REPOSITORY = "flabber1835/stocker"
REF = "refs/heads/codex/capital-risk-research"
TARGET = "/usr/local/lib/android"
SDK = TARGET + "/sdk"
WORKSPACE = "/home/runner/work/stocker/stocker"
TEMP = "/home/runner/work/_temp"
TOOLS = "/opt/hostedtoolcache"
MODULE = "research/capital_risk/ephemeral_runner_capacity.py"
OUTPUT = "artifacts/capital-risk/ephemeral-runner-capacity.json"
MIN_FREE = 12 * 1024**3
DELETE_COMMAND = (
    "/usr/bin/sudo", "-n", "/usr/bin/rm", "--recursive", "--force",
    "--one-file-system", "--preserve-root=all", "--", TARGET,
)
ANCESTORS = ("/", "/usr", "/usr/local", "/usr/local/lib", TARGET)
MARKERS = (SDK + "/cmdline-tools/latest/bin/sdkmanager", SDK + "/platform-tools/adb")
FORBIDDEN = (
    "ALPACA_API_KEY", "ALPACA_SECRET_KEY", "APCA_API_KEY_ID", "APCA_API_SECRET_KEY",
    "DATABASE_URL", "PGPASSWORD", "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "OPENAI_API_KEY",
)
PUBLIC_FIELDS = frozenset((
    "schema", "authority", "run_id", "head", "ref", "source_sha256", "target", "phase",
    "phase_history", "removal_attempted", "target_removed", "free_before_bytes", "free_after_bytes",
    "error_code", "production_contacted", "financial_or_market_payload_included",
))


class Refusal(ValueError):
    """A static public invariant code, never an exception payload."""


def need(value: bool, code: str) -> None:
    if not value:
        raise Refusal(code)


def context(env: Mapping[str, str], host: dict) -> None:
    expected = {
        "GITHUB_ACTIONS": "true", "GITHUB_REPOSITORY": REPOSITORY,
        "GITHUB_REPOSITORY_OWNER": "flabber1835", "GITHUB_ACTOR": "flabber1835",
        "GITHUB_REF": REF, "GITHUB_REF_TYPE": "branch", "GITHUB_EVENT_NAME": "push",
        "GITHUB_RUN_ATTEMPT": "1", "RUNNER_ENVIRONMENT": "github-hosted",
        "RUNNER_OS": "Linux", "RUNNER_ARCH": "X64", "ImageOS": "ubuntu24",
        "GITHUB_WORKSPACE": WORKSPACE, "RUNNER_TEMP": TEMP, "RUNNER_TOOL_CACHE": TOOLS,
        "ANDROID_HOME": SDK, "ANDROID_SDK_ROOT": SDK,
    }
    need(all(env.get(k) == v for k, v in expected.items()), "REFUSED_CAPACITY_CONTEXT")
    need(host == dict(system="Linux", os_id="ubuntu", os_version="24.04", containerized=False),
         "REFUSED_CAPACITY_ACTUAL_HOST")
    need(not env.get("GITHUB_HEAD_REF") and not env.get("GITHUB_BASE_REF")
         and not any(env.get(k) for k in FORBIDDEN), "REFUSED_CAPACITY_SCOPE_OR_CREDENTIAL")
    need(re.fullmatch(r"[0-9a-f]{40}", env.get("GITHUB_SHA", "")) is not None
         and re.fullmatch(r"[1-9][0-9]*", env.get("GITHUB_RUN_ID", "")) is not None,
         "REFUSED_CAPACITY_SOURCE_OR_RUN")
    workflow = env.get("GITHUB_WORKFLOW_REF", "")
    need(re.fullmatch(re.escape(REPOSITORY) + r"/\.github/workflows/[a-z0-9_-]+\.yml@"
                      + re.escape(REF), workflow) is not None, "REFUSED_CAPACITY_WORKFLOW_REF")


def host_metadata() -> dict:
    fields = {}
    for line in Path("/etc/os-release").read_text().splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            fields[key] = value.strip('"')
    return dict(system=platform.system(), os_id=fields.get("ID"), os_version=fields.get("VERSION_ID"),
                containerized=Path("/.dockerenv").exists() or Path("/run/.containerenv").exists())


def record(path: str) -> dict:
    value = Path(path).lstat()
    return dict(path=path, resolved=str(Path(path).resolve(strict=True)),
                mode=stat.S_IFMT(value.st_mode), permissions=stat.S_IMODE(value.st_mode),
                uid=value.st_uid, device=value.st_dev, inode=value.st_ino,
                symlink=stat.S_ISLNK(value.st_mode))


def mounts(text: str) -> list[dict]:
    values = []
    for line in text.splitlines():
        parts = line.split()
        need(len(parts) >= 10 and "-" in parts, "REFUSED_CAPACITY_MOUNTINFO")
        separator = parts.index("-")
        need(separator >= 6 and len(parts) >= separator + 4, "REFUSED_CAPACITY_MOUNTINFO")
        point = re.sub(r"\\([0-7]{3})", lambda m: chr(int(m.group(1), 8)), parts[4])
        need(point.startswith("/"), "REFUSED_CAPACITY_MOUNTINFO")
        values.append(dict(point=point, filesystem=parts[separator + 1]))
    need(bool(values), "REFUSED_CAPACITY_MOUNTINFO")
    return values


def layout() -> dict:
    paths = [*ANCESTORS, SDK, SDK + "/cmdline-tools", SDK + "/cmdline-tools/latest",
             SDK + "/cmdline-tools/latest/bin", SDK + "/platform-tools"]
    return dict(ancestors=[record(p) for p in ANCESTORS],
                sdk_directories=[record(p) for p in paths[len(ANCESTORS):]],
                markers=[record(p) for p in MARKERS],
                target_children=sorted(p.name for p in Path(TARGET).iterdir()),
                scopes=[record(p) for p in (WORKSPACE, TEMP, TOOLS)],
                mounts=mounts(Path("/proc/self/mountinfo").read_text()),
                commands=[record(p) for p in ("/usr/bin/sudo", "/usr/bin/rm")])


def admit_layout(value: dict) -> tuple[int, int]:
    ancestors = value["ancestors"]
    need([p["path"] for p in ancestors] == list(ANCESTORS), "REFUSED_CAPACITY_FIXED_TARGET")
    for p in [*ancestors, *value["sdk_directories"], *value["markers"],
              *value["scopes"], *value["commands"]]:
        need(p["resolved"] == p["path"] and not p["symlink"], "REFUSED_CAPACITY_PATH_ALIAS")
    need(all(p["mode"] == stat.S_IFDIR and p["uid"] == 0 and not p["permissions"] & 0o022
             for p in ancestors[:-1]) and ancestors[-1]["mode"] == stat.S_IFDIR,
         "REFUSED_CAPACITY_PROTECTED_ANCESTORS")
    dirs = [SDK, SDK + "/cmdline-tools", SDK + "/cmdline-tools/latest",
            SDK + "/cmdline-tools/latest/bin", SDK + "/platform-tools"]
    need([p["path"] for p in value["sdk_directories"]] == dirs
         and all(p["mode"] == stat.S_IFDIR for p in value["sdk_directories"])
         and value["target_children"] == ["sdk"], "REFUSED_CAPACITY_SDK_IDENTITY")
    need([p["path"] for p in value["markers"]] == list(MARKERS)
         and all(p["mode"] == stat.S_IFREG for p in value["markers"]),
         "REFUSED_CAPACITY_SDK_MARKERS")
    need([p["path"] for p in value["commands"]] == ["/usr/bin/sudo", "/usr/bin/rm"]
         and all(p["mode"] == stat.S_IFREG and p["uid"] == 0 and not p["permissions"] & 0o022
                 for p in value["commands"]), "REFUSED_CAPACITY_COMMAND_IDENTITY")
    target = PurePosixPath(TARGET)
    need([p["path"] for p in value["scopes"]] == [WORKSPACE, TEMP, TOOLS]
         and all(p["mode"] == stat.S_IFDIR
                 and not PurePosixPath(p["resolved"]).is_relative_to(target)
                 and not target.is_relative_to(PurePosixPath(p["resolved"])) for p in value["scopes"]),
         "REFUSED_CAPACITY_PROTECTED_SCOPES")
    need(not any(PurePosixPath(p["point"]).is_relative_to(target)
                 or (p["point"] != "/" and target.is_relative_to(PurePosixPath(p["point"])))
                 for p in value["mounts"]),
         "REFUSED_CAPACITY_ANDROID_MOUNT")
    root = [p for p in value["mounts"] if p["point"] == "/"]
    need(len(root) == 1 and root[0]["filesystem"] in ("ext4", "xfs"),
         "REFUSED_CAPACITY_SHARED_OR_CONTAINER_FILESYSTEM")
    android = ancestors[-1]
    need(android["device"] == ancestors[-2]["device"]
         == value["scopes"][0]["device"] == value["scopes"][1]["device"],
         "REFUSED_CAPACITY_DIFFERENT_FILESYSTEM")
    return android["device"], android["inode"]


def checkout(env: Mapping[str, str]) -> str:
    module = Path(__file__)
    need(str(module.resolve(strict=True)) == WORKSPACE + "/" + MODULE,
         "REFUSED_CAPACITY_CHECKED_OUT_MODULE")
    head = subprocess.check_output(["git", "-C", WORKSPACE, "rev-parse", "HEAD"], timeout=20).decode().strip()
    source = subprocess.check_output(["git", "-C", WORKSPACE, "show", head + ":" + MODULE], timeout=20)
    need(head == env["GITHUB_SHA"] and module.read_bytes() == source,
         "REFUSED_CAPACITY_EXACT_CHECKOUT")
    return hashlib.sha256(source).hexdigest()


def admitted_output(output: Path) -> Path:
    expected = Path(WORKSPACE) / OUTPUT
    need(output.is_absolute() and output.resolve() == expected and not output.is_symlink()
         and not output.exists(), "REFUSED_CAPACITY_OUTPUT")
    return expected


def write_receipt(path: Path, value: dict) -> None:
    need(set(value) == PUBLIC_FIELDS and value["schema"] == SCHEMA and value["authority"] == AUTHORITY
         and value["target"] == TARGET and value["production_contacted"] is False
         and value["financial_or_market_payload_included"] is False, "REFUSED_CAPACITY_RECEIPT_SCOPE")
    path.parent.mkdir(parents=True, exist_ok=True)
    pending = path.with_suffix(".partial")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
    fd = os.open(pending, flags, 0o600)
    with os.fdopen(fd, "w", encoding="utf8", newline="\n") as stream:
        stream.write(json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(pending, path)
    directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def remove_android() -> None:
    try:
        subprocess.run(list(DELETE_COMMAND), shell=False, check=True, stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, timeout=180)
    except subprocess.TimeoutExpired as error:
        raise Refusal("UNKNOWN_REMOVAL_OUTCOME") from error
    except (OSError, subprocess.CalledProcessError) as error:
        raise Refusal("REFUSED_CAPACITY_REMOVAL_COMMAND") from error


def free_bytes() -> int:
    return shutil.disk_usage(TEMP).free


def target_absent() -> bool:
    return not os.path.lexists(TARGET)


def prepare(output: Path, env: Mapping[str, str]) -> dict:
    context(env, host_metadata())
    output = admitted_output(output)
    source = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    receipt = dict(schema=SCHEMA, authority=AUTHORITY, run_id=env["GITHUB_RUN_ID"],
                   head=env["GITHUB_SHA"], ref=REF, source_sha256=source, target=TARGET,
                   phase="VALIDATING", phase_history=["VALIDATING"], removal_attempted=False,
                   target_removed=None, free_before_bytes=None, free_after_bytes=None, error_code=None,
                   production_contacted=False, financial_or_market_payload_included=False)
    write_receipt(output, receipt)
    try:
        need(checkout(env) == source, "REFUSED_CAPACITY_EXACT_CHECKOUT")
        receipt["free_before_bytes"] = free_bytes()
        identity = admit_layout(layout())
        context(env, host_metadata())
        need(checkout(env) == source and admit_layout(layout()) == identity,
             "REFUSED_CAPACITY_TARGET_CHANGED")
        receipt.update(phase="REMOVAL_ATTEMPTED", removal_attempted=True,
                       phase_history=[*receipt["phase_history"], "REMOVAL_ATTEMPTED"])
        write_receipt(output, receipt)
        remove_android()
        receipt["target_removed"] = target_absent()
        receipt["free_after_bytes"] = free_bytes()
        need(receipt["target_removed"] is True, "REFUSED_CAPACITY_TARGET_REMAINS")
        need(type(receipt["free_after_bytes"]) is int and receipt["free_after_bytes"] >= MIN_FREE,
             "REFUSED_CAPACITY_AFTER_REMOVAL_RESERVE")
        receipt.update(phase="PREPARED", phase_history=[*receipt["phase_history"], "PREPARED"])
    except Exception as error:
        code = str(error) if isinstance(error, Refusal) else "REFUSED_CAPACITY_PREPARATION_OPERATION"
        need(re.fullmatch(r"(?:REFUSED_CAPACITY_[A-Z_]+|UNKNOWN_REMOVAL_OUTCOME)", code) is not None,
             "REFUSED_CAPACITY_PUBLIC_ERROR")
        receipt.update(phase="REFUSED", error_code=code,
                       phase_history=[*receipt["phase_history"], "REFUSED"])
    write_receipt(output, receipt)
    return receipt


def validate_prepared_receipt(value: dict, *, head: str, run_id: str, source_sha256: str) -> None:
    need(set(value) == PUBLIC_FIELDS and value["schema"] == SCHEMA and value["authority"] == AUTHORITY
         and value["head"] == head and value["run_id"] == run_id and value["ref"] == REF
         and value["source_sha256"] == source_sha256 and value["target"] == TARGET,
         "REFUSED_CAPACITY_PREPARED_IDENTITY")
    need(value["phase"] == "PREPARED" and value["phase_history"] ==
         ["VALIDATING", "REMOVAL_ATTEMPTED", "PREPARED"] and value["removal_attempted"] is True
         and value["target_removed"] is True and value["error_code"] is None
         and type(value["free_before_bytes"]) is int and value["free_before_bytes"] >= 0
         and type(value["free_after_bytes"]) is int and value["free_after_bytes"] >= MIN_FREE
         and value["production_contacted"] is False and value["financial_or_market_payload_included"] is False,
         "REFUSED_CAPACITY_NOT_ACTUALLY_PREPARED")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        value = prepare(args.output, dict(os.environ))
    except Exception as error:
        code = str(error) if isinstance(error, Refusal) else "REFUSED_CAPACITY_PREPARATION_OPERATION"
        print(json.dumps(dict(schema=SCHEMA, phase="REFUSED_BEFORE_RECEIPT", error_code=code)))
        return 2
    print(json.dumps(value, sort_keys=True))
    return 0 if value["phase"] == "PREPARED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
