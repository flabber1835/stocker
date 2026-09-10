"""Strict environmental adapters; production code owns every safety decision."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys

ROOT = Path(os.environ.get("SENTINEL_REPO_ROOT", Path(__file__).resolve().parents[2]))
MARKER = ".sentinel-independent-durable-target-v1"
CONTENT = "sentinel-independent-durable-target-v1\n"
SYSTEM_ID = 7377777777777777777
SEGMENT_SIZE = 1024 * 1024
NOW = datetime(2026, 9, 10, 12, tzinfo=timezone.utc)
BASE = "base-20260910T110000Z"


def wal_name(index: int, timeline: int = 1) -> str:
    log, segment = divmod(index, 4096)
    return f"{timeline:08X}{log:08X}{segment:08X}"


class Media:
    """Sparse files represent physical size; archive subprocess tests use bytes."""
    def __init__(self, root: Path):
        self.root = root
        self.wal = root / "wal"
        self.base = root / "base"
        self.namespace = self.wal / f"cluster-{SYSTEM_ID}"
        self.namespace.mkdir(parents=True)
        self.base.mkdir()
        for parent in (self.wal, self.base):
            (parent / MARKER).write_text(CONTENT)
        self.backup = self.base / BASE
        self.backup.mkdir()
        self.metadata = (
            f"marker=sentinel-backup-20260910T110000Z-42\nlsn=0/300040\n"
            f"wal={wal_name(3)}\nsystem_identifier={SYSTEM_ID}\n")
        (self.backup / "sentinel-recovery-marker").write_text(self.metadata)
        (self.backup / "sentinel-pitr-base-identity").write_text(
            f"schema=sentinel.base-backup-pitr/2\nsystem_identifier={SYSTEM_ID}\n")
        (self.backup / "backup_label").write_text("synthetic observation fixture")
        (self.backup / "backup_manifest").write_text(json.dumps({
            "WAL-Ranges": [{"Timeline": 1, "End-LSN": "0/200040"}],
        }))
        for i in range(2, 6):
            self.segment(i)

    def segment(self, index: int):
        path = self.namespace / wal_name(index)
        with path.open("wb") as handle:
            handle.truncate(SEGMENT_SIZE)
        return path

    def path(self, absolute: str) -> Path:
        prefix = "/sentinel-backup/"
        assert absolute.startswith(prefix), absolute
        relative = Path(absolute.removeprefix(prefix))
        assert ".." not in relative.parts, absolute
        return self.root / relative


class Database:
    """Only known SELECT statements are accepted. No production policy is mocked."""
    def __init__(self, media: Media):
        self.media = media
        self.now = NOW
        self.last_ok = NOW - timedelta(seconds=10)
        self.last_fail = None
        self.failed_count = 0
        self.mode = "on"
        self.system_id = SYSTEM_ID
        self.frontier = wal_name(5)
        self.statements = []

    def cursor(self):
        return Cursor(self)


class Cursor:
    def __init__(self, db):
        self.db = db
        self.rows = []

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def execute(self, sql, params=()):
        self.db.statements.append((sql, params))
        query = " ".join(sql.split())
        db = self.db
        self.rows = []
        if query == "SELECT system_identifier::text FROM pg_control_system()":
            self.rows = [(str(db.system_id),)]
        elif query.startswith("SELECT pg_read_file(%s,0,1048576,"):
            path = db.media.path(params[0])
            if path.exists():
                self.rows = [(path.read_text(),)]
            elif params[1]:
                self.rows = [(None,)]
            else:
                raise FileNotFoundError(path)
        elif query == "SELECT pg_ls_dir(%s)":
            self.rows = [(p.name,) for p in db.media.path(params[0]).iterdir()]
        elif query.startswith("SELECT (j->'WAL-Ranges'"):
            data = json.loads(db.media.path(params[0]).read_text())
            record = data.get("WAL-Ranges", [{}])[-1]
            self.rows = [(record.get("Timeline"), record.get("End-LSN"))]
        elif query.startswith("SELECT name,(pg_stat_file"):
            paths = db.media.path(params[1]).iterdir()
            self.rows = [(p.name, p.stat().st_size) for p in paths
                         if len(p.name) == 24 and all(c in "0123456789ABCDEF" for c in p.name)]
        elif query.startswith("SELECT current_setting('archive_mode')"):
            self.rows = [(db.mode, db.last_ok, db.last_fail, db.failed_count, db.now)]
        elif query.startswith("SELECT last_archived_wal,last_archived_time,last_failed_time,"):
            last = SEGMENT_SIZE if "wal_segment_size" in query else db.failed_count
            self.rows = [(db.frontier, db.last_ok, db.last_fail, last)]
        elif query.startswith("SELECT (pg_stat_file(%s,true)).size"):
            path = db.media.path(params[0])
            self.rows = [(path.stat().st_size if path.exists() else None, SEGMENT_SIZE)]
        elif query.startswith("SELECT pg_create_restore_point("):
            self.rows = [("0/500040",)]
        elif query == "SELECT pg_walfile_name(pg_switch_wal())":
            self.rows = [(wal_name(6),)]
        else:
            raise AssertionError(f"Unexpected SQL in backup adapter: {query}")

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def fetchall(self):
        return self.rows


class Archive:
    def __init__(self, root: Path):
        self.root = root
        self.archive = root / "archive"
        self.archive.mkdir(parents=True)
        (self.archive / MARKER).write_text(CONTENT)
        self.source = root / "source"
        self.source.write_bytes(b"\0" * 24 + struct.pack("=Q", SYSTEM_ID) + b"known-wal" * 1024)
        self.name = wal_name(3)
        self.namespace = self.archive / f"cluster-{SYSTEM_ID}"
        self.namespace.mkdir()
        self.target = self.namespace / self.name
        self.bin = root / "bin"
        self.bin.mkdir()
        # Construct a minimal, credential-free child environment.
        self.env = {"PATH": os.environ["PATH"], "LANG": "C", "LC_ALL": "C"}

    def fault(self, command: str, phase: str, mode: str):
        original = shutil.which(command)
        assert original
        wrapper = self.bin / command
        wrapper.write_text(f"#!{sys.executable}\n" + (
            "import os, pathlib, signal, subprocess, sys\n"
            f"original={original!r}\nphase={phase!r}\nmode={mode!r}\n"
            "args=sys.argv[1:]\n"
            "target=pathlib.Path(args[-1])\n"
            "is_temporary='.part.' in target.name\n"
            "hit=(phase=='any' or phase=='temporary' and is_temporary or "
            "phase=='final' and target.is_file() and not is_temporary or "
            "phase=='directory' and target.is_dir())\n"
            "if not hit: os.execv(original,[original,*args])\n"
            "if mode=='fail-before': sys.exit(73)\n"
            "rc=subprocess.call([original,*args])\n"
            "if rc: sys.exit(rc)\n"
            "if mode=='corrupt':\n"
            "    with target.open('r+b') as f: f.seek(40); f.write(b'BAD')\n"
            "    sys.exit(0)\n"
            "if mode=='kill': os.kill(os.getppid(),signal.SIGKILL)\n"
            "sys.exit(74)\n"
        ))
        wrapper.chmod(0o755)
        self.env["PATH"] = f"{self.bin}{os.pathsep}{os.environ['PATH']}"

    def clear(self):
        self.env["PATH"] = os.environ["PATH"]

    def command(self):
        return ["sh", str(ROOT / "scripts/sentinel-archive-wal.sh"),
                str(self.source), self.name, str(self.archive)]

    def run(self):
        return subprocess.run(self.command(), env=self.env, capture_output=True,
                              text=True, timeout=10)

    def assert_exact(self):
        assert self.target.read_bytes() == self.source.read_bytes()
