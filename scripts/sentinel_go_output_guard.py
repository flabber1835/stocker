#!/usr/bin/env python3
"""Stream one GO subprocess while removing actual configured secret values.

The supported shell launcher uses this boundary for production diagnostics that
may contain child exception text. It preserves live stdout/stderr, the child exit
code, and the inherited verified lifecycle-lock descriptor while ensuring
configured authority values cannot reach the terminal or CI logs even when an
exception prints a bare secret with no identifying key.
"""
from __future__ import annotations

import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time
from typing import Mapping, Sequence

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import sentinel_go_lock as go_lock  # noqa: E402
import sentinel_go_validate as go  # noqa: E402


_EXTRA_SECRET_NAMES = frozenset({
    "SENTINEL_GO_RUN_TOKEN",
})
_REPLACEMENT = "[REDACTED]"
_TERMINATION_GRACE_SECONDS = 5.0


def _secret_values(values: Mapping[str, str]) -> tuple[str, ...]:
    names = set(go._SECRET_NAMES) | set(_EXTRA_SECRET_NAMES)
    found = {
        str(values.get(name) or "")
        for name in names
        if str(values.get(name) or "")
    }
    return tuple(sorted(found, key=len, reverse=True))


def redact(text: str, *, secrets: Sequence[str]) -> str:
    value = str(text or "")
    for secret in secrets:
        if secret:
            value = value.replace(secret, _REPLACEMENT)
    return value


def _load_secret_values() -> tuple[str, ...]:
    try:
        values = go.merged_environment()
    except Exception:
        # Failure to establish the configured secret set means this boundary
        # cannot prove that emitted diagnostics are safe.
        raise RuntimeError("GO diagnostic redaction authority unavailable")
    return _secret_values(values)


def _verified_pass_fds(values: Mapping[str, str]) -> tuple[int, ...]:
    """Preserve the exact inherited GO flock descriptor when production owns it."""
    held = str(values.get(go_lock.LOCK_HELD_ENV) or "")
    raw_fd = str(values.get(go_lock.LOCK_FD_ENV) or "")
    if not held and not raw_fd:
        return ()
    if not go_lock.lifecycle_lock_is_held(values):
        raise RuntimeError("GO lifecycle lock authority unavailable")
    try:
        fd = int(raw_fd)
        os.fstat(fd)
    except (OSError, TypeError, ValueError) as exc:
        raise RuntimeError("GO lifecycle lock authority unavailable") from exc
    return (fd,)


def _send_process_group(proc: subprocess.Popen, signum: int) -> None:
    try:
        os.killpg(proc.pid, signum)
    except ProcessLookupError:
        pass
    except OSError:
        pass


def _process_group_alive(proc: subprocess.Popen) -> bool:
    try:
        os.killpg(proc.pid, 0)
    except ProcessLookupError:
        return False
    except OSError:
        return False
    return True


def _escalate_process_group(proc: subprocess.Popen) -> None:
    deadline = time.monotonic() + _TERMINATION_GRACE_SECONDS
    while time.monotonic() < deadline:
        if not _process_group_alive(proc):
            return
        time.sleep(0.05)
    if _process_group_alive(proc):
        _send_process_group(proc, signal.SIGKILL)


def run_guarded(command: Sequence[str]) -> int:
    if not command:
        print("REFUSED: GO output guard requires a command", file=sys.stderr)
        return 2
    try:
        secrets = _load_secret_values()
    except RuntimeError as exc:
        print("REFUSED: %s" % exc, file=sys.stderr)
        return 2

    child_env = dict(os.environ)
    try:
        pass_fds = _verified_pass_fds(child_env)
    except RuntimeError as exc:
        print("REFUSED: %s" % exc, file=sys.stderr)
        return 2
    if (getattr(sys.stdout, "isatty", lambda: False)()
            and not child_env.get("NO_COLOR")
            and "SENTINEL_GO_COLOR" not in child_env):
        child_env["SENTINEL_GO_COLOR"] = "1"

    previous = {}
    termination_started = threading.Event()
    escalation_threads = []
    pending_signals = []
    proc_holder = [None]
    threads = []

    def forward(signum, _frame) -> None:
        proc = proc_holder[0]
        if proc is None:
            pending_signals.append(signum)
            return
        if termination_started.is_set():
            _send_process_group(proc, signal.SIGKILL)
            return
        termination_started.set()
        _send_process_group(proc, signum)
        escalator = threading.Thread(
            target=_escalate_process_group, args=(proc,), daemon=True)
        escalation_threads.append(escalator)
        escalator.start()

    for signum in (signal.SIGINT, signal.SIGTERM):
        previous[signum] = signal.getsignal(signum)
        signal.signal(signum, forward)

    try:
        try:
            proc = subprocess.Popen(
                [str(item) for item in command],
                cwd=str(go.ROOT),
                env=child_env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
                pass_fds=pass_fds,
                start_new_session=True,
            )
        except OSError:
            print("REFUSED: guarded GO subprocess could not start", file=sys.stderr)
            return 127
        proc_holder[0] = proc
        for signum in tuple(pending_signals):
            forward(signum, None)

        write_lock = threading.Lock()

        def pump(stream, target) -> None:
            try:
                for line in iter(stream.readline, ""):
                    safe = redact(line, secrets=secrets)
                    with write_lock:
                        target.write(safe)
                        target.flush()
            finally:
                try:
                    stream.close()
                except OSError:
                    pass

        threads.extend([
            threading.Thread(target=pump, args=(proc.stdout, sys.stdout), daemon=True),
            threading.Thread(target=pump, args=(proc.stderr, sys.stderr), daemon=True),
        ])
        for thread in threads:
            thread.start()

        return int(proc.wait())
    finally:
        for signum, handler in previous.items():
            signal.signal(signum, handler)
        for escalator in escalation_threads:
            escalator.join(timeout=_TERMINATION_GRACE_SECONDS + 1.0)
        for thread in threads:
            thread.join(timeout=2)


def main(argv=None) -> int:
    return run_guarded(list(argv if argv is not None else sys.argv[1:]))


if __name__ == "__main__":
    raise SystemExit(main())
