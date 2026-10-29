"""Typed, finite corpus-pin waits for activation's read-only observations."""
from __future__ import annotations

import json
import math
import subprocess
import time

import sentinel_autonomous_deploy as core
from sentinel_go_process import owned_command

WAIT_EXIT = 75
WAIT_MARKER = 'SENTINEL_ACTIVATION_READ_WAIT='
WAIT_OUTPUT = WAIT_MARKER + json.dumps(
    {'schema': 'sentinel.activation-read-wait/1', 'reason': 'CORPUS_LOCK_BUSY'},
    sort_keys=True, separators=(',', ':'))


def child_code(code):
    """Catch only the real failed read-pin type, after the probe's own cleanup."""
    return (
        'from sentinel.feed.publication import CorpusLockUnavailable as _ActivationCorpusBusy\n'
        'try:\n'
        '    exec(compile(' + repr(code) + ', "activation read probe", "exec"))\n'
        'except _ActivationCorpusBusy as _activation_busy:\n'
        '    if type(_activation_busy) is not _ActivationCorpusBusy:\n'
        '        raise\n'
        '    print(' + repr(WAIT_OUTPUT) + ', flush=True)\n'
        '    raise SystemExit(' + str(WAIT_EXIT) + ')\n')


def run(deploy, command, label, *, deadline=None, timeout=None, allowed_returncodes=(),
        budget_seconds=None):
    """Retry one pure observation, never a lifecycle phase or financial writer."""
    now = time.monotonic()
    seconds = (getattr(deploy.cfg, 'health_timeout', 300)
               if budget_seconds is None else budget_seconds)
    if type(seconds) not in (int, float) or not math.isfinite(seconds) or seconds <= 0:
        raise core.DeployRefused('activation read timeout is invalid')
    limit = now + min(300, seconds)
    if timeout is not None:
        if type(timeout) not in (int, float) or not math.isfinite(timeout):
            raise core.DeployRefused('activation read caller timeout is invalid')
        if timeout <= 0:
            raise core.ActivationPending(label + ' has no remaining read budget')
        limit = min(limit, now + timeout)
    for absolute in (deadline, getattr(deploy, '_causal_wait_deadline', None)):
        if absolute is not None:
            if type(absolute) not in (int, float) or not math.isfinite(absolute):
                raise core.DeployRefused('activation read deadline is invalid')
            limit = min(limit, absolute)
    while True:
        remaining = limit - time.monotonic()
        if remaining <= 0:
            raise core.ActivationPending(label + ' corpus wait deadline exhausted')
        try:
            with owned_command(command) as owner:
                completed = deploy.runner.run(owner['command'], capture=True, check=False,
                                             timeout=remaining)
        except core.DeployRefused:
            raise
        except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
            raise core.DeployRefused(label + ' read command or owned cleanup failed') from exc
        output = completed.stdout or ''
        if WAIT_MARKER in (getattr(completed, 'stderr', '') or ''):
            raise core.DeployRefused(label + ' contention response used an invalid channel')
        busy = completed.returncode == WAIT_EXIT and output.strip() == WAIT_OUTPUT
        if completed.returncode == WAIT_EXIT and not busy:
            raise core.DeployRefused(label + ' contention response is malformed')
        if not busy and WAIT_MARKER in output:
            raise core.DeployRefused(label + ' contention response contradicts command status')
        if not busy and completed.returncode not in (0, *allowed_returncodes):
            raise core.DeployRefused(label + ' command refused (exit %s)' % completed.returncode)
        if time.monotonic() >= limit:
            raise core.ActivationPending(label + ' corpus wait deadline exhausted')
        if not busy:
            return completed
        time.sleep(min(1, max(0, limit - time.monotonic())))
