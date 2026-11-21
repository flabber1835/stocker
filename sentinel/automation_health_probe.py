"""Fresh automation observations over the shared supervised health transport."""
from functools import partial
from pathlib import Path

from sentinel import supervisor_health

PATH = Path('/tmp/sentinel-automation-health.sock')
CLIENT_SECONDS = supervisor_health.CLIENT_SECONDS
READ_SECONDS = supervisor_health.READ_SECONDS
LIMIT = supervisor_health.LIMIT


def probe(path=PATH):
    return supervisor_health.probe(path, client_seconds=CLIENT_SECONDS)


def _observe(database_url, lease_seconds):
    from sentinel.automation_liveness import observe
    from sentinel.feed import store

    def connect(dsn):
        conn = store.connect(dsn, connect_timeout=2, statement_timeout_ms=2000)
        conn.read_only = True
        return conn

    return observe(database_url, lease_seconds, connect=connect)


class WarmHealthReader(supervisor_health.WarmHealthReader):
    def __init__(self, database_url, lease_seconds, *, max_pulse_age, path=PATH):
        super().__init__(partial(_observe, database_url, lease_seconds), path=path,
                         max_pulse_age=max_pulse_age, read_seconds=READ_SECONDS)
