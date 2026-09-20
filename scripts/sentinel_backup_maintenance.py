#!/usr/bin/env python3
"""Scheduled host coordinator; standard library only, host Python >=3.8.15."""
from __future__ import annotations

import json
import fcntl
from datetime import datetime, timezone
import os
from pathlib import Path
import re
import subprocess
import sys
import time

from sentinel_backup_lock import lock_is_held, _lock_path
from sentinel_maintenance_process import run_bounded


ROOT = Path(__file__).resolve().parents[1]
COMPOSE = ["docker", "compose", "-f", "docker-compose.sentinel.yml",
           "-f", "docker-compose.sentinel-backup.yml"]
IMAGE_RE = re.compile(r"(?:sha256:[0-9a-f]{64}|[A-Za-z0-9][A-Za-z0-9._/:-]*@sha256:[0-9a-f]{64})\Z")
BASE_RE = re.compile(r"base-[0-9]{8}T[0-9]{6}Z\Z")
RENEW_BYTES = 256 * 1024 * 1024
RENEW_SECONDS = 12 * 3600


class Refused(RuntimeError):
    pass


def run(command, *, timeout=120, stdin=None):
    result = run_bounded(command, timeout=timeout, stdin=stdin, private_group=False)
    if result.returncode:
        # Child output is retained by the scheduler; no environment/credentials.
        print(result.stdout, end="")
        print(result.stderr, end="", file=sys.stderr)
        raise Refused("maintenance command failed: " + command[0])
    return result.stdout.strip()


def sql(query, runner=run):
    return runner(COMPOSE + ["exec", "-T", "sentinel-postgres", "psql", "-U", "sentinel",
                            "-d", "sentinel", "-v", "ON_ERROR_STOP=1", "-Atc", query])


def runtime_image(runner=run):
    pointer = ROOT / "artifacts/sentinel/deployment/validated-runtime.env"
    value = os.environ.get("SENTINEL_RUNTIME_IMAGE_REF", "")
    if pointer.exists():
        raw = pointer.read_text(encoding="ascii")
        prefix = "SENTINEL_RUNTIME_IMAGE_REF="
        if not raw.startswith(prefix) or len(raw.splitlines()) != 1:
            raise Refused("invalid validated runtime selector")
        value = raw[len(prefix):].strip()
    if not IMAGE_RE.fullmatch(value):
        raise Refused("maintenance requires an immutable runtime image")
    head = runner(["git", "rev-parse", "HEAD"])
    if runner(["git", "status", "--porcelain", "--untracked-files=no"]):
        raise Refused("maintenance requires a clean reviewed checkout")
    revision = runner(["docker", "image", "inspect", "--format",
                       '{{index .Config.Labels "org.opencontainers.image.revision"}}', value])
    if not re.fullmatch(r"[0-9a-f]{40}", head) or revision != head:
        raise Refused("runtime image does not match the maintenance checkout")
    return value


def observe_primary(runner=run):
    value = json.loads(sql("""SELECT json_build_object(
        'system_id',system_identifier::text,
        'now',floor(extract(epoch FROM clock_timestamp()))::bigint,
        'lsn',pg_current_wal_lsn()::text,
        'timeline',substring(pg_walfile_name(pg_current_wal_lsn()) from 1 for 8),
        'segment_size',pg_size_bytes(current_setting('wal_segment_size')))
        FROM pg_control_system()""", runner))
    if (not re.fullmatch(r"[1-9][0-9]{0,19}", str(value.get("system_id", "")))
            or not re.fullmatch(r"[0-9A-F]{8}", str(value.get("timeline", "")))
            or not re.fullmatch(r"[0-9A-F]+/[0-9A-F]{1,8}", str(value.get("lsn", "")))
            or type(value.get("now")) is not int
            or type(value.get("segment_size")) is not int):
        raise Refused("invalid primary observation")
    size = value["segment_size"]
    if not 1024 * 1024 <= size <= 1024**3 or size & (size - 1):
        raise Refused("invalid primary WAL geometry")
    return value


