"""Diagnostic phases from the currently owned host installation or activation."""
from contextlib import contextmanager, suppress
from contextvars import ContextVar
import fcntl
import os
from pathlib import Path
import re
import tempfile

_OWNER = ContextVar('deployment_progress_owner', default=None)
_PHASES = {
    'preflight': 'preflight', 'installation': 'software', 'select': 'software',
    'transition': 'fence', 'schema': 'schema', 'install': 'services',
    'integrity': 'integrity', 'durability': 'recovery', 'backup': 'recovery',
    'review': 'validation', 'ownership': 'account', 'authority': 'authority',
    'plan': 'plan', 'automation': 'automation', 'activation': 'activation',
    'prove': 'heartbeat', 'finalize': 'finalize',
}
_INSTALL_STAGES = {
    'installation: exact nonfinancial dashboard review schema': 'schema',
    'installation: create dormant exact financial services': 'dormant',
    'transition: start only behavioral PostgreSQL on preserved volume': 'postgres',
}
_GO_STAGES = {
    '=== PHASE C - CERTIFIED FINANCIAL PREPARATION ===': 'preparation',
    '=== PHASE D1 - WEALTH CORE PARITY ===': 'parity',
    '=== PHASE D2 - MARKET DATA READINESS ===': 'market_data',
    '=== PHASE D3 - DATABASE FINANCIAL HEALTH ===': 'database',
    '=== PROMOTE EXACT CERTIFIED RUNTIME ===': 'software',
    '=== POST-VALIDATION HANDOFF ===': 'validation',
}


def _write(fd, operation, stage):
    # One fixed-width write. An unrecognized or incomplete record is ignored.
    raw = (operation + ' ' + stage).encode('ascii').ljust(64)
    os.pwrite(fd, raw, 0)


@contextmanager
def reporting(authority, operation):
    """Called only inside the public lifecycle lock. No release gate depends on it."""
    directory = Path(authority) / 'operator-progress'
    fd = None
    temporary = None
    token = None
    try:
        try:
            try:
                directory.mkdir(mode=0o711)
            except FileExistsError:
                pass
            else:
                # The installer's private umask must permit the panel to traverse
                # this dedicated mount. Only the finite public record is readable.
                os.chmod(directory, 0o711)
            if not directory.is_symlink():
                fd, temporary = tempfile.mkstemp(prefix='.phase-', dir=str(directory))
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                _write(fd, operation, 'preflight')
                os.fchmod(fd, 0o644)
                os.replace(temporary, directory / 'current')
                temporary = None
                token = _OWNER.set((fd, operation))
        except OSError:
            pass
        yield
    finally:
        if token is not None:
            _OWNER.reset(token)
        if fd is not None:
            os.close(fd)
        if temporary is not None:
            with suppress(OSError):
                os.unlink(temporary)


def publish(stage):
    owner = _OWNER.get()
    if owner is not None:
        with suppress(OSError):
            _write(*owner, stage)


def phase(description):
    publish(_INSTALL_STAGES.get(description, _PHASES.get(description.partition(':')[0], 'working')))


class GoStages:
    """Recognize only complete public lines from the one supported GO child."""
    def __init__(self):
        self.pending = ''

    def consume(self, chunk):
        for part in chunk.splitlines(keepends=True):
            # Keep a bounded prefix, including an overflow byte, across pipe reads.
            self.pending += part[:max(0, 257 - len(self.pending))]
            if part.endswith('\n'):
                line = self.pending.rstrip('\r\n')
                self.pending = ''
                # GO can explicitly enable its normal terminal colors on a pipe.
                if line.endswith('\033[0m'):
                    line = line[:-4]
                    for prefix in ('\033[36m\033[1m', '\033[36m'):
                        if line.startswith(prefix):
                            line = line[len(prefix):]
                            break
                stage = _GO_STAGES.get(line)
                if re.fullmatch(r'\[RUN\]  verify database backup health \(deadline [0-9]+(?:\.[0-9]+)?s\)', line):
                    stage = 'backup_check'
                elif re.fullmatch(r'\[RUN\]  certified financial preparation \(deadline [0-9]+(?:\.[0-9]+)?s\)', line):
                    stage = 'preparation'
                if stage:
                    publish(stage)
