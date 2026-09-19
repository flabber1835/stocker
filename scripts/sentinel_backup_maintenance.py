#!/usr/bin/env python3
"""One bounded, broker-free backup maintenance tick for a host scheduler."""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import math
import os
from pathlib import Path
import re
import selectors
import signal
import subprocess
import sys
import time

import sentinel_backup_lock as backup_lock

ROOT = Path(__file__).resolve().parents[1]
MAX_OUTPUT = 256 * 1024
RENEW_AGE_HOURS = 24
# Keep these tied to the runtime ceilings by a production-policy test.
RENEW_WAL_BYTES = 512 * 1024 * 1024
RENEW_WAL_OBJECTS = 512
REPAIRABLE = frozenset({
    "BASE_BACKUP_STALE", "WAL_ARCHIVE_STALE", "BASE_BACKUP_MISSING",
    "BASE_BACKUP_NOT_FOUND", "WAL_ARCHIVE_UNINITIALIZED",
    "WAL_ARCHIVE_UNRESOLVED_FAILURE", "BASE_BACKUP_RUNTIME_HORIZON_EXCEEDED",
})


@dataclass(frozen=True)
class Result:
    returncode: int
    stdout: str


def run_bounded(argv, *, env=None, timeout=900.0, private_group=True):
    """Bound process exit, pipe reads and output; reap private descendants."""
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("maintenance timeout must be positive and finite")
    deadline = time.monotonic() + timeout
    output = bytearray()
    values = os.environ if env is None else env
    fds = ()
    if backup_lock.lock_is_held(values):
        fds = (int(values[backup_lock.LOCK_FD_ENV]),)
    process = subprocess.Popen(
        list(argv), cwd=str(ROOT), env=env, stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        start_new_session=private_group, pass_fds=fds)
    try:
        with selectors.DefaultSelector() as selector:
            os.set_blocking(process.stdout.fileno(), False)
            selector.register(process.stdout, selectors.EVENT_READ)
            while selector.get_map():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return Result(124, output.decode("utf-8", errors="replace") +
                                  "\nMAINTENANCE_DEADLINE_EXCEEDED\n")
                for key, _ in selector.select(min(remaining, 0.2)):
                    chunk = os.read(key.fileobj.fileno(), 8192)
                    if not chunk:
                        selector.unregister(key.fileobj)
                    elif len(output) + len(chunk) > MAX_OUTPUT:
                        return Result(125, "MAINTENANCE_OUTPUT_LIMIT_EXCEEDED\n")
                    else:
                        output.extend(chunk)
            try:
                code = process.wait(timeout=max(0.001, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                return Result(124, "MAINTENANCE_DEADLINE_EXCEEDED\n")
        return Result(code, output.decode("utf-8", errors="replace"))
    finally:
        if private_group:
            # Even an exited parent may leave a descendant holding a pipe or
            # lock. Never carry that work into the next scheduler invocation.
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        elif process.poll() is None:
            process.kill()
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            pass  # Outer group supervisor still enforces the invocation limit.
        process.stdout.close()


def reason_for_renewal(result):
    if result.returncode:
        reasons = re.findall(r"^SENTINEL_BACKUP_STATUS_REASON=([A-Z0-9_]+)$",
                             result.stdout, flags=re.MULTILINE)
        if result.returncode == 4 and len(reasons) == 1 and reasons[0] in REPAIRABLE:
            return reasons[0]
        raise ValueError("backup status has no repairable freshness verdict")
    # The machine record is emitted only after full base/WAL verification.
    records = re.findall(
        r"^backup_maintenance: age_seconds=(\d+) wal_segments=(\d+) "
        r"wal_segment_bytes=(\d+)$", result.stdout, flags=re.MULTILINE)
    if len(records) != 1:
        raise ValueError("backup maintenance evidence is missing or duplicated")
    age, segments, size = map(int, records[0])
    if segments < 1 or size < 1 or size > 2**32 or 2**32 % size:
        raise ValueError("backup maintenance WAL geometry is invalid")
    if age >= RENEW_AGE_HOURS * 3600:
        return "DAILY_RENEWAL"
    if segments >= RENEW_WAL_OBJECTS or segments * size >= RENEW_WAL_BYTES:
        return "PROACTIVE_WAL_ROLLOVER"
    return None


def maintain(run, *, backup_root):
    """Recompute work from verified artifacts, never a cached success flag."""
    status = run(["bash", "scripts/sentinel-backup-status.sh"])
    reason = reason_for_renewal(status)
    if reason is None:
        return Result(0, "backup_maintenance: HEALTHY\n")
    created = run(["bash", "scripts/sentinel-base-backup.sh"])
    if created.returncode:
        return Result(created.returncode, "backup_maintenance: RENEWAL_FAILED\n" + created.stdout)
    paths = re.findall(r"^verified_base_backup:(.+)$", created.stdout, re.MULTILINE)
    if len(paths) != 1:
        raise ValueError("producer did not return one verified backup")
    path = Path(paths[0])
    if (path.parent != Path(backup_root) / "base"
            or re.fullmatch(r"base-\d{8}T\d{6}Z", path.name) is None):
        raise ValueError("producer returned a backup outside the durable target")
    verified = run(["bash", "scripts/sentinel-backup-status.sh", "--backup", str(path)])
    if verified.returncode:
        return Result(verified.returncode, "backup_maintenance: VERIFICATION_FAILED\n" + verified.stdout)
    if reason_for_renewal(verified) is not None:
        return Result(4, "backup_maintenance: NEW_BASE_HAS_NO_RENEWAL_HEADROOM\n")
    return Result(0, "backup_maintenance: RENEWED reason=" + reason + "\n" + verified.stdout)


def emit_result(result):
    """A full scheduler log pipe cannot defeat the work deadline."""
    child = subprocess.Popen(
        [sys.executable, "-c", "import sys; sys.stdout.buffer.write(sys.stdin.buffer.read()); "
         "sys.stdout.buffer.flush()"], stdin=subprocess.PIPE)
    try:
        child.communicate(result.stdout.encode("utf-8"), timeout=1)
        return child.returncode == 0
    except subprocess.TimeoutExpired:
        return False
    finally:
        if child.poll() is None:
            child.kill()
        try:
            child.wait(timeout=1)
        except subprocess.TimeoutExpired:
            pass  # Host monitoring must handle uninterruptible kernel I/O.
        child.stdin.close()


def _main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeout-seconds", type=float, default=900)
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if not math.isfinite(args.timeout_seconds) or not 1 <= args.timeout_seconds <= 3600:
        parser.error("timeout must be finite and between 1 and 3600 seconds")
    if not args.worker:
        result = run_bounded(["bash", "scripts/sentinel-backup-maintenance-entry.sh"],
                             timeout=args.timeout_seconds)
    else:
        if not backup_lock.lock_is_held():
            print("REFUSED: maintenance requires the inherited physical-backup lock", file=sys.stderr)
            return 2
        env = {key: value for key, value in os.environ.items()
               if not key.startswith(("ALPACA_", "APCA_"))}
        try:
            result = maintain(lambda command: run_bounded(
                command, env=env, timeout=600, private_group=False),
                backup_root=env[backup_lock.LOCK_ROOT_ENV])
        except ValueError as exc:
            result = Result(4, "REFUSED: " + str(exc) + "\n")
    return result.returncode if emit_result(result) else (result.returncode or 4)


def _interrupt(signum, _frame):
    # Unwind run_bounded so a scheduler stop also reaps its private group.
    raise SystemExit(128 + signum)


def main(argv=None):
    previous = {sig: signal.signal(sig, _interrupt)
                for sig in (signal.SIGTERM, signal.SIGINT)}
    try:
        return _main(argv)
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)


if __name__ == "__main__":
    raise SystemExit(main())
