"""Stdlib-only finite filesystem snapshot; authentication stays canonical."""
from pathlib import Path

MAX_BYTES = 8192


def raw(path):
    with path.open('rb') as stream:
        value = stream.read(MAX_BYTES+1)
    if len(value) > MAX_BYTES:
        raise ValueError('worker status exceeds its bound')
    return value


def optional(path):
    try:
        return raw(path)
    except FileNotFoundError:
        return None


def observe(state_dir: Path):
    critical = state_dir/'shadow-supervisor-critical.json'
    if critical.exists():
        return {'critical': True, 'pending': None, 'status': None, 'latest_pending': None}
    pending = optional(state_dir/'shadow-supervisor-pending.json')
    value = raw(state_dir/'shadow-service-status.json')
    if critical.exists():
        return {'critical': True, 'pending': None, 'status': None, 'latest_pending': None}
    latest = optional(state_dir/'shadow-supervisor-pending.json')
    return {'critical': False, 'pending': pending, 'status': value, 'latest_pending': latest}
