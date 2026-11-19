"""Read the live host owner's public diagnostic phase from a read-only mount."""
import fcntl
import os
from pathlib import Path
import stat

_FILE = Path('/run/sentinel-install-progress/current')
_LABELS = {
    'preflight': 'checking the release', 'software': 'verifying the signed software',
    'fence': 'fencing services', 'schema': 'checking the database schema',
    'services': 'starting operator services', 'integrity': 'checking stored authority',
    'recovery': 'verifying the recovery checkpoint', 'validation': 'checking financial readiness',
    'account': 'checking the account binding', 'authority': 'verifying financial authority',
    'plan': 'preparing the plan', 'automation': 'starting automation',
    'activation': 'verifying the service handoff', 'heartbeat': 'checking the leader heartbeat',
    'finalize': 'verifying completion', 'working': 'in progress',
    'backup_check': 'checking backup health', 'preparation': 'checking financial inputs',
    'parity': 'verifying strategy parity', 'market_data': 'checking market data',
    'database': 'checking financial database health',
    'dormant': 'creating fenced services', 'postgres': 'starting the database',
}


def current():
    try:
        fd = os.open(_FILE, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        try:
            meta = os.fstat(fd)
            if not stat.S_ISREG(meta.st_mode) or meta.st_size != 64 or meta.st_nlink != 1:
                return None
            raw = os.read(fd, 65)
            if len(raw) != 64:
                return None
            operation, stage = raw.rstrip(b' ').decode('ascii').split(' ')
            title = {'install': 'Software installation', 'activate': 'Activation'}.get(operation)
            if title is None or stage not in _LABELS:
                return None
            try:
                fcntl.flock(fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
            except BlockingIOError:
                return title + ' · ' + _LABELS[stage]
            return None
        finally:
            os.close(fd)
    except (OSError, ValueError):
        return None
