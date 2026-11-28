"""One broker-free verification of a waiting plan after scheduler startup."""
from __future__ import annotations

from datetime import timedelta
import os
import signal
import subprocess
import sys


def start(runtime, now):
    """Called only by the leader after the scheduler proved an idle cycle."""
    child = getattr(runtime, '_opening_warm_process', None)
    if child is not None:
        if child.poll() is None:
            return
        runtime._opening_warm_process = None
    if (getattr(runtime, '_opening_warm_attempted', False)
            or not getattr(runtime, '_operational_source_only', False)
            or not (runtime._dual_run_enabled or getattr(runtime, '_live_run_enabled', False))):
        return
    parked = getattr(getattr(runtime, 'service', None), '_idle_cycle_proof', None)
    if not parked:
        return
    cycle = parked[1]
    if (cycle.state.value != 'WAITING_OPEN' or cycle.historical_state_only or not cycle.plan_id
            or cycle.execute_at - now <= timedelta(minutes=3)):
        return
    runtime._opening_warm_attempted = True
    try:
        runtime._opening_warm_process = subprocess.Popen(
            [sys.executable, '-m', __name__, str(os.getpid()), cycle.cycle_id],
            stdin=subprocess.DEVNULL, close_fds=True)
    except OSError as exc:
        print(f'opening prewarm unavailable: {type(exc).__name__}', file=sys.stderr, flush=True)


def stop(runtime):
    child = getattr(runtime, '_opening_warm_process', None)
    if child is not None:
        if child.poll() is None:
            child.kill()
        # The reader has its own exec'd process and owns no financial permit.
        # poll() reaps without making a due callback wait for kernel I/O.
        if child.poll() is not None:
            runtime._opening_warm_process = None


def verify_waiting(conn, *, cycle_id, observation_id, starting_cash):
    from sentinel import dual_reconciliation, prepared_opening_material, snapshot_scan_admission
    from sentinel.automation import store
    from sentinel.execution import feed_inputs, journal
    cycle = store.load_cycle(conn, cycle_id)
    now = conn.execute('SELECT clock_timestamp()').fetchone()[0]
    if (cycle.state.value != 'WAITING_OPEN' or cycle.historical_state_only or not cycle.plan_id
            or cycle.execute_at - now <= timedelta(minutes=2)):
        return
    signal.alarm(min(240, int((cycle.execute_at - now).total_seconds()) - 60))
    with snapshot_scan_admission.discretionary(), prepared_opening_material.cycle(cycle), feed_inputs.pinned(conn, commit=False):
        plan = journal.latest_plan(conn)
        if plan is None or plan.plan_id != cycle.plan_id or plan.fingerprint() != cycle.plan_fingerprint:
            return
        dual_reconciliation.require_plan_matches_verified_shadow(conn, plan=plan,
            observation_id=observation_id, starting_cash=starting_cash)


def main():
    from sentinel import supervisor_io
    from sentinel.config import SentinelConfig
    from sentinel.feed import store
    supervisor_io._parent_death(int(sys.argv[1]))
    signal.alarm(240)
    config = SentinelConfig.from_env()
    try:
        with store.connect(config.database_url, connect_timeout=2, statement_timeout_ms=45000) as conn:
            conn.read_only = True
            verify_waiting(conn, cycle_id=sys.argv[2],
                observation_id=os.environ.get('SENTINEL_SHADOW_OBSERVATION_ID', 'primary'),
                starting_cash=os.environ.get('SENTINEL_SHADOW_STARTING_CASH', '50000'))
    except Exception as exc:
        # The foreground retains the canonical proof path. Log no account data.
        print(f'opening prewarm incomplete: {type(exc).__name__}', file=sys.stderr, flush=True)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
