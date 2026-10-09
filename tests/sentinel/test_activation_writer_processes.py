"""Real supervisor/child/PG locking; external authority and finance are fixtures.

This suite does not simulate a PostgreSQL lock or worker acknowledgement. It
substitutes the economic worker payload and broker-free administrative payloads,
so it claims concurrency/ownership coverage, never financial admission.
"""
import contextlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from sentinel.execution import journal
from tests.sentinel.test_rolling_snapshot_publisher import conn, pg
from tests.sentinel.test_activation_writer_handoff import appliance, CLASSES, core


WORKER = r'''
import os,sys,time,psycopg
from pathlib import Path
from sentinel.execution import journal
root, mode = Path(sys.argv[1]), sys.argv[2]
with psycopg.connect(os.environ['HANDOFF_TEST_DSN']) as conn:
    with journal.writer_lock(conn, recovery_only=True):
        (root/'worker.pid').write_text(str(os.getpid()))
        if mode == 'hold': time.sleep(120)
    (root/'worker-finished').touch()
'''

SUPERVISOR = r'''
import os,subprocess,sys
from pathlib import Path
from types import SimpleNamespace
from sentinel import shadow_supervisor as shadow
root, mode, payload = Path(sys.argv[1]), sys.argv[2], sys.argv[3]
shadow.ShadowServiceConfig.from_env = lambda: SimpleNamespace(poll_seconds=300)
shadow.LATCH_FILE = root/'critical.json'
shadow.HEARTBEAT_FILE = root/'heartbeat'
shadow.shadow_worker_liveness.ACTIVE_FILE = root/'active.json'
shadow.shadow_budget.seconds = lambda: 120
spawn = subprocess.Popen
def worker(*args, **kwargs):
    return spawn([sys.executable, '-c', payload, str(root), mode],
                 stdin=subprocess.DEVNULL)
shadow.subprocess.Popen = worker
raise SystemExit(shadow.run())
'''


def until(predicate, *, seconds=10):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(.025)
    pytest.fail('real process did not reach its observed milestone')


@contextlib.contextmanager
def publisher(root, dsn, mode='hold'):
    root.mkdir(exist_ok=True)
    proc = subprocess.Popen([sys.executable, '-c', SUPERVISOR, str(root), mode, WORKER],
        env=dict(os.environ, HANDOFF_TEST_DSN=dsn), stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE, text=True)
    try:
        until(lambda: (root/'worker.pid').exists() or proc.poll() is not None)
        assert proc.poll() is None, proc.stderr.read()
        yield proc
    finally:
        if proc.poll() is None:
            proc.terminate()
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)
        proc.stderr.close()


def lock_is_available(conn):
    try:
        with journal.writer_lock(conn, recovery_only=True):
            return True
    except journal.WriterLockUnavailable:
        conn.rollback()
        return False


def test_real_attested_publisher_can_still_own_writer_slot(conn, tmp_path):
    with publisher(tmp_path/'original', conn.info.dsn) as process:
        assert not lock_is_available(conn)
        worker_pid = int((tmp_path/'original'/'worker.pid').read_text())
        process.terminate()
        assert process.wait(timeout=15) == 0
        assert lock_is_available(conn)
        assert not (tmp_path/'original'/'shadow-supervisor-pending.json').exists()
        with pytest.raises(ProcessLookupError):
            os.kill(worker_pid, 0)


@pytest.mark.parametrize('stop_failure', ['error', 'noop'])
def test_unsuccessful_stop_preserves_live_owner_and_never_dispatches(conn, tmp_path, stop_failure):
    obj, events, control, _ = appliance(tmp_path, CLASSES[-1])
    with publisher(tmp_path/'shadow', conn.info.dsn) as process:
        obj._running_shadow_containers = lambda: [str(process.pid)] if process.poll() is None else []
        obj._direct_stop_shadow = core.AutonomousDeploy._direct_stop_shadow.__get__(obj)
        def stop(args, **kwargs):
            assert args[:2] == ['docker', 'stop'] and str(process.pid) in args
            if stop_failure == 'error':
                raise core.DeployRefused('owned stop refused')
            return SimpleNamespace(returncode=0)
        obj.runner.run = stop
        with pytest.raises(core.DeployRefused):
            with obj.activation_transition():
                obj.prepare_activate_start('certificate', '2026-10-08')
        assert process.poll() is None and not lock_is_available(conn)
        assert (tmp_path/'shadow'/'shadow-supervisor-pending.json').exists()
        assert control['kill_switch_engaged'] and not control['enabled']
        assert 'prepare-paper-plan' not in events and 'start-automation' not in events


