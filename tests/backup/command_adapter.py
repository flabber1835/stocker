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
        print(f"on|{WAL}|1789038000|0|0|{SYSTEM_ID}")
    elif "pg_snapshot_xmax" in query:
        print("1000|00000001")
    elif "CREATE TABLE IF NOT EXISTS sentinel_backup_recovery_markers" in query:
        return event("marker-row", lambda: 0)
    elif "pg_current_wal_lsn()::text" in query:
        marker = re.search(r"SELECT '([^|]+)\|'", query).group(1)
        print(f"{marker}|0/300040|{WAL}")
    elif "pg_switch_wal" in query:
        print("0/400000")
    else:
        raise AssertionError("unexpected simulated SQL: " + query)
    return 0


def basebackup():
    path = Path(args[args.index("-D") + 1])
    path.mkdir()
    data = path / "relation-data"
    data.write_bytes(b"complete-base-backup-data")
    (path / "backup_manifest").write_text(hashlib.sha256(data.read_bytes()).hexdigest())
    (path / "backup_label").write_text("simulated-base")
    return 0


def verify():
    path = Path(args[-1])
    if (path / "backup_manifest").read_text() != hashlib.sha256(
            (path / "relation-data").read_bytes()).hexdigest():
        print("simulated manifest checksum mismatch", file=sys.stderr)
        return 1
    return 0


def shell(command):
    mapped = [part.replace("/sentinel-backup", str(MEDIA)) for part in command]
    return subprocess.call(mapped)


def docker():
    if args[:1] == ["compose"]:
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
    print("1789041600" if args == ["+%s"] else "20260910T120000Z")
elif name == "sleep":
    pass  # No wall-clock delay in the finite archive polling loop.
else:
    raise AssertionError("unexpected command " + name)
