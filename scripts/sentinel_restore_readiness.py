"""Wait for this worker's startup phase before probing private PostgreSQL."""
import argparse
import os
import re
import selectors
import subprocess
import time

READINESS_SECONDS = 1200
MAX_LOG_BYTES = 1024 * 1024
PHASES = ('COPYING', 'VERIFYING', 'STARTING')


def _remaining(deadline, clock):
    remaining = deadline - clock()
    if remaining <= 0:
        raise RuntimeError('restore readiness deadline exhausted')
    return remaining


def wait_starting(container, token, *, deadline, clock=time.monotonic):
    """A scheduling hint only; the actual readiness/replay checks remain."""
    prefix = ('SENTINEL_RESTORE_PHASE=' + token + ':').encode('ascii')
    process = subprocess.Popen(['docker', 'logs', '--follow', container],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=0)
    try:
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ)
            buffer = b''
            total = index = 0
            while True:
                events = selector.select(min(1, _remaining(deadline, clock)))
                if not events:
                    if process.poll() is not None:
                        raise RuntimeError('restore worker ended before PostgreSQL startup')
                    continue
                chunk = os.read(process.stdout.fileno(), 4096)
                if not chunk:
                    raise RuntimeError('restore worker log ended before PostgreSQL startup')
                total += len(chunk)
                if total > MAX_LOG_BYTES:
                    raise RuntimeError('restore worker log exceeds readiness bound')
                buffer += chunk
                while b'\n' in buffer:
                    line, buffer = buffer.split(b'\n', 1)
                    if not line.startswith(prefix):
                        continue
                    if line != prefix + PHASES[index].encode('ascii'):
                        raise RuntimeError('restore worker phase sequence refused')
                    index += 1
                    if index == len(PHASES):
                        _remaining(deadline, clock)
                        return
    finally:
        if process.poll() is None:
            process.terminate()
        try:
            process.wait(timeout=1)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=1)
        process.stdout.close()


def wait_ready(container, token, *, seconds=READINESS_SECONDS,
               clock=time.monotonic, sleep=time.sleep, probe=subprocess.run):
    if (not re.fullmatch(r'sentinel-restore-drill-[A-Za-z0-9-]{1,150}', container)
            or not re.fullmatch(r'[A-Za-z0-9-]{1,150}', token)
            or container != 'sentinel-restore-drill-' + token
            or type(seconds) not in (int, float) or not 0 < seconds <= READINESS_SECONDS):
        raise RuntimeError('restore readiness invocation is malformed')
    deadline = clock() + seconds
    wait_starting(container, token, deadline=deadline, clock=clock)
    while True:
        remaining = _remaining(deadline, clock)
        try:
            result = probe(['docker', 'exec', container, 'pg_isready', '-U', 'sentinel', '-d', 'sentinel'],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=min(5, remaining))
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError('restore PostgreSQL readiness probe timed out') from exc
        _remaining(deadline, clock)
        if result.returncode == 0:
            return
        sleep(min(1, _remaining(deadline, clock)))


def main():
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument('--container', required=True)
    parser.add_argument('--token', required=True)
    args = parser.parse_args()
    try:
        wait_ready(args.container, args.token)
    except (OSError, RuntimeError) as exc:
        print('REFUSED: ' + str(exc))
        return 4
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