def test_retry_uses_canonical_deactivation_and_preserves_durable_cycle(conn, tmp_path):
    from sentinel import schema
    from sentinel.automation import store
    from sentinel.automation.model import AutomationConfig, CycleState, StaleLeaderRefused
    from sentinel.cli import automation
    from tests.sentinel.test_automation_store import identity, cycle_spec

    schema.ensure_schema(conn)
    cfg = AutomationConfig()
    bound = identity(cfg)
    store.activate(conn, binding=bound, actor='fixture', reason='fixture authority')
    control = store.release_kill(conn, expected_binding=bound, actor='fixture', reason='fixture release')
    permit = store.acquire_lease(conn, holder_id='old-worker', lease_seconds=30)
    cycle = store.create_cycle(conn, permit=permit, spec=cycle_spec(control, cfg))
    store.engage_kill(conn, actor='fixture', reason='readiness retry fence')

    def retained_cycle():
        with conn.cursor() as cursor:
            cursor.execute('SELECT row_to_json(c) FROM sentinel_automation_cycles c ORDER BY cycle_id')
            rows = cursor.fetchall()
            cursor.execute('SELECT row_to_json(e) FROM sentinel_automation_cycle_events e ORDER BY seq')
            events = cursor.fetchall()
        conn.rollback()
        return rows, events

    before = retained_cycle()
    obj, events, _, running = appliance(tmp_path, CLASSES[-1])
    running['shadow'] = False
    obj._automation_status = lambda: store.load_control(conn).model_dump(mode='json')

    def cli(args, **kwargs):
        assert args[0] == 'deactivate-paper-automation'
        result = automation._remove_automation_authority(
            SimpleNamespace(database_url=conn.info.dsn),
            SimpleNamespace(command=args[0], actor='fixture', reason='retry after fence'))
        assert result == 0
        events.append(args[0])
    obj._base_cli = cli
    obj.confirm_disabled_activation_fence()

    after = store.load_control(conn)
    assert not after.enabled and after.kill_switch_engaged
    assert after.binding == bound
    assert events == ['deactivate-paper-automation']
    assert retained_cycle() == before
    with pytest.raises(StaleLeaderRefused):
        store.transition_cycle(conn, permit=permit, cycle_id=cycle.cycle_id,
                               to_state=CycleState.PREPARING)


