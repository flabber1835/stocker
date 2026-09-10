#!/usr/bin/env python3
"""Executable boundary for shell orchestration tests, never a Docker client.

Runs production shell snippets against temporary files. PostgreSQL responses and
manifest hashes here are simulated; the separate physical gate uses PostgreSQL.
Unknown commands fail. All invocations and injected faults are retained.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import shutil
from decimal import Decimal, ROUND_FLOOR, ROUND_HALF_UP

ROOT = Path(os.environ["BACKUP_LAB_ROOT"])
MEDIA = ROOT / "media"
SYSTEM_ID = "7377777777777777777"
WAL = "000000010000000000000003"
args = sys.argv[1:]
name = Path(sys.argv[0]).name


def event(stage, callback):
    with (ROOT / "events.jsonl").open("a") as stream:
        stream.write(json.dumps({"stage": stage, "argv": args}) + "\n")
    point = os.environ.get("BACKUP_LAB_FAULT", "")
    if point == stage + ":before":
        sys.exit(71)
    code = callback()
    if point == stage + ":after":
        sys.exit(72)
    return code


def sql():
    query = args[-1]
    if query == "SHOW archive_mode":
        print("on")
    elif query == "SELECT system_identifier::text FROM pg_control_system()":
        print(SYSTEM_ID)
    elif query == "SELECT pg_size_bytes(current_setting('wal_segment_size'))":
        print(16 * 1024 * 1024)
    elif "pg_stat_archiver" in query:
        now = Decimal(os.environ.get("BACKUP_LAB_DB_NOW", "1789041600"))
        last_ok = Decimal(os.environ.get("BACKUP_LAB_LAST_OK", "1789038000"))
        last_fail = Decimal(os.environ.get("BACKUP_LAB_LAST_FAIL", "0"))
        rounding = ROUND_FLOOR if "floor(extract" in query else ROUND_HALF_UP
        epoch = lambda value: str(value.to_integral_value(rounding=rounding))
        frontier = os.environ.get("BACKUP_LAB_FRONTIER", WAL)
        row = f"on|{frontier}|{epoch(last_ok)}|{epoch(last_fail)}|0|{SYSTEM_ID}"
        if "clock_timestamp()" in query:
            row += f"|{'t' if max(last_ok, last_fail) > now else 'f'}|{epoch(now)}"
            row += f"|{'t' if last_fail > last_ok else 'f'}"
        print(row)
    elif "pg_snapshot_xmax" in query:
        print("1000|00000001")
    elif "CREATE TABLE IF NOT EXISTS sentinel_backup_recovery_markers" in query:
        return event("marker-row", lambda: 0)
    elif "pg_current_wal_lsn()::text" in query:
        marker = re.search(r"SELECT '([^|]+)\|'", query).group(1)
        print(f"{marker}|0/03000040|{WAL}")
    elif "pg_switch_wal" in query:
        print("0/04000000")
    elif "j->'WAL-Ranges'" in query:
        path = re.search(r"pg_read_file\('([^']+)'\)", query).group(1)
        record = json.loads(Path(path).read_text())["WAL-Ranges"][-1]
        print(f"{record['Timeline']}|{record['End-LSN']}")
    else:
        raise AssertionError("unexpected simulated SQL: " + query)
    return 0


def basebackup():
    path = Path(args[args.index("-D") + 1])
    path.mkdir()
    data = path / "relation-data"
    data.write_bytes(b"complete-base-backup-data")
    manifest = {
        "WAL-Ranges": [{"Timeline": 1, "End-LSN": "0/03000040"}],
        "Synthetic-Data-SHA256": hashlib.sha256(data.read_bytes()).hexdigest(),
    }
    (path / "backup_manifest").write_text(json.dumps(manifest, sort_keys=True))
    (path / "backup_label").write_text("simulated-base")
    return 0


def verify():
    path = Path(args[-1])
    try:
        manifest = json.loads((path / "backup_manifest").read_text())
        expected = manifest["Synthetic-Data-SHA256"]
    except (OSError, KeyError, TypeError, ValueError):
        print("simulated manifest checksum mismatch", file=sys.stderr)
        return 1
    if expected != hashlib.sha256((path / "relation-data").read_bytes()).hexdigest():
        print("simulated manifest checksum mismatch", file=sys.stderr)
        return 1
    return 0


def shell(command):
    mapped = [part.replace("/sentinel-backup", str(MEDIA)) for part in command]
    return subprocess.call(mapped)


def _python_chain_probe(*, base, system_id, last_wal, segment_size):
    helper = ROOT / "repo" / "scripts" / "sentinel-backup-verify-chain.py"
    result = subprocess.run([
        sys.executable, str(helper),
        "--root", str(MEDIA),
        "--base", base,
        "--system-id", system_id,
        "--last-wal", last_wal,
        "--segment-size", segment_size,
    ], capture_output=True, text=True)
    if result.stdout:
        sys.stdout.write(result.stdout)
    if result.stderr:
        sys.stderr.write(result.stderr)
    return result.returncode


def runtime_backup_probe():
    base = args[args.index("--base") + 1]
    result = subprocess.run([
        sys.executable, str(ROOT / "repo" / "scripts" / "sentinel-backup-verify-chain.py"),
        "--root", str(MEDIA),
        "--base", base,
        "--system-id", SYSTEM_ID,
        "--last-wal", WAL,
        "--segment-size", str(16 * 1024 * 1024),
    ], capture_output=True, text=True)
    if result.stdout:
        print("backup_runtime_authority_ready:true " + result.stdout.strip())
    if result.stderr:
        sys.stderr.write(result.stderr)
    return result.returncode


def docker():
    if args[:1] == ["compose"]:
        if ("run" in args and "sentinel.backup_runtime_probe" in args
                and "sentinel-postgres" not in args):
            return event("runtime-backup-probe", runtime_backup_probe)
        index = args.index("sentinel-postgres")
        command = args[index + 1:]
        source = " ".join(command)
        stage = "compose-read"
        if 'metadata="/sentinel-backup/base/$staging/sentinel-pitr-base-identity"' in source:
            stage = "base-identity"
        elif 'metadata="/sentinel-backup/base/$name/sentinel-recovery-marker"' in source:
            stage = "marker-file"
        elif "mv -T --no-clobber" in source:
            stage = "base-publish"
        elif 'namespace="$1" wal="$2"' in source:
            stage = "wal-proof"
        elif command[:3] == ["stat", "-c", "%Y"]:
            stage = "status-manifest-stat"
        elif command[:3] == ["bash", "-s", "--"] and len(command) == 8:
            stage = "wal-chain-proof"
            # Execute the actual stdin validator used by production status.
            # Map only the container mount; psql remains the SQL boundary double.
            script = sys.stdin.read().replace("/sentinel-backup", str(MEDIA))
            return event(stage, lambda: subprocess.run(
                command, input=script, text=True).returncode)
        elif command[:3] == ["sh", "-s", "--"]:
            stage = "metadata-access"
        return event(stage, lambda: shell(command))
    if args[:2] in (["volume", "create"], ["network", "create"]):
        if args[0] == "volume":
            (ROOT / "volumes" / args[-1]).mkdir(parents=True)
        return 0
    if args[:2] in (["volume", "rm"], ["network", "rm"], ["rm", "-f"]):
        return event("cleanup", lambda: 0)
    if args[:1] == ["run"]:
        assert "--network" in args
        if "-d" in args:
            return event("restore-start", lambda: 79)
        command = args[args.index("-ceu"):]
        source = command[1]
        mappings = {}
        for i, arg in enumerate(args):
            if arg == "-v":
                origin, destination, *mode = args[i + 1].split(":")
                assert destination in {"/source", "/target"}, destination
                if not origin.startswith("/"):
                    origin = str(ROOT / "volumes" / origin)
                mappings[destination] = origin
        for destination, origin in mappings.items():
            source = source.replace(destination, origin)
        # The real shell copies and verifies. Ownership requires real Docker,
        # covered by the physical gate, so remove only those commands here.
        source = re.sub(r"^\s*chown .*", "", source, flags=re.MULTILINE)
        return event("restore-copy", lambda: subprocess.call(["sh", "-ceu", source]))
    raise AssertionError("unexpected simulated Docker invocation: " + repr(args))


if name == "docker":
    sys.exit(docker())
elif name == "psql":
    sys.exit(sql())
elif name == "pg_basebackup":
    sys.exit(event("base-copy", basebackup))
elif name == "pg_verifybackup":
    sys.exit(event("base-verify", verify))
elif name == "date":
    if args == ["+%s"]:
        count_file = ROOT / "clock-reads"
        count = int(count_file.read_text()) if count_file.exists() else 0
        count_file.write_text(str(count + 1))
        # A generation published while the status command is enumerating it.
        if os.environ.get("BACKUP_LAB_PUBLISH_DURING_STATUS"):
            observed = any(json.loads(line)["stage"] == "status-manifest-stat"
                           for line in (ROOT / "events.jsonl").read_text().splitlines())
            print(1789041601 if observed else 1789041600)
        else:
            print(int(Decimal(os.environ.get("BACKUP_LAB_DB_NOW", "1789041600"))))
    else:
        print("20260910T120000Z")
elif name == "sleep":
    pass  # No wall-clock delay in the finite archive polling loop.
elif name == "id":
    # Ownership authority is exercised by the mandatory real Docker gate.
    assert args in (["-u"], ["-g", "postgres"])
    print(0 if args == ["-u"] else os.getgid())
elif name == "chown":
    pass  # The temporary filesystem has the invoking test user's ownership.
elif name == "stat":
    if args[:2] == ["-c", "%u"]:
        print(0)  # Container-root ownership; real authority has a Docker gate.
    else:
        os.execv(shutil.which("stat", path=os.defpath), ["stat", *args])
else:
    raise AssertionError("unexpected command " + name)
