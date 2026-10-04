"""Ephemeral Linux process evidence; never authority to acknowledge work."""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
import time

ACTIVE_FILE = Path('/tmp/sentinel-shadow-active-worker.json')
SCHEMA = 'sentinel.shadow-supervisor-active/1'


def _read(path: Path) -> dict:
    with path.open(encoding='utf-8') as stream:
        value = json.loads(stream.read(8193))
    if not isinstance(value, dict):
        raise ValueError('process evidence must be an object')
    return value


def _process(pid: int) -> dict:
    # /proc stat predates Linux 3.10; fdinfo lock reporting is not required.
    if type(pid) is not int or pid < 1:
        raise ValueError('invalid process identity')
    stat = Path(f'/proc/{pid}/stat').read_text()
    fields = stat[stat.rindex(')') + 2:].split()
    if fields[0] in {'Z', 'X', 'x'}:
        raise ValueError('process is no longer live')
    return {'pid': pid, 'parent_pid': int(fields[1]), 'start_ticks': int(fields[19])}


def _boot() -> str:
    return Path('/proc/sys/kernel/random/boot_id').read_text().strip()


def record(attempt: str, supervisor_pid: int, child_pid: int, deadline: float) -> None:
    parent, child = _process(supervisor_pid), _process(child_pid)
    if child['parent_pid'] != supervisor_pid:
        raise ValueError('worker is not the supervised child')
    payload = {'schema': SCHEMA, 'attempt_id': attempt, 'boot_id': _boot(),
               'supervisor': parent, 'worker': child, 'deadline_monotonic': deadline}
    temporary = ACTIVE_FILE.with_name(ACTIVE_FILE.name + '.' + attempt)
    try:
        with temporary.open('x', encoding='utf-8') as stream:
            json.dump(payload, stream, sort_keys=True)
        os.replace(temporary, ACTIVE_FILE)
    finally:
        temporary.unlink(missing_ok=True)


def matches(pending_path: Path) -> bool:
    try:
        pending, active = _read(pending_path), _read(ACTIVE_FILE)
        attempt = pending.get('attempt_id')
        deadline = active.get('deadline_monotonic')
        if (pending.get('schema') != 'sentinel.shadow-supervisor-pending/2'
                or not isinstance(attempt, str) or len(attempt) != 32
                or active.get('schema') != SCHEMA or active.get('attempt_id') != attempt
                or active.get('boot_id') != _boot()
                or type(deadline) not in {int, float} or not math.isfinite(deadline)
                or time.monotonic() > deadline):
            return False
        parent, child = active['supervisor'], active['worker']
        return (parent == _process(parent['pid']) and child == _process(child['pid'])
                and child['parent_pid'] == parent['pid'])
    except (OSError, ValueError, KeyError, TypeError, IndexError):
        return False


def clear() -> None:
    ACTIVE_FILE.unlink(missing_ok=True)
