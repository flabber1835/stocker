#!/usr/bin/env python3
"""Bounded process transport for the canonical recurring backup coordinator."""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import math
import os
from pathlib import Path
import selectors
import signal
import subprocess
import sys
import tempfile
import time

import sentinel_backup_lock as backup_lock

ROOT = Path(__file__).resolve().parents[1]
MAX_OUTPUT = 256 * 1024

@dataclass(frozen=True)
class Result:
    returncode: int
    stdout: str
    stderr: str = ''


def run_bounded(argv, *, env=None, timeout=900.0, private_group=True, stdin=None):
    """Bound process exit, pipe reads and output; reap private descendants."""
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("maintenance timeout must be positive and finite")
    deadline = time.monotonic() + timeout
    output, errors = bytearray(), bytearray()
    values = os.environ if env is None else env
    fds = ()
    if backup_lock.lock_is_held(values):
        fds = (int(values[backup_lock.LOCK_FD_ENV]),)
    # Requests are small JSON receipts. A file avoids blocking on a child's
    # unread stdin before the output/deadline selector starts.
    with tempfile.TemporaryFile() as request:
        raw = b'' if stdin is None else stdin.encode('utf-8')
        if len(raw) > MAX_OUTPUT:
            raise ValueError('maintenance input exceeds bound')
        request.write(raw)
        request.seek(0)
        process = subprocess.Popen(
            list(argv), cwd=str(ROOT), env=env, stdin=request,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            start_new_session=private_group, pass_fds=fds)
    try:
        with selectors.DefaultSelector() as selector:
            for stream, buffer in ((process.stdout, output), (process.stderr, errors)):
                os.set_blocking(stream.fileno(), False)
                selector.register(stream, selectors.EVENT_READ, buffer)
            while selector.get_map():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return Result(124, output.decode("utf-8", errors="replace") +
                                  "\nMAINTENANCE_DEADLINE_EXCEEDED\n")
                for key, _ in selector.select(min(remaining, 0.2)):
                    chunk = os.read(key.fileobj.fileno(), 8192)
                    if not chunk:
                        selector.unregister(key.fileobj)
                    elif len(output) + len(errors) + len(chunk) > MAX_OUTPUT:
                        return Result(125, "MAINTENANCE_OUTPUT_LIMIT_EXCEEDED\n")
                    else:
                        key.data.extend(chunk)
            try:
                code = process.wait(timeout=max(0.001, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                return Result(124, "MAINTENANCE_DEADLINE_EXCEEDED\n")
        return Result(code, output.decode("utf-8", errors="replace"),
                      errors.decode("utf-8", errors="replace"))
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
        process.stderr.close()


def emit_result(result):
    """A full scheduler log pipe cannot defeat the work deadline."""
    child = subprocess.Popen(
        [sys.executable, "-c", "import json,sys; output,error=json.load(sys.stdin); "
         "sys.stdout.write(output); sys.stdout.flush(); "
         "sys.stderr.write(error); sys.stderr.flush()"], stdin=subprocess.PIPE)
    try:
        child.communicate(json.dumps([result.stdout, result.stderr]).encode("utf-8"), timeout=1)
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


def _interrupt(signum, _frame):
    raise SystemExit(128 + signum)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--timeout-seconds', type=float, default=3600)
    args, forwarded = parser.parse_known_args(argv)
    if not math.isfinite(args.timeout_seconds) or not 1 <= args.timeout_seconds <= 3600:
        parser.error('timeout must be finite and between 1 and 3600 seconds')
    previous = {sig: signal.signal(sig, _interrupt)
                for sig in (signal.SIGTERM, signal.SIGINT)}
    try:
        result = run_bounded(['bash', 'scripts/sentinel-backup-maintenance-entry.sh', *forwarded],
                             timeout=args.timeout_seconds)
        return result.returncode if emit_result(result) else (result.returncode or 4)
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)


if __name__ == '__main__':
    raise SystemExit(main())