def renewal_due(selected, observation):
    age = observation["now"] - selected["timestamp"]
    if age < 0:
        raise Refused("backup is future-dated")
    current_timeline = int(observation["timeline"], 16)
    ranges = selected["ranges"]
    if any(item["timeline"] > current_timeline for item in ranges):
        raise Refused("primary timeline regressed")
    if any(item["timeline"] < current_timeline for item in ranges):
        return True
    high, low = observation["lsn"].split("/")
    current = int(high, 16) * 2**32 + int(low, 16)
    end = max(item["end"] for item in ranges)
    if current < end:
        raise Refused("primary WAL regressed")
    size = observation["segment_size"]
    footprint = (current // size - (end - 1) // size + 1) * size
    return age >= RENEW_SECONDS or footprint >= RENEW_BYTES


def worker(action, image, root, observation, runner=run, request=None):
    command = ["docker", "run", "--rm", "-i", "--network", "none", "--read-only",
               "--user", "0:0", "--cap-drop", "ALL", "--cap-add", "DAC_OVERRIDE",
               "--security-opt", "no-new-privileges",
               "--memory", "256m", "--pids-limit", "64",
               "-v", root + "/base:/backup/base", "-v", root + "/wal:/backup/wal",
               "--entrypoint", "python", image, "-m", "sentinel.backup_retention", action,
               "--system-id", observation["system_id"]]
    return json.loads(runner(command, timeout=600,
                             stdin=json.dumps(request) if request is not None else None))


def receipt_for(selected, observation, image, runner=run):
    name, digest = selected["name"], selected["metadata_sha256"]
    if not BASE_RE.fullmatch(name) or not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise Refused("invalid selected identity")
    # Fields interpolated below are already restricted to machine identities.
    raw = sql("SELECT proof::text FROM sentinel_backup_evidence "
              "WHERE kind='RESTORE_DRILL' AND proof->>'base_backup'='" + name + "' "
              "AND proof->>'metadata_sha256'='" + digest + "' "
              "ORDER BY observed_at DESC,seq DESC LIMIT 1", runner)
    if not raw:
        return None
    result = json.loads(raw)
    expected = {"base_backup": name, "metadata_sha256": digest,
                "system_identifier": observation["system_id"], "runtime_image": image,
                "physical_only": False, "marker": selected["marker"],
                "target_lsn": selected["target_lsn"]}
    if not isinstance(result, dict) or any(type(result.get(k)) is not type(v) or result.get(k) != v
                                          for k, v in expected.items()):
        return None
    return result


def reap_restore_resources(now, runner=run):
    """Remove only expired, labeled and unreferenced disposable resources."""
    removed = 0
    for kind in ("volume", "network"):
        names = runner(["docker", kind, "ls", "--filter", "label=sentinel.restore-drill=v1",
                        "--format", "{{.Name}}"]).splitlines()
        if len(names) > 256:
            raise Refused("restore resource inventory exceeds recovery bound")
        for name in names:
            if not re.fullmatch(r"sentinel-restore-drill-[0-9]{8}T[0-9]{6}Z-[0-9]+-[0-9a-f]{32}", name):
                raise Refused("unexpected labeled restore resource identity")
            raw = runner(["docker", kind, "inspect", "--format", "{{json .}}", name])
            record = json.loads(raw)
            if record.get("Name") != name or record.get("Labels", {}).get("sentinel.restore-drill") != "v1":
                raise Refused("restore resource identity changed")
            stamp_text = record["CreatedAt" if kind == "volume" else "Created"]
            # Docker emits nanoseconds; host Python 3.8 accepts microseconds.
            stamp_text = re.sub(r"\.(\d{1,9})(?=Z|[+-][0-9]{2}:[0-9]{2}$)",
                                lambda match: "." + match[1][:6].ljust(6, "0"), stamp_text)
            stamp = datetime.fromisoformat(stamp_text.replace("Z", "+00:00"))
            if stamp.tzinfo is None:
                raise Refused("restore resource has no clock offset")
            age = now - stamp.astimezone(timezone.utc).timestamp()
            if age < 0:
                raise Refused("restore resource is future-dated")
            if age < 7200:
                continue
            if kind == "volume":
                if runner(["docker", "ps", "-a", "--filter", "volume=" + name, "--format", "{{.ID}}"]):
                    continue
            elif record.get("Containers") != {}:
                continue
            # Docker's removal is the final atomic in-use check; never force it.
            runner(["docker", kind, "rm", name])
            removed += 1
    return removed


def tick(root, runner=run):
    image = runtime_image(runner)
    observation = observe_primary(runner)
    reap_restore_resources(observation["now"], runner)
    selected = worker("observe", image, root, observation, runner)
    renewed = renewal_due(selected, observation)
    if renewed:
        output = runner(["bash", "scripts/sentinel-base-backup.sh"], timeout=600)
        paths = [line[len("verified_base_backup:"):] for line in output.splitlines()
                 if line.startswith("verified_base_backup:")]
        if len(paths) != 1 or not paths[0].startswith(root + "/base/"):
            raise Refused("producer did not return one exact successor")
        selected = worker("observe", image, root, observation, runner)
        if paths[0] != root + "/base/" + selected["name"]:
            raise Refused("producer successor differs from selected generation")
        observation = observe_primary(runner)
        if renewal_due(selected, observation):
            raise Refused("successor already exhausts maintenance headroom")
    path = root + "/base/" + selected["name"]
    runner(["bash", "scripts/sentinel-backup-status.sh", "--backup", path], timeout=600)
    receipt = receipt_for(selected, observation, image, runner)
    if receipt is None:
        # Exactly the normal full semantic drill. No physical-only or bypass flag.
        env_before = os.environ.get("SENTINEL_RUNTIME_IMAGE_REF")
        os.environ["SENTINEL_RUNTIME_IMAGE_REF"] = image
        try:
            runner(["bash", "scripts/sentinel-restore-drill.sh", "--backup", path], timeout=2100)
        finally:
            if env_before is None:
                os.environ.pop("SENTINEL_RUNTIME_IMAGE_REF", None)
            else:
                os.environ["SENTINEL_RUNTIME_IMAGE_REF"] = env_before
        receipt = receipt_for(selected, observation, image, runner)
        if receipt is None:
            raise Refused("full restore returned without matching durable evidence")
    # The full drill may take time: obtain fresh clocks and a fresh chain proof.
    observation = observe_primary(runner)
    runner(["bash", "scripts/sentinel-backup-status.sh", "--backup", path], timeout=600)
    result = worker("retain", image, root, observation, runner, {
        "receipt": receipt, "image": image, "now": observation["now"],
        "segment_size": observation["segment_size"],
    })
    print(json.dumps({"maintenance_ready": True, "observed_at": observation["now"], "renewed": renewed,
                      "base": selected["name"], **result}, sort_keys=True))
    return result


def supervise():
    path = _lock_path(os.environ)
    if path is None:
        raise Refused("supervisor requires a canonical target")
    path = path.with_suffix(".maintenance-loop")
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with path.open("a+") as handle:
        os.chmod(path, 0o600)
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print("SENTINEL_BACKUP_MAINTENANCE=SUPERVISOR_ALREADY_RUNNING", flush=True)
            return 0
        while True:
            result = subprocess.run(["bash", "scripts/sentinel-backup-maintenance.sh"],
                                    cwd=str(ROOT), check=False, pass_fds=(handle.fileno(),))
            if result.returncode:
                print("SENTINEL_BACKUP_MAINTENANCE=FAILED_RETRY_PENDING", file=sys.stderr, flush=True)
            time.sleep(60)


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    if args == ["--loop"]:
        return supervise()
    if args:
        print("usage: sentinel-backup-maintenance.sh [--loop]", file=sys.stderr)
        return 2
    if not lock_is_held():
        print("REFUSED: maintenance requires the target ownership lock", file=sys.stderr)
        return 4
    root = os.environ["SENTINEL_BASE_BACKUP_LOCK_ROOT"]
    try:
        tick(root)
        return 0
    except (Refused, OSError, ValueError, KeyError, TypeError) as exc:
        print("REFUSED: backup maintenance: " + str(exc), file=sys.stderr, flush=True)
        return 4


if __name__ == "__main__":
    raise SystemExit(main())
