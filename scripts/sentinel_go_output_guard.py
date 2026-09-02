#!/usr/bin/env python3
"""Stream one GO subprocess while removing actual configured secret values.

The supported shell launcher uses this boundary for production diagnostics that
may contain child exception text.  It preserves live stdout/stderr and the child
exit code while ensuring configured authority values cannot reach the terminal
or CI logs even when an exception prints a bare secret with no identifying key.
"""
from __future__ import annotations

import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
from typing import Mapping, Sequence

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import sentinel_go_validate as go  # noqa: E402


_EXTRA_SECRET_NAMES = frozenset({
    "SENTINEL_GO_RUN_TOKEN",
})
_REPLACEMENT = "[REDACTED]"


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
    if (getattr(sys.stdout, "isatty", lambda: False)()
            and not child_env.get("NO_COLOR")
            and "SENTINEL_GO_COLOR" not in child_env):
        child_env["SENTINEL_GO_COLOR"] = "1"

    try:
        proc = subprocess.Popen(
            [str(item) for item in command],
            cwd=str(go.ROOT),
            env=child_env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
    except OSError:
        print("REFUSED: guarded GO subprocess could not start", file=sys.stderr)
        return 127

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

    threads = [
        threading.Thread(target=pump, args=(proc.stdout, sys.stdout), daemon=True),
        threading.Thread(target=pump, args=(proc.stderr, sys.stderr), daemon=True),
    ]
    for thread in threads:
        thread.start()

    previous = {}

    def forward(signum, _frame) -> None:
        try:
            proc.send_signal(signum)
        except OSError:
            pass

    for signum in (signal.SIGINT, signal.SIGTERM):
        previous[signum] = signal.getsignal(signum)
        signal.signal(signum, forward)

    try:
        rc = proc.wait()
    finally:
        for signum, handler in previous.items():
            signal.signal(signum, handler)
        for thread in threads:
            thread.join(timeout=2)
    return int(rc)


def main(argv=None) -> int:
    return run_guarded(list(argv if argv is not None else sys.argv[1:]))


if __name__ == "__main__":
    raise SystemExit(main())