@pytest.mark.parametrize('cls', CLASSES)
@pytest.mark.parametrize('foreign', [False, True])
def test_actual_host_handoff_owns_processes_and_all_three_lock_boundaries(
        conn, tmp_path, cls, foreign):
    # Only fixture control/plan operations are substituted. Host sequencing,
    # Docker-command interpretation, real supervisor and PG locks stay real.
    obj, events, control, _ = appliance(tmp_path, cls)
    obj.cfg.health_timeout = 30
    with contextlib.ExitStack() as resources:
        original = resources.enter_context(publisher(tmp_path/'shadow', conn.info.dsn))
        processes = {'shadow': original, 'automation': None}
        foreign_process = None
        if foreign:
            # The foreign writer starts after the owned publisher relinquishes
            # its lock; it must refuse this attempt and must never be stopped.
            def foreign_after_stop():
                nonlocal foreign_process
                foreign_process = resources.enter_context(
                    publisher(tmp_path/'foreign', conn.info.dsn))
        else:
            foreign_after_stop = lambda: None

        def running(service):
            proc = processes[service]
            return [str(proc.pid)] if proc is not None and proc.poll() is None else []

        def run(args, **kwargs):
            if args[:2] == ['docker', 'ps']:
                service = ('automation' if any('sentinel-automation' in a for a in args)
                           else 'shadow')
                return SimpleNamespace(stdout='\n'.join(running(service)), returncode=0)
            if args[:2] == ['docker', 'stop']:
                for service, proc in processes.items():
                    if proc is not None and str(proc.pid) in args:
                        proc.terminate()
                        assert proc.wait(timeout=15) == 0
                        events.append('stopped-real-' + service)
                        if service == 'shadow':
                            assert '--time' in args and args[args.index('--time')+1] == '30'
                            assert not (tmp_path/'shadow'/'shadow-supervisor-pending.json').exists()
                            foreign_after_stop()
                return SimpleNamespace(stdout='', returncode=0)
            if args[-3:] == ['up', '-d', 'sentinel-shadow']:
                # Reuse the same real state directory, proving acknowledged
                # termination permits a fresh worker instead of clearing files.
                (tmp_path/'shadow'/'worker.pid').unlink()
                processes['shadow'] = resources.enter_context(
                    publisher(tmp_path/'shadow', conn.info.dsn, 'finish'))
                until(lambda: (tmp_path/'shadow'/'worker-finished').exists()
                      and not (tmp_path/'shadow'/'shadow-supervisor-pending.json').exists())
                events.append('start-real-shadow')
                return SimpleNamespace(stdout='', returncode=0)
            assert args[-3:] == ['up', '-d', 'sentinel-automation']
            assert 'reconcile-resumed' in events
            assert lock_is_available(conn)
            events.append('start-real-dispatcher')
            processes['automation'] = subprocess.Popen([sys.executable, '-c', 'import time;time.sleep(120)'])
            def cleanup_dispatcher():
                proc = processes['automation']
                if proc.poll() is None:
                    proc.terminate()
                proc.wait(timeout=5)
            resources.callback(cleanup_dispatcher)
            return SimpleNamespace(stdout='', returncode=0)

        obj.runner.run = run
        obj._running_shadow_containers = core.AutonomousDeploy._running_shadow_containers.__get__(obj)
        obj._running_automation_containers = core.AutonomousDeploy._running_automation_containers.__get__(obj)
        obj._direct_stop_shadow = core.AutonomousDeploy._direct_stop_shadow.__get__(obj)
        obj._direct_stop_automation = core.AutonomousDeploy._direct_stop_automation.__get__(obj)
        def cli(args, **kwargs):
            if args[0] != 'current-paper-plan':
                try:
                    with journal.writer_lock(conn):
                        events.append('actual-lock-' + args[0])
                except journal.WriterLockUnavailable as exc:
                    conn.rollback()
                    raise core.DeployRefused(str(exc)) from exc
            if args[0] == 'activate-paper-automation':
                control['enabled'] = True
            elif args[0] == 'release-paper-automation-kill-switch':
                control['kill_switch_engaged'] = False
            result = {'plan': {'plan_id': 'exact', 'decision_session': '2026-10-08'},
                      'database_authorities_match': True}
            events.append(args[0])
            return SimpleNamespace(stdout=json.dumps(result), returncode=0)
        obj._authorized_cli = obj._base_cli = cli
        def restore():
            assert not running('shadow') and not running('automation')
            assert control['enabled'] and control['kill_switch_engaged']
            assert lock_is_available(conn)
            events.append('fixture-restore-boundary')
        obj.establish_activation_backup = restore
        obj._running_shadow_containers = lambda: running('shadow')
        obj._running_automation_containers = lambda: running('automation')
        obj._verify_dual_plan_shadow_reconciliation = lambda: events.append(
            'reconcile-resumed' if running('shadow') else 'reconcile-plan')
        def health():
            from sentinel import shadow_supervisor as shadow
            saved = shadow.LATCH_FILE, shadow.HEARTBEAT_FILE, shadow.shadow_worker_liveness.ACTIVE_FILE
            try:
                shadow.LATCH_FILE = tmp_path/'shadow'/'critical.json'
                shadow.HEARTBEAT_FILE = tmp_path/'shadow'/'heartbeat'
                shadow.shadow_worker_liveness.ACTIVE_FILE = tmp_path/'shadow'/'active.json'
                assert shadow._service_health_snapshot(30) == 0
            finally:
                shadow.LATCH_FILE, shadow.HEARTBEAT_FILE, shadow.shadow_worker_liveness.ACTIVE_FILE = saved
        obj.wait_shadow_process = health
        if foreign:
            with pytest.raises(core.DeployRefused, match='writer lock'):
                with obj.activation_transition():
                    obj.prepare_activate_start('certificate', '2026-10-08')
            assert foreign_process.poll() is None
            assert control['kill_switch_engaged'] and not control['enabled']
            assert 'actual-lock-activate-paper-automation' not in events
        else:
            with obj.activation_transition():
                obj.prepare_activate_start('certificate', '2026-10-08')
            assert [e for e in events if e.startswith('actual-lock-')] == [
                'actual-lock-prepare-paper-plan', 'actual-lock-activate-paper-automation',
                'actual-lock-release-paper-automation-kill-switch']
            assert 'start-real-dispatcher' in events
            assert processes['shadow'].poll() is None
            proc = processes['automation']
            proc.terminate()
            proc.wait(timeout=5)
