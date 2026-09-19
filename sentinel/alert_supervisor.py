"""Independent wall-clock enforcement for the broker-free alert dispatcher."""
import os
import select
import signal
import subprocess
import sys
import time

from sentinel import supervisor_io

PROGRESS_FD = 'SENTINEL_ALERT_PROGRESS_FD'


class DispatcherStalled(TimeoutError):
    pass


def progress():
    raw = os.environ.get(PROGRESS_FD)
    if raw is not None:
        os.write(int(raw), b'.')


def _terminate(child, grace_seconds):
    # Kill the private process group, including a dependency/reporting child.
    try:
        os.killpg(child.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        child.wait(timeout=grace_seconds)
    except subprocess.TimeoutExpired:
        pass
    try:
        os.killpg(child.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    child.wait(timeout=1)


def run_worker(command, *, deadline_seconds, stopping=lambda: False, grace_seconds=5):
    if deadline_seconds <= 0:
        raise ValueError('dispatcher deadline must be positive')
    reader, writer = os.pipe()
    os.set_blocking(writer, False)
    child = None
    try:
        env = dict(os.environ, **{PROGRESS_FD: str(writer)})
        child = subprocess.Popen(command, env=env, stdin=subprocess.DEVNULL,
                                 pass_fds=(writer,), start_new_session=True)
        os.close(writer)
        writer = None
        deadline = time.monotonic() + deadline_seconds
        while child.poll() is None and not stopping():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise DispatcherStalled('alert dispatcher made no bounded iteration progress')
            readable, _, _ = select.select([reader], [], [], min(.25, max(0., remaining)))
            if readable and os.read(reader, 4096):
                deadline = time.monotonic() + deadline_seconds
        return 0 if stopping() else child.returncode
    finally:
        os.close(reader)
        if writer is not None:
            os.close(writer)
        if child is not None:
            _terminate(child, grace_seconds)


def _report_stall():
    from sentinel.alert_service import WebhookAlertAdapter
    url = os.environ.get('SENTINEL_AUTOMATION_ALERT_WEBHOOK_URL', '').strip()
    if url:
        WebhookAlertAdapter(url, timeout_seconds=10).deliver_health_failure(
            'ALERT_DISPATCHER_STALLED', {'detail': 'dispatcher exceeded its wall-clock deadline'},
            int(time.time() // 60))


def main():
    deadline = float(os.environ.get('SENTINEL_ALERT_WORKER_DEADLINE_SECONDS', '120'))
    if not 90 <= deadline <= 600:
        raise ValueError('SENTINEL_ALERT_WORKER_DEADLINE_SECONDS must be in [90,600]')
    stopped = False
    def stop(*_):
        nonlocal stopped
        stopped = True
    for signum in (signal.SIGTERM, signal.SIGINT):
        signal.signal(signum, stop)
    while not stopped:
        try:
            return run_worker([sys.executable, '-m', 'sentinel.alert_service', '--worker'],
                              deadline_seconds=deadline, stopping=lambda: stopped)
        except DispatcherStalled as exc:
            supervisor_io.report('CRITICAL: ' + str(exc))
            try:
                supervisor_io.run(_report_stall, timeout=12)
            except Exception:
                supervisor_io.report('CRITICAL: independent dispatcher-stall report unavailable')
    return 0
